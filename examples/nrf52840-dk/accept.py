"""One approved DK A/B run through the installed HIL Runner; no hardware retries."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from hil_runner.child import Child
from hil_runner.common import HilError
from hil_runner.managed_plan import build_inputs, file_hash, read_plan


def check_message(message, operation, request_id=None):
    if (
        message.get("schema_version") != "embedded-hil-runner.managed-result.v1"
        or message.get("ok") is not True
        or message.get("operation") != operation
        or message.get("request_id") != request_id
    ):
        raise ValueError(f"managed run stopped: {message}")


def prepare(root: Path, plan_sha256: str):
    body = read_plan(root / "managed-plan.json", plan_sha256)
    scope = body["native_scope"]
    if (
        scope["backend"] != "probe-rs"
        or scope["probe"] != "1366:1061:001050275757"
        or scope["target"] != "nRF52840_xxAA"
        or scope["max_flashes"] != 2
        or scope["firmware_format"] != "hex"
        or scope["write_window"] != {"start": "0x00000000", "length": 4096}
        or scope["erase_window"] != {"start": "0x00000000", "length": 4096}
    ):
        raise ValueError(
            "this client only accepts the reviewed onboard DK two-build first-page scope"
        )
    serial = body["runtime_template"]["serial"]
    if any(
        serial.get(key) != expected
        for key, expected in {
            "port": "COM11",
            "usb_vendor_id": "1366",
            "usb_product_id": "1061",
            "usb_serial_number": "001050275757",
            "baud": 115200,
            "dtr": True,
            "rts": False,
            "transmit_bytes": 0,
            "observe_duration_seconds": 15,
            "minimum_complete_heartbeats": 3,
        }.items()
    ):
        raise ValueError("runtime serial scope differs")
    manifest = json.loads((root / "firmware-final/manifest.json").read_bytes())
    if [variant["variant"] for variant in manifest["variants"]] != ["A", "B"]:
        raise ValueError("exact A/B order required")
    requests = []
    for variant in manifest["variants"]:
        name = variant["variant"]
        runtime = root / f"runtime-{name}.json"
        request = {
            "id": name,
            "operation": "build",
            "firmware": variant["firmware"]["path"],
            "firmware_sha256": variant["firmware"]["sha256"],
            "runtime_contract": str(runtime),
            "runtime_sha256": file_hash(runtime),
        }
        _, contract = build_inputs(body, request)
        if contract["serial"]["build_id_line"] != variant["build_line"]:
            raise ValueError("BUILD identity differs from the fixture manifest")
        requests.append(request)
    return body, requests


def execute(root: Path, plan_sha256: str, confirm: str) -> int:
    body, requests = prepare(root, plan_sha256)
    if confirm != body["native_confirm_digest"]:
        raise ValueError("provide the user's once-approved native scope confirmation")
    # A client-level marker also prevents accidentally rerunning this physical test.
    with (root / "acceptance.started").open("xb") as marker:
        marker.write(b"one bounded A/B attempt; do not remove to retry\n")
    directory = root / "client"
    directory.mkdir(exist_ok=False)
    rows = []
    owner = None
    failure = None
    accepted = False
    deadline = time.monotonic() + 300

    def guard():
        if time.monotonic() >= deadline:
            raise HilError("TIMEOUT", "DK client maximum duration reached")

    try:
        # Windows PnP supplements baud's interface=null without rewriting native evidence.
        expression = (
            "Get-PnpDevice -Class Ports -PresentOnly | "
            "Where-Object {$_.FriendlyName -like '*(COM11)' -and "
            "$_.InstanceId -like 'USB\\VID_1366&PID_1061&MI_00\\*'} | "
            "Select-Object FriendlyName,InstanceId,Status | ConvertTo-Json -Compress"
        )
        pnp = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", expression],
            capture_output=True,
            timeout=15,
            creationflags=0x08000000,
        )
        (directory / "pnp-before.json").write_bytes(pnp.stdout)
        (directory / "pnp-before.stderr.log").write_bytes(pnp.stderr)
        identity = json.loads(pnp.stdout)
        if pnp.returncode != 0 or not isinstance(identity, dict) or identity.get("Status") != "OK":
            raise ValueError("COM11 MI_00 Windows identity unavailable; no target operation")
        command = [
            sys.executable,
            "-u",
            "-m",
            "hil_runner",
            "managed",
            "serve",
            str(root / "managed-plan.json"),
            "--plan-sha256",
            plan_sha256,
            "--confirm",
            confirm,
            "--allow-runtime-reset",
            "--output-dir",
            str(root / "firmware-final/run"),
        ]
        owner = Child(command, directory, "hil-owner")
        ready = owner.response(30, guard)
        rows.append(ready)
        check_message(ready, "managed.ready")
        for request in requests:
            # Only submit B after the native manager reports A's completed acceptance.
            owner.send((json.dumps(request) + "\n").encode(), 5, guard)
            message = owner.response(130, guard)
            rows.append(message)
            check_message(message, "managed.build", request["id"])
        final = owner.response(20, guard)
        rows.append(final)
        check_message(final, "managed.closed")
        if (
            final["data"].get("complete") is not True
            or final["data"].get("builds_passed") != 2
            or final["data"].get("reason") != "count_exhausted"
            or owner.wait(15, guard) != 0
        ):
            raise ValueError("managed final cleanup/count differs")
        accepted = True
    except (HilError, OSError, ValueError, KeyError, TypeError) as error:
        failure = str(error)
    finally:
        if owner is not None and owner.process.poll() is None:
            try:
                owner.process.stdin.close()  # EOF requests normal managed cleanup; never retry.
                owner.wait(15, lambda: None)
            except (HilError, OSError):
                pass
        cleanup = owner.stop(5) if owner is not None else None
    if cleanup is not None and (
        not cleanup["process_tree_stopped"]
        or not cleanup["capture_complete"]
        or cleanup["forced_termination"]
        or cleanup["exit_code"] != 0
    ):
        accepted = False
        failure = failure or "client process cleanup failed"
    report = {
        "schema_version": "embedded-hil-runner.dk-client-result.v1",
        "ok": accepted,
        "messages": rows,
        "process_cleanup": cleanup,
        "target_cleanup_verified_by_client": False,
        "error": failure,
    }
    with (root / "acceptance-result.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"ok": accepted, "report": str(root / "acceptance-result.json")}))
    return 0 if accepted else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--confirm")
    parser.add_argument(
        "--check", action="store_true", help="host-only input checks; no process starts"
    )
    arguments = parser.parse_args()
    root = arguments.root.resolve(strict=True)
    if arguments.check:
        prepare(root, arguments.plan_sha256)
        print(json.dumps({"ok": True, "hardware_access": False, "executables_started": False}))
        return 0
    if arguments.confirm is None:
        parser.error("physical acceptance needs the once-approved native --confirm value")
    return execute(root, arguments.plan_sha256, arguments.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
