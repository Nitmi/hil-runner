from __future__ import annotations

import copy
import json
import subprocess

import pytest

from hil_runner.common import HilError, decode, digest
from hil_runner.selection import selection_plan

from .conftest import VALIDATOR, cli, selection


def test_plan_is_read_only_and_unifies_usb_interfaces(saved, tmp_path):
    path = saved(transports=("debug", "serial", "ble"))
    namespace = tmp_path / "not-created"
    before = path.read_bytes()
    plan = selection_plan(path, namespace)
    assert plan["resources"] == [
        "ble:AB:CD:00:00:00:01",
        "serial-port:COM999",
        "usb:FFFF:0001:CI-A",
    ]
    assert plan["selection"]["sha256"] == digest(before)
    assert plan["effects"] == []
    assert not plan["hardware_identity_verified"] and not plan["upstream_files_revalidated"]
    assert path.read_bytes() == before and not namespace.exists()


def test_cli_plan_schema_and_error_are_structured(saved, tmp_path):
    path = saved()
    namespace = tmp_path / "absent"
    result = subprocess.run(
        cli("lease", "plan", path, "--lease-root", namespace, "--json"),
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0 and not result.stderr
    value = json.loads(result.stdout)
    VALIDATOR.validate(value)
    assert value["data"]["effects"] == [] and not namespace.exists()
    missing = subprocess.run(
        cli("lease", "plan", tmp_path / "missing", "--json"), capture_output=True, timeout=5
    )
    assert missing.returncode == 4
    VALIDATOR.validate(json.loads(missing.stdout))


def test_snapshot_hash_drift_rejected_before_lock_root(saved, tmp_path):
    path = saved()
    namespace = tmp_path / "absent"
    with pytest.raises(HilError, match="differs"):
        selection_plan(path, namespace, "0" * 64)
    assert not namespace.exists()


@pytest.mark.parametrize(
    "payload",
    [b'{"x":1,"x":2}', b'{"x":NaN}', b'"\xff"', b"[" * 2000 + b"]" * 2000],
    ids=["duplicate", "nonfinite", "encoding", "nesting"],
)
def test_invalid_json_is_bounded_and_rejected(payload):
    with pytest.raises(HilError):
        decode(payload)


def test_json_depth_counts_only_containers_outside_strings():
    value = {"quoted": "[" * 100 + '\\"' + "]" * 100}
    assert decode(json.dumps(value).encode()) == value


def test_selection_size_bound(saved, tmp_path):
    path = saved()
    path.write_bytes(b" " * (256 * 1024 + 1))
    with pytest.raises(HilError, match="exceeds"):
        selection_plan(path, tmp_path / "leases")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(extra=True),
        lambda v: v.update(ok=1),
        lambda v: v.update(hardware_access=0),
        lambda v: v.update(board_id="bad name"),
        lambda v: v["authorization"].update(granted=True),
        lambda v: v["authorization"].update(allowed_operations=["flash"]),
        lambda v: v.update(required_transports=["debug", "debug"]),
        lambda v: v["bindings"][0].update(transport="serial"),
        lambda v: v["bindings"][0]["source"].update(sha256="X" * 64),
        lambda v: v["bindings"][0]["source"].update(point_in_time=1),
        lambda v: v["inputs"]["registry"].update(extra="no"),
        lambda v: v["bindings"][0]["observed_identity"].update(probe_selector="ffff:0001:other"),
        lambda v: v["bindings"][0]["observed_identity"].update(command="erase"),
    ],
)
def test_invalid_selection_is_rejected(saved, tmp_path, mutation):
    value = selection()
    mutation(value)
    with pytest.raises(HilError):
        selection_plan(saved(value), tmp_path / "leases")


@pytest.mark.parametrize(
    "transport,identity",
    [
        ("debug", {"probe_selector": "ffff:0001"}),
        ("debug", {"probe_selector": "ffff:0001:"}),
        ("debug", {"probe_selector": "xxxx:0001:SERIAL"}),
        ("debug", {"probe_selector": "ffff:0001:A", "serial_number": "B"}),
        ("serial", {"port": "COM3", "usb_vid": "FFFF"}),
        ("serial", {"port": "COM0"}),
        ("serial", {"usb_vid": "FFFF", "usb_pid": "0001", "usb_serial": "A"}),
        ("ble", {"local_name": "friendly-name"}),
        ("ble", {"identifier": "id:any"}),
    ],
)
def test_ambiguous_transport_keys_are_rejected(saved, tmp_path, transport, identity):
    value = selection(transports=(transport,))
    for key in ("selector_identity", "observed_identity"):
        value["bindings"][0][key] = copy.deepcopy(identity)
    with pytest.raises(HilError):
        selection_plan(saved(value), tmp_path / "leases")


def test_case_normalization_and_uuid(saved, tmp_path):
    value = selection(transports=("ble", "debug", "serial"), serial="case", port="com99")
    for key in ("selector_identity", "observed_identity"):
        value["bindings"][0][key]["identifier"] = "12345678-abcd-0123-4567-890123456789"
    plan = selection_plan(saved(value), tmp_path / "leases")
    assert plan["resources"] == [
        "ble:12345678-ABCD-0123-4567-890123456789",
        "serial-port:COM99",
        "usb:FFFF:0001:CASE",
    ]


def test_alias_selection_path_binds_canonical_file(saved, tmp_path):
    path = saved()
    plan = selection_plan(path.parent / ".." / path.parent.name / path.name, tmp_path / "leases")
    assert plan["selection"]["path"] == str(path.resolve())
