from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hil_runner.common import digest

from .conftest import selection


def write(path: Path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def prepare(directory: Path):
    build = directory / "build"
    build.mkdir()
    scope_path = directory / "native-scope.json"
    programs = {}
    for name, version in (("embedded-debugger", "0.2.5"), ("baud", "0.1.2"), ("blea", "0.7.0")):
        path = directory / (name + ".exe")
        path.write_bytes(name.encode())
        programs[name] = {
            "path": str(path.resolve()),
            "version": version,
            "sha256": digest(path.read_bytes()),
        }
    write(directory / "selection.json", selection(transports=("debug", "serial")))
    write(
        directory / "lock.json",
        {"schema_version": "embedded-agent-toolkit.component-lock.v2", "components": programs},
    )
    now = datetime.now(UTC)
    native = {
        "schema_version": "embedded-debugger.flash-session.v1",
        "executor_sha256": programs["embedded-debugger"]["sha256"],
        "scope_path": str(scope_path.resolve()),
        "backend": "replay",
        "probe": "ffff:0001:CI-A",
        "target": "STM32G431CBTx",
        "firmware_directory": str(build.resolve()),
        "firmware_format": "bin",
        "duration_seconds": 300,
        "max_flashes": 2,
        "expires_at": (now + timedelta(seconds=300)).isoformat(),
    }
    write(scope_path, native)
    template = {
        "schema_version": "1.0",
        "name": "ci-runtime",
        "board": "ci-fixture",
        "target": native["target"],
        "debug": {
            "probe": native["probe"],
            "operation": "snapshot.reset-capture",
            "automatic_retries": 0,
        },
        "firmware": {},
        "flash": {
            "exact_probe_selector_required": True,
            "exact_confirmation_digest_required": True,
            "automatic_retries": 0,
        },
        "serial": {
            "exact_port_identity_required": True,
            "port": "COM999",
            "usb_vendor_id": "FFFF",
            "usb_product_id": "0001",
            "usb_serial_number": "CI-A",
            "usb_interface": None,
            "baud": 115200,
            "data_bits": 8,
            "parity": "none",
            "stop_bits": 1,
            "flow_control": "none",
            "dtr": False,
            "rts": False,
            "transmit_bytes": 0,
            "observe_duration_seconds": 1,
            "monitor_startup_delay_ms": 400,
            "ready_line": "HIL_READY v1",
            "build_id_line": None,
            "heartbeat_line": "HIL_HEARTBEAT",
            "minimum_complete_heartbeats": 3,
            "forbidden_complete_lines": ["HIL_FAULT"],
        },
        "visual": None,
        "abort_conditions": ["stop on indeterminate native result"],
        "cleanup": {
            "close_serial_session": True,
            "disconnect_debug_session": True,
            "do_not_retry_state_changing_failures": True,
        },
    }
    write(directory / "runtime-template.json", template)
    write(directory / "replay.json", {"fixture": "not executed"})
    spec = {
        "schema_version": "embedded-hil-runner.managed-spec.v1",
        "selection": "selection.json",
        "component_lock": "lock.json",
        "native_scope": "native-scope.json",
        "native_confirm_digest": "a" * 64,
        "runtime_template": "runtime-template.json",
        "replay_fixture": "replay.json",
        "limits": {
            "duration_seconds": 300,
            "idle_timeout_seconds": 5,
            "native_timeout_seconds": 30,
            "startup_timeout_seconds": 5,
            "shutdown_timeout_seconds": 3,
        },
    }
    write(directory / "spec.json", spec)
    firmware = build / "a.bin"
    firmware.write_bytes(b"BUILD-A")
    template["firmware"] = {"sha256": digest(firmware.read_bytes())}
    template["serial"]["build_id_line"] = "HIL_BUILD A"
    runtime = write(build / "runtime-a.json", template)
    request = {
        "id": "A",
        "operation": "build",
        "firmware": str(firmware),
        "firmware_sha256": digest(firmware.read_bytes()),
        "runtime_contract": str(runtime),
        "runtime_sha256": digest(runtime.read_bytes()),
    }
    return directory / "spec.json", request
