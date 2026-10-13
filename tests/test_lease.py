from __future__ import annotations

import os
import time
from unittest import mock

import pytest

from hil_runner.common import HilError, digest
from hil_runner.lease import Lease, bounds
from hil_runner.selection import selection_plan


def test_real_process_conflict_close_and_reacquire(saved, live):
    path = saved()
    first = live(path)
    opened = first.line()
    assert opened["operation"] == "lease.open" and opened["ok"]
    second = live(path)
    conflict = second.line()
    assert not conflict["ok"] and conflict["errors"][0]["code"] == "RESOURCE_BUSY"
    assert conflict["data"]["failure"]["resource"] == "usb:FFFF:0001:CI-A"
    second.wait(3)
    first.close(opened["data"]["lease_id"])
    third = live(path)
    reopened = third.line()
    assert reopened["ok"] and reopened["data"]["lease_id"] != opened["data"]["lease_id"]
    third.close(reopened["data"]["lease_id"])


def test_different_boards_do_not_conflict(saved, live):
    first = live(saved(serial="ONE"))
    one = first.line()
    second = live(saved(name="two.json", serial="TWO"))
    two = second.line()
    assert one["ok"] and two["ok"]
    first.close(one["data"]["lease_id"])
    second.close(two["data"]["lease_id"])


def test_debug_vs_serial_conflict_and_partial_rollback(saved, live):
    owner = live(saved())
    opened = owner.line()
    serial_path = saved(name="serial.json", transports=("serial",))
    failed = live(serial_path)
    assert failed.line()["errors"][0]["code"] == "RESOURCE_BUSY"
    failed.wait(3)
    # The serial-port lock preceding the busy USB key was released on rollback.
    import json

    value = json.loads(serial_path.read_bytes())
    for key in ("selector_identity", "observed_identity"):
        value["bindings"][0][key] = {"port": "COM999"}
    port_only = live(saved(value, name="port-only.json"))
    port = port_only.line()
    assert port["ok"]
    port_only.close(port["data"]["lease_id"])
    owner.close(opened["data"]["lease_id"])


def test_six_simultaneous_owners_have_one_winner(saved, live):
    path = saved()
    contenders = [live(path) for _ in range(6)]
    responses = [child.line() for child in contenders]
    assert sum(value["ok"] for value in responses) == 1
    for child, value in zip(contenders, responses, strict=True):
        if value["ok"]:
            child.close(value["data"]["lease_id"])
        else:
            assert value["errors"][0]["code"] == "RESOURCE_BUSY"
            child.wait(3)


def test_same_ble_address_conflicts(saved, live):
    path = saved(transports=("ble",))
    first = live(path)
    one = first.line()
    second = live(path)
    assert second.line()["errors"][0]["code"] == "RESOURCE_BUSY"
    second.wait(3)
    first.close(one["data"]["lease_id"])


def test_eof_releases_without_reader_shutdown_error(saved, live):
    path = saved()
    owner = live(path)
    owner.line()
    owner.process.stdin.close()
    terminal = owner.line()
    assert terminal["data"]["reason"] == "stdin_eof"
    assert terminal["data"]["host_handles_closed"]
    owner.wait()
    again = live(path)
    again.close(again.line()["data"]["lease_id"])


def test_idle_expiry_with_stdin_open_releases(saved, live):
    path = saved()
    owner = live(path, duration=5, idle=1)
    owner.line()
    terminal = owner.line()
    assert terminal["data"]["reason"] == "idle_expired"
    owner.wait()
    again = live(path)
    again.close(again.line()["data"]["lease_id"])


def test_status_renews_idle_but_not_duration(saved, live):
    owner = live(saved(), duration=2, idle=1)
    opened = owner.line()
    lease_id = opened["data"]["lease_id"]
    for _ in range(5):
        time.sleep(0.3)
        owner.send({"id": "keepalive", "operation": "lease.status", "lease_id": lease_id})
        value = owner.line()
        assert value["ok"] and value["request_id"] == "keepalive"
    terminal = owner.line()
    assert terminal and terminal["data"]["reason"] == "duration_expired"
    owner.wait()


def test_forced_termination_releases_kernel_locks(saved, live):
    path = saved()
    owner = live(path)
    owner.line()
    owner.process.kill()
    owner.process.wait(timeout=5)
    fresh = live(path)
    opened = fresh.line()
    assert opened["ok"]
    fresh.close(opened["data"]["lease_id"])


def test_stale_malformed_and_command_injection_do_not_renew(saved, live):
    owner = live(saved(), duration=5, idle=1)
    lease_id = owner.line()["data"]["lease_id"]
    owner.send({"id": "bad", "operation": "lease.status", "lease_id": "lease_stale"})
    assert owner.line()["errors"][0]["code"] == "PROTOCOL_ERROR"
    owner.send({"id": "bad", "operation": "flash", "lease_id": lease_id, "command": "erase"})
    assert not owner.line()["ok"]
    terminal = owner.line()
    assert terminal["data"]["reason"] == "idle_expired"
    owner.wait()


def test_oversized_request_releases_and_exits_nonzero(saved, live):
    owner = live(saved())
    owner.line()
    owner.process.stdin.write(b"x" * 4097)
    owner.process.stdin.flush()
    terminal = owner.line()
    assert not terminal["ok"] and terminal["data"]["reason"] == "oversized"
    owner.wait(2)


def test_request_limit_is_actual_requests_not_poll_ticks(saved, live):
    owner = live(saved())
    owner.line()
    owner.process.stdin.write(b"{}\n" * 256)
    owner.process.stdin.flush()
    for _ in range(256):
        assert owner.line()["operation"] == "lease.error"
    assert owner.line()["data"]["reason"] == "request_limit"
    owner.wait(2)


def test_drift_rejected_without_creating_namespace(saved, live, tmp_path):
    owner = live(saved(), expected="0" * 64)
    assert owner.line()["errors"][0]["code"] == "INVALID_INPUT"
    owner.wait(2)
    assert not (tmp_path / "shared-leases").exists()


@pytest.mark.parametrize("duration,idle", [(0, 1), (3601, 1), (True, 1), (2, 0), (2, 3), (2, True)])
def test_bounds_reject_invalid_values(duration, idle):
    with pytest.raises(HilError):
        bounds(duration, idle)


def test_library_keeps_lock_files_and_noninheritable_handles(saved, tmp_path):
    plan = selection_plan(saved(), tmp_path / "leases")
    lease = Lease(plan, duration=5, idle=5)
    lease.acquire()
    files = [path for _, path, _ in lease.handles]
    assert all(not os.get_inheritable(fd) for _, _, fd in lease.handles)
    result = lease.release("test")
    assert result["host_handles_closed"] and not result["native_operations_stopped"]
    assert all(path.exists() for path in files)
    again = Lease(plan, duration=5, idle=5)
    again.acquire()
    again.release("test")


def test_cleanup_error_not_claimed_success(saved, tmp_path):
    lease = Lease(selection_plan(saved(), tmp_path / "leases"), duration=5, idle=5)
    lease.acquire()
    with (
        mock.patch("hil_runner.lease.unlock", side_effect=OSError("synthetic")),
        pytest.raises(HilError) as failure,
    ):
        lease.release("test")
    assert not failure.value.data["host_handles_closed"]
    again = Lease(lease.plan, duration=5, idle=5)
    again.acquire()
    again.release("test")


@pytest.mark.parametrize("kind", ["directory", "hardlink"])
def test_hardlink_or_directory_lockfile_rejected_without_delete(saved, tmp_path, kind):
    plan = selection_plan(saved(), tmp_path / "leases")
    root = tmp_path / "leases"
    root.mkdir()
    path = root / (digest(plan["resources"][0].encode()) + ".lock")
    if kind == "directory":
        path.mkdir()
    else:
        original = tmp_path / "original"
        original.write_bytes(b"untouched")
        os.link(original, path)
    lease = Lease(plan, duration=5, idle=5)
    with pytest.raises(HilError, match="regular"):
        lease.acquire()
    if kind == "directory":
        assert path.is_dir()
    else:
        assert path.read_bytes() == b"untouched" and path.stat().st_nlink == 2


def test_namespace_identity_change_stops_active_lease(saved, tmp_path):
    lease = Lease(selection_plan(saved(), tmp_path / "leases"), duration=5, idle=5)
    lease.acquire()
    lease.root_identity = (0, -1)
    try:
        with pytest.raises(HilError, match="identity changed"):
            lease.status()
    finally:
        lease.release("test")


def test_broken_stdout_releases_host_lease(saved, tmp_path):
    from hil_runner.server import serve

    lease = Lease(selection_plan(saved(), tmp_path / "leases"), duration=5, idle=5)
    with (
        mock.patch(
            "hil_runner.server.os.dup", side_effect=AssertionError("no stdin on broken stdout")
        ),
        mock.patch("hil_runner.server.emit_json", side_effect=BrokenPipeError("closed")) as emit,
    ):
        assert serve(lease, 0, emit) == 4
    assert not lease.handles
    fresh = Lease(lease.plan, duration=5, idle=5)
    fresh.acquire()
    fresh.release("test")
