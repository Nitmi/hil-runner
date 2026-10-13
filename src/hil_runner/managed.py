from __future__ import annotations

import json
import os
import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .child import Child
from .common import MAX_REQUESTS, HilError, decode, invalid
from .lease import Lease
from .managed_plan import build_inputs, canonical, current, file_hash, read_plan, snapshot
from .selection import exact, text
from .server import OutputPump, requests

RESULT_SCHEMA = "embedded-hil-runner.managed-result.v1"


def result(operation, *, data=None, error=None, request_id=None, started=False, dispatched=False):
    return {
        "schema_version": RESULT_SCHEMA,
        "ok": error is None,
        "operation": operation,
        "request_id": request_id,
        "scope": "managed_native_component_execution",
        "authorization_granted": False,
        "component_processes_started": started,
        "hardware_access_possible": dispatched,
        "native_target_operations_dispatched": dispatched,
        "target_cleanup_verified": False,
        "data": data or {},
        "errors": [{"code": error.code, "message": str(error)[:1024]}] if error else [],
    }


def native_message(value, operation):
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0"
        or value.get("ok") is not True
        or value.get("operation") != operation
        or not isinstance(value.get("data"), dict)
    ):
        raise HilError("NATIVE_FAILURE", f"native {operation} did not return a successful envelope")
    return value["data"]


def artifact(value, expected: Path) -> tuple[dict, object]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise HilError("VERIFICATION_FAILED", "native artifact reference missing")
    path = Path(value["path"])
    if not path.samefile(expected) or value.get("sha256") != file_hash(expected):
        raise HilError("VERIFICATION_FAILED", "native evidence path or hash differs")
    if type(value.get("size")) is not int or value["size"] != expected.stat().st_size:
        raise HilError("VERIFICATION_FAILED", "native evidence size differs")
    return snapshot(expected, 4 * 1024 * 1024, value["sha256"])


class Manager:
    def __init__(self, body: dict, directory: Path, emit):
        self.body, self.directory, self.emit = body, directory, emit
        limits = body["limits"]
        self.lease = Lease(
            body["ownership"],
            duration=limits["duration_seconds"],
            idle=limits["idle_timeout_seconds"],
        )
        self.children: list[Child] = []
        self.flash: Child | None = None
        self.remaining = body["native_scope"]["max_flashes"]
        self.completed = []
        self.seen_ids: set[str] = set()
        self.build_lines: dict[str, str] = {}
        self.dispatched = False
        self.flash_uncertain = False
        self.closing = False
        self.native_expiry = datetime.fromisoformat(
            body["native_scope"]["expires_at"].replace("Z", "+00:00")
        )
        if self.native_expiry.tzinfo is None:
            raise invalid("native scope expiry must include timezone")

    def guard(self):
        self.lease.check_continuity()
        if not self.closing:
            self.lease.last_activity = time.monotonic()  # in-flight work is activity, not idle
            if self.lease.timeout() <= 0 or datetime.now(UTC) >= self.native_expiry:
                raise HilError("TIMEOUT", "managed or native scope duration expired")

    def command(self, *parts: str) -> list[str]:
        body = self.body
        command = [
            body["components"]["embedded-debugger"]["path"],
            "--backend",
            body["native_scope"]["backend"],
        ]
        if "replay_fixture" in body["inputs"]:
            command.extend(["--fixture", body["inputs"]["replay_fixture"]["path"]])
        return command + list(parts)

    def spawn(self, command, directory, name, *, jsonl=True):
        self.guard()
        current(self.body)
        child = Child(command, directory, name, jsonl=jsonl)
        self.children.append(child)
        return child

    def control(self, command, directory, name, *, version=None, operation=None):
        child = self.spawn(command, directory, name, jsonl=False)
        code, raw = child.control(self.body["limits"]["startup_timeout_seconds"], self.guard)
        cleanup = child.stop(self.body["limits"]["shutdown_timeout_seconds"])
        if code != 0 or not cleanup["process_tree_stopped"] or not cleanup["capture_complete"]:
            raise HilError(
                "NATIVE_FAILURE", "native control process failed or cleanup was incomplete"
            )
        if version is not None:
            if raw.decode("utf-8").strip() != version:
                raise HilError(
                    "VERIFICATION_FAILED", "component version differs from the selected lock"
                )
            return None
        return native_message(decode(raw), operation)

    def start(self):
        self.lease.acquire()
        current(self.body)
        directory = self.directory / "startup"
        directory.mkdir()
        for key, name in (("embedded-debugger", "embedded-debugger"), ("baud", "baud")):
            row = self.body["components"][key]
            self.control(
                [row["path"], "--version"],
                directory,
                key + "-version",
                version=name + " " + row["version"],
            )
        native = self.control(
            self.command(
                "flash", "session", "inspect", self.body["inputs"]["native_scope"]["path"], "--json"
            ),
            directory,
            "scope-inspect",
            operation="flash.session.inspect",
        )
        if (
            native.get("confirm_digest") != self.body["native_confirm_digest"]
            or native.get("scope") != self.body["native_scope"]
        ):
            raise HilError(
                "VERIFICATION_FAILED", "native scope inspection differs from the managed plan"
            )
        template = self.control(
            self.command(
                "runtime", "inspect", self.body["inputs"]["runtime_template"]["path"], "--json"
            ),
            directory,
            "runtime-inspect",
            operation="runtime.inspect",
        )
        if template.get("valid") is not True:
            raise HilError("VERIFICATION_FAILED", "native runtime template inspection failed")
        transcript = self.directory / "native-transcript"
        transcript.mkdir()
        self.flash = self.spawn(
            self.command(
                "flash",
                "session",
                "serve",
                self.body["inputs"]["native_scope"]["path"],
                "--confirm",
                self.body["native_confirm_digest"],
                "--transcript-dir",
                str(transcript),
            ),
            self.directory,
            "flash-session",
        )
        ready = native_message(
            self.flash.response(self.body["limits"]["startup_timeout_seconds"], self.guard),
            "flash.session.ready",
        )
        if (
            ready.get("confirm_digest") != self.body["native_confirm_digest"]
            or type(ready.get("remaining")) is not int
            or ready["remaining"] != self.remaining
        ):
            raise HilError("VERIFICATION_FAILED", "native ready count or confirmation differs")
        self.emit(
            result(
                "managed.ready",
                started=True,
                data={
                    "remaining": self.remaining,
                    "lease_id": self.lease.lease_id,
                    "resources": self.body["ownership"]["resources"],
                    "native_scope_confirmation_accepted": True,
                    "native_owner_pid": self.flash.process.pid,
                    "runtime_reset_capture_per_build": True,
                    "runtime_serial_zero_transmit": True,
                },
            )
        )

    def build(self, request: dict):
        current(self.body)
        inputs, contract = build_inputs(self.body, request)
        request_id = inputs["id"]
        if request_id in self.seen_ids:
            raise invalid("build request id was already consumed")
        self.seen_ids.add(request_id)
        line = contract["serial"]["build_id_line"]
        previous = self.build_lines.setdefault(line, inputs["firmware"]["sha256"])
        if previous != inputs["firmware"]["sha256"]:
            raise invalid("different firmware builds cannot share the same reported BUILD line")
        budget = (
            2 * self.body["limits"]["native_timeout_seconds"]
            + self.body["limits"]["startup_timeout_seconds"]
            + self.body["limits"]["shutdown_timeout_seconds"]
        )
        available = min(
            self.lease.started + self.lease.duration - time.monotonic(),
            (self.native_expiry - datetime.now(UTC)).total_seconds(),
        )
        if available < budget:
            raise HilError(
                "TIMEOUT", "not enough remaining scope budget for a complete build and cleanup"
            )
        directory = self.directory / f"build-{len(self.completed) + 1:04d}"
        directory.mkdir(mode=0o700)
        copies = {}
        for key, filename in (
            ("firmware", "firmware." + self.body["native_scope"]["firmware_format"]),
            ("runtime_contract", "runtime.contract.json"),
        ):
            source = Path(inputs[key]["path"])
            destination = directory / filename
            import hashlib

            hasher = hashlib.sha256()
            size = 0
            with source.open("rb") as original, destination.open("xb") as copied:
                while chunk := original.read(1024 * 1024):
                    size += len(chunk)
                    if size > 256 * 1024 * 1024:
                        raise invalid("build snapshot exceeds 256 MiB")
                    hasher.update(chunk)
                    copied.write(chunk)
                copied.flush()
                os.fsync(copied.fileno())
            if hasher.hexdigest() != inputs[key]["sha256"]:
                raise HilError("INPUT_DRIFT", "build input changed while being snapshotted")
            copies[key] = {"path": str(destination), "sha256": hasher.hexdigest()}
        inspected = self.control(
            self.command("runtime", "inspect", copies["runtime_contract"]["path"], "--json"),
            directory,
            "runtime-inspect",
            operation="runtime.inspect",
        )
        if inspected.get("valid") is not True:
            raise HilError("VERIFICATION_FAILED", "native build runtime contract is invalid")
        # Recheck the changing build files immediately before asking the native executor.
        current(self.body)
        if file_hash(Path(copies["firmware"]["path"])) != inputs["firmware"]["sha256"]:
            raise HilError("INPUT_DRIFT", "firmware changed during preflight")
        snapshot(
            Path(copies["runtime_contract"]["path"]),
            64 * 1024,
            inputs["runtime_contract"]["sha256"],
        )
        evidence = directory / "flash.evidence.json"
        native_request = {
            "operation": "flash",
            "firmware": copies["firmware"]["path"],
            "evidence": str(evidence),
        }
        timeout = self.body["limits"]["native_timeout_seconds"]
        self.dispatched = self.flash_uncertain = True
        self.flash.send((json.dumps(native_request) + "\n").encode(), timeout, self.guard)
        flashed = native_message(self.flash.response(timeout, self.guard), "flash.session.flash")
        execution = flashed.get("execution", {})
        if (
            flashed.get("remaining") != self.remaining - 1
            or type(flashed.get("remaining")) is not int
            or execution.get("flash", {}).get("verified") is not True
            or execution.get("plan", {}).get("firmware", {}).get("sha256")
            != inputs["firmware"]["sha256"]
        ):
            raise HilError(
                "VERIFICATION_FAILED",
                "native flash verification, firmware identity or count differs",
            )
        flash_ref, flash_evidence = artifact(execution.get("evidence"), evidence)
        if flash_evidence.get("complete") is not True:
            raise HilError("VERIFICATION_FAILED", "native flash cleanup evidence is incomplete")
        self.remaining -= 1
        self.flash_uncertain = False
        runtime_path = directory / "runtime.evidence.json"
        # Runtime acceptance owns serial discovery/open, assertions, one reset and cleanup.
        self.guard()
        snapshot(
            Path(copies["runtime_contract"]["path"]),
            64 * 1024,
            inputs["runtime_contract"]["sha256"],
        )
        runtime = self.spawn(
            self.command(
                "runtime",
                "accept",
                "--contract",
                copies["runtime_contract"]["path"],
                "--baud-executable",
                self.body["components"]["baud"]["path"],
                "--evidence",
                str(runtime_path),
                "--json",
            ),
            directory,
            "runtime",
            jsonl=False,
        )
        code, raw = runtime.control(timeout, self.guard)
        cleanup = runtime.stop(self.body["limits"]["shutdown_timeout_seconds"])
        if (
            code != 0
            or not cleanup["process_tree_stopped"]
            or cleanup["forced_termination"]
            or not cleanup["capture_complete"]
        ):
            raise HilError("NATIVE_FAILURE", "native runtime acceptance or process cleanup failed")
        accepted = native_message(decode(raw), "runtime.accept")
        runtime_ref, runtime_evidence = artifact(accepted.get("evidence"), runtime_path)
        report = accepted.get("report", {})
        if (
            runtime_evidence != report
            or report.get("accepted") is not True
            or report.get("complete") is not True
            or report.get("assertions", {}).get("passed") is not True
            or report.get("assertions", {}).get("build_identity", {}).get("required") is not True
            or report.get("reset_capture", {}).get("complete") is not True
            or report.get("contract", {}).get("captured", {}).get("sha256")
            != inputs["runtime_contract"]["sha256"]
        ):
            raise HilError(
                "VERIFICATION_FAILED", "native runtime evidence or required BUILD assertion differs"
            )
        if file_hash(Path(copies["firmware"]["path"])) != inputs["firmware"]["sha256"]:
            raise HilError("INPUT_DRIFT", "firmware changed while it was being accepted")
        summary = {
            "id": request_id,
            "inputs": inputs,
            "snapshots": copies,
            "flash": flash_ref,
            "runtime": runtime_ref,
            "remaining": self.remaining,
            "native_cleanup_evidence_verified": True,
        }
        (directory / "build-result.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        self.completed.append(summary)
        self.emit(
            result(
                "managed.build", data=summary, request_id=request_id, started=True, dispatched=True
            )
        )

    def cleanup(self, reason: str) -> dict:
        self.closing = True
        close_error = None
        if self.flash is not None and self.flash.process.poll() is None:
            try:
                if not self.flash_uncertain:
                    timeout = self.body["limits"]["shutdown_timeout_seconds"]
                    self.flash.send(b'{"operation":"close"}\n', timeout, lambda: None)
                    native_message(
                        self.flash.response(timeout, lambda: None), "flash.session.close"
                    )
                    self.flash.wait(timeout, lambda: None)
                else:
                    # No further protocol request after an indeterminate mutation.
                    self.flash.process.stdin.close()
                    self.flash.wait(self.body["limits"]["shutdown_timeout_seconds"], lambda: None)
            except (HilError, OSError) as error:
                close_error = type(error).__name__
        rows = [
            child.stop(self.body["limits"]["shutdown_timeout_seconds"])
            for child in reversed(self.children)
        ]
        # Resource ownership ends only after process tree termination has been checked.
        if all(row["process_tree_stopped"] for row in rows):
            lease_cleanup = self.lease.release(reason)
        else:
            lease_cleanup = {
                "status": "retained_until_owner_exit",
                "host_handles_closed": False,
                "resources": self.body["ownership"]["resources"],
            }
        complete = not close_error and all(
            row["process_tree_stopped"]
            and row["capture_complete"]
            and not row["forced_termination"]
            and row["exit_code"] == 0
            for row in rows
        )
        transcript_verified = False
        if self.flash is not None and all(row["capture_complete"] for row in rows):
            transcript = self.directory / "native-transcript/responses.jsonl"
            if transcript.exists():
                transcript_verified = (
                    transcript.read_bytes() == self.flash.stdout.destination.read_bytes()
                )
                complete = complete and transcript_verified
        return {
            "reason": reason,
            "builds_passed": len(self.completed),
            "remaining": self.remaining,
            "children": rows,
            "lease": lease_cleanup,
            "complete": complete,
            "native_transcript_matches_capture": transcript_verified,
            "close_error": close_error,
            "target_cleanup_verified": False,
        }


def execute(
    plan_path: Path, expected: str, confirm: str, directory: Path, *, allow_runtime_reset: bool
) -> int:
    if os.name != "nt":
        raise HilError(
            "UNSUPPORTED_PLATFORM",
            "managed execution currently requires Windows process containment",
        )
    body = read_plan(plan_path, expected)
    if confirm != body["native_confirm_digest"]:
        raise invalid("confirmation must be the once-approved native scope digest")
    if not allow_runtime_reset:
        raise invalid(
            "managed execution requires the declared per-build runtime reset-capture scope"
        )
    if Path(body["inputs"]["native_scope"]["path"] + ".active").exists():
        raise invalid("native one-use scope is already consumed; do not remove its marker")
    directory = canonical(directory, strict=False)
    if not directory.is_relative_to(canonical(Path(body["native_scope"]["firmware_directory"]))):
        raise invalid(
            "managed output directory must be inside the native firmware directory for snapshots"
        )
    directory.mkdir(mode=0o700, exist_ok=False)
    output = OutputPump()
    manager = Manager(body, directory, output.emit)
    failure = None
    reason = "host_error"
    request_log = None
    try:
        request_log = (directory / "managed-requests.jsonl").open("xb")
        manager.start()
        messages: queue.Queue = queue.Queue(maxsize=16)
        threading.Thread(target=requests, args=(os.dup(0), messages), daemon=True).start()
        processed = 0
        while processed < MAX_REQUESTS:
            if manager.remaining == 0:
                reason = "count_exhausted"
                break
            manager.lease.check_continuity()
            if manager.lease.timeout() <= 0:
                reason = manager.lease.expiry_reason()
                break
            if datetime.now(UTC) >= manager.native_expiry:
                reason = "native_scope_expired"
                break
            if manager.flash.process.poll() is not None:
                raise HilError(
                    "NATIVE_FAILURE", "native scope executor exited before count exhaustion"
                )
            try:
                kind, payload = messages.get(timeout=min(0.25, manager.lease.timeout()))
            except queue.Empty:
                # Do not count idle polls against the protocol request budget.
                continue
            if kind == "eof":
                reason = "stdin_eof"
                break
            if kind != "line":
                raise invalid("managed stdin size or I/O limit exceeded")
            processed += 1
            request_log.write(payload + b"\n")
            request_log.flush()
            value = decode(payload)
            if isinstance(value, dict) and value.get("operation") == "close":
                exact(value, {"id", "operation"}, "close request")
                text(value["id"], "request id", maximum=64)
                reason = "requested"
                break
            manager.build(value)
            manager.lease.last_activity = time.monotonic()
        else:
            raise invalid("256 managed request limit exceeded")
    except HilError as error:
        failure = error
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        failure = HilError("HOST_IO_ERROR", str(error))
    except KeyboardInterrupt:
        failure = HilError("INTERRUPTED", "managed owner interrupted")
        reason = "interrupted"
    finally:
        if request_log is not None:
            request_log.close()
        cleanup = manager.cleanup(reason)
    if not cleanup["complete"] and failure is None:
        failure = HilError(
            "VERIFICATION_FAILED", "managed process cleanup or capture is incomplete"
        )
    final = result(
        "managed.closed",
        data=cleanup,
        error=failure,
        started=bool(manager.children),
        dispatched=manager.dispatched,
    )
    (directory / "managed-result.json").write_text(
        json.dumps(final, indent=2) + "\n", encoding="utf-8"
    )
    try:
        output.emit(final)
    except OSError:
        return 4
    flushed = output.finish()
    if not flushed:
        return 4
    return (3 if failure and failure.code == "RESOURCE_BUSY" else 2) if failure else 0
