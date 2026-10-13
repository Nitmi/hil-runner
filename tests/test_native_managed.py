from __future__ import annotations

import contextlib
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path

import jsonschema
import pytest

from hil_runner.common import digest
from hil_runner.lease import Lease
from hil_runner.managed_plan import compile_plan

from .managed_fixtures import prepare, write

NATIVE = os.environ.get("HIL_NATIVE_DEBUGGER_TEST_EXE")
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not NATIVE, reason="explicit native Replay executable required"
)


@pytest.fixture(scope="session")
def fixture_program(tmp_path_factory):
    directory = tmp_path_factory.mktemp("fixture-baud")
    output = directory / "baud-fixture.exe"
    source = Path(__file__).parent / "fixtures/baud_fixture.rs"
    subprocess.run(
        ["rustc", "--edition=2021", str(source), "-o", str(output)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return output


def setup_native(tmp_path, fixture_program, *, max_flashes=2, mode="normal", native_timeout=30):
    spec_path, request_a = prepare(tmp_path)
    program = tmp_path / "fixture-baud.exe"
    program.write_bytes(fixture_program.read_bytes())
    (tmp_path / "next-build.txt").write_text("HIL_BUILD A")
    (tmp_path / "mode.txt").write_text(mode)
    native = Path(NATIVE).resolve()
    assert digest(native.read_bytes()) == os.environ["HIL_NATIVE_DEBUGGER_TEST_SHA256"]
    spec = json.loads(spec_path.read_bytes())
    lock = json.loads((tmp_path / "lock.json").read_bytes())
    lock["components"]["embedded-debugger"] = {
        "path": str(native),
        "version": os.environ.get("HIL_NATIVE_DEBUGGER_TEST_VERSION", "0.2.5"),
        "sha256": digest(native.read_bytes()),
    }
    lock["components"]["baud"] = {
        "path": str(program),
        "version": "0.1.2",
        "sha256": digest(program.read_bytes()),
    }
    write(tmp_path / "lock.json", lock)
    fixture_path = Path(os.environ["HIL_NATIVE_REPLAY_FIXTURE"])
    fixture = json.loads(fixture_path.read_bytes())
    fixture["probe"].update(
        id="ffff:0001:CI-A", vendor_id=65535, product_id=1, serial_number="CI-A"
    )
    fixture["control_cores"][0]["state"] = "running"
    fixture["control_cores"][0]["halt_reason"] = None
    write(tmp_path / "replay.json", fixture)
    (tmp_path / "native-scope.json").unlink()  # Only our synthetic prepare() placeholder.
    command = [
        str(native),
        "--backend",
        "replay",
        "flash",
        "session",
        "plan",
        "--probe",
        "ffff:0001:CI-A",
        "--target",
        "STM32G431CBTx",
        "--firmware-directory",
        str(tmp_path / "build"),
        "--format",
        "bin",
        "--base-address",
        "0x08000000",
        "--write-start",
        "0x08000000",
        "--write-length",
        "64",
        "--erase-start",
        "0x08000000",
        "--erase-length",
        "2048",
        "--max-flashes",
        str(max_flashes),
        "--duration-seconds",
        "300",
        "--output",
        str(tmp_path / "native-scope.json"),
        "--json",
    ]
    planned = subprocess.run(command, capture_output=True, timeout=10)
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(planned.stdout)["data"]
    (tmp_path / "native-plan.stdout.json").write_bytes(planned.stdout)
    spec["native_confirm_digest"] = plan["confirm_digest"]
    spec["limits"]["native_timeout_seconds"] = native_timeout
    write(spec_path, spec)
    managed = compile_plan(spec_path, tmp_path / "managed-plan.json", tmp_path / "leases")
    firmware_b = tmp_path / "build/b.bin"
    firmware_b.write_bytes(b"BUILD-B")
    runtime_b = json.loads((tmp_path / "build/runtime-a.json").read_bytes())
    runtime_b["firmware"] = {"sha256": digest(firmware_b.read_bytes())}
    runtime_b["serial"]["build_id_line"] = "HIL_BUILD B"
    write(tmp_path / "build/runtime-b.json", runtime_b)
    request_b = {
        **request_a,
        "id": "B",
        "firmware": str(firmware_b),
        "firmware_sha256": digest(firmware_b.read_bytes()),
        "runtime_contract": str(tmp_path / "build/runtime-b.json"),
        "runtime_sha256": digest((tmp_path / "build/runtime-b.json").read_bytes()),
    }
    command = [
        sys.executable,
        "-u",
        "-m",
        "hil_runner",
        "managed",
        "serve",
        str(tmp_path / "managed-plan.json"),
        "--plan-sha256",
        managed["sha256"],
        "--confirm",
        plan["confirm_digest"],
        "--allow-runtime-reset",
        "--output-dir",
        str(tmp_path / "build/run"),
    ]
    return command, request_a, request_b


class NativeLive:
    def __init__(self, command):
        self.child = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        self.messages = queue.Queue()
        self.schema = json.loads(
            (Path(__file__).parents[1] / "schemas/managed-result.schema.json").read_bytes()
        )

        def read():
            for line in iter(self.child.stdout.readline, b""):
                self.messages.put(line)
            self.messages.put(None)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def line(self):
        # Allow the configured 30 s native deadline and bounded cleanup to report.
        raw = self.messages.get(timeout=45)
        assert raw is not None, "unexpected owner EOF"
        message = json.loads(raw)
        jsonschema.validate(message, self.schema)
        return message

    def send(self, value):
        self.child.stdin.write(json.dumps(value).encode() + b"\n")
        self.child.stdin.flush()

    def finish(self, code):
        assert self.child.wait(timeout=10) == code
        assert self.child.stderr.read() == b""

    def dispose(self):
        if self.child.poll() is None:
            self.child.kill()
        self.child.wait(timeout=5)
        self.reader.join(timeout=1)
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            with contextlib.suppress(OSError):
                stream.close()


def test_native_two_builds_share_one_grant_and_preserve_transcript(tmp_path, fixture_program):
    command, a, b = setup_native(tmp_path, fixture_program)
    owner = NativeLive(command)
    try:
        ready = owner.line()
        assert ready["ok"], ready
        assert ready["operation"] == "managed.ready"
        owner.send(a)
        first = owner.line()
        assert first["ok"] and first["request_id"] == "A", first
        (tmp_path / "next-build.txt").write_text("HIL_BUILD B")
        owner.send(b)
        second = owner.line()
        assert second["ok"] and second["request_id"] == "B", second
        final = owner.line()
        assert final["ok"] and final["data"]["reason"] == "count_exhausted", final
        assert final["data"]["builds_passed"] == 2 and final["data"]["complete"]
        owner.finish(0)
        transcript = tmp_path / "build/run/native-transcript"
        assert (transcript / "responses.jsonl").read_bytes() == (
            tmp_path / "build/run/flash-session.stdout.jsonl"
        ).read_bytes()
        rows = [
            json.loads(line) for line in (transcript / "requests.jsonl").read_bytes().splitlines()
        ]
        assert len(rows) == 2 and all(row["operation"] == "flash" for row in rows)
        assert (tmp_path / "native-scope.json.active").exists()
    finally:
        owner.dispose()


def test_failed_runtime_stops_before_queued_second_build(tmp_path, fixture_program):
    command, a, b = setup_native(tmp_path, fixture_program)
    (tmp_path / "next-build.txt").write_text("WRONG_BUILD")
    owner = NativeLive(command)
    try:
        assert owner.line()["ok"]
        owner.send(a)
        owner.send(b)
        final = owner.line()
        assert not final["ok"] and final["operation"] == "managed.closed", final
        assert final["data"]["builds_passed"] == 0
        owner.finish(2)
        rows = [
            json.loads(line)
            for line in (tmp_path / "build/run/native-transcript/requests.jsonl")
            .read_bytes()
            .splitlines()
        ]
        assert sum(row["operation"] == "flash" for row in rows) == 1
        assert not (tmp_path / "build/run/build-0002").exists()
    finally:
        owner.dispose()


def test_native_runtime_hang_terminates_nested_tree_without_target_claim(tmp_path, fixture_program):
    command, a, _ = setup_native(tmp_path, fixture_program, mode="hang", native_timeout=11)
    owner = NativeLive(command)
    try:
        assert owner.line()["ok"]
        owner.send(a)
        final = owner.line()
        assert not final["ok"] and not final["target_cleanup_verified"], final
        assert any(row["forced_termination"] for row in final["data"]["children"])
        assert all(row["process_tree_stopped"] for row in final["data"]["children"])
        owner.finish(2)
    finally:
        owner.dispose()


def test_lease_conflict_does_not_consume_native_scope(tmp_path, fixture_program):
    command, _, _ = setup_native(tmp_path, fixture_program)
    body = json.loads((tmp_path / "managed-plan.json").read_bytes())
    blocker = Lease(body["ownership"], duration=30, idle=30)
    blocker.acquire()
    owner = NativeLive(command)
    try:
        final = owner.line()
        assert final["errors"][0]["code"] == "RESOURCE_BUSY"
        assert not final["component_processes_started"]
        assert not (tmp_path / "native-scope.json.active").exists()
        owner.finish(3)
    finally:
        owner.dispose()
        blocker.release("test")


def test_eof_closes_native_before_releasing_resources(tmp_path, fixture_program):
    command, _, _ = setup_native(tmp_path, fixture_program)
    owner = NativeLive(command)
    try:
        assert owner.line()["ok"]
        owner.child.stdin.close()
        final = owner.line()
        assert final["ok"] and final["data"]["reason"] == "stdin_eof"
        assert final["data"]["complete"]
        assert all(row["process_tree_stopped"] for row in final["data"]["children"])
        owner.finish(0)
    finally:
        owner.dispose()


def test_killed_managed_owner_kills_native_job(tmp_path, fixture_program):
    command, _, _ = setup_native(tmp_path, fixture_program)
    owner = NativeLive(command)
    handle = None
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        ready = owner.line()
        assert ready["ok"]
        handle = api.OpenProcess(0x00100000, False, ready["data"]["native_owner_pid"])
        assert handle
        owner.child.kill()
        owner.child.wait(timeout=5)
        assert api.WaitForSingleObject(handle, 5000) == 0
        assert (tmp_path / "native-scope.json.active").exists()
    finally:
        if handle:
            api.CloseHandle(handle)
        owner.dispose()
