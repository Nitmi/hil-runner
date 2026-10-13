from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from contextlib import suppress
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hil_runner.common import digest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = Draft202012Validator(json.loads((ROOT / "schemas/result.schema.json").read_bytes()))


def selection(*, transports=("debug",), serial="CI-A", port="COM999"):
    identities = {
        "debug": {"probe_selector": "ffff:0001:" + serial},
        "serial": {"port": port, "usb_vid": "FFFF", "usb_pid": "0001", "usb_serial": serial},
        "ble": {"identifier": "AB:CD:00:00:00:01", "local_name": "fixture"},
    }
    return {
        "schema_version": "embedded-board-registry.selection.v1",
        "ok": True,
        "status": "selected",
        "board_id": "ci-fixture",
        "required_transports": sorted(transports),
        "bindings": [
            {
                "transport": kind,
                "selector_id": kind + "-selector",
                "observation_id": kind + "-observed",
                "selector_identity": identities[kind].copy(),
                "observed_identity": identities[kind].copy(),
                "source": {"path": "synthetic.json", "sha256": "a" * 64, "point_in_time": True},
            }
            for kind in sorted(transports)
        ],
        "inputs": {
            key: {"path": key + ".json", "sha256": "b" * 64} for key in ("registry", "observations")
        },
        "authorization": {"granted": False, "allowed_operations": []},
        "hardware_access": False,
        "executables_started": False,
    }


@pytest.fixture
def saved(tmp_path):
    def write(value=None, *, name="selection.json", **options):
        path = tmp_path / name
        path.write_text(
            json.dumps(value if value is not None else selection(**options)), encoding="utf-8"
        )
        return path

    return write


def cli(*args):
    return [sys.executable, "-u", "-m", "hil_runner", *map(str, args)]


class Live:
    def __init__(self, path, namespace, *, duration=20, idle=10, expected=None):
        self.messages = queue.Queue()
        self.process = subprocess.Popen(
            cli(
                "lease",
                "serve",
                path,
                "--selection-sha256",
                expected or digest(path.read_bytes()),
                "--lease-root",
                namespace,
                "--duration-seconds",
                duration,
                "--idle-timeout-seconds",
                idle,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in iter(self.process.stdout.readline, b""):
            self.messages.put(line)
        self.messages.put(None)

    def line(self, timeout=5):
        payload = self.messages.get(timeout=timeout)
        assert payload is not None, "unexpected protocol EOF"
        value = json.loads(payload)
        VALIDATOR.validate(value)
        return value

    def send(self, value):
        self.process.stdin.write(json.dumps(value).encode() + b"\n")
        self.process.stdin.flush()

    def close(self, lease_id):
        self.send({"id": "close", "operation": "lease.close", "lease_id": lease_id})
        value = self.line()
        assert value["ok"] and value["operation"] == "lease.close"
        self.wait()
        return value

    def wait(self, code=0):
        assert self.process.wait(timeout=5) == code
        self.reader.join(timeout=1)
        assert not self.reader.is_alive()
        assert self.process.stderr.read() == b""

    def dispose(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            with suppress(OSError):
                stream.close()


@pytest.fixture
def live(tmp_path):
    children = []

    def launch(path, **options):
        child = Live(path, tmp_path / "shared-leases", **options)
        children.append(child)
        return child

    yield launch
    for child in children:
        child.dispose()
