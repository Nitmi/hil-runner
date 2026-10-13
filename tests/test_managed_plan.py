from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

from hil_runner.common import HilError, digest
from hil_runner.managed import artifact, execute, native_message
from hil_runner.managed_plan import build_inputs, compile_plan, read_plan

from .managed_fixtures import prepare, write


def compiled(tmp_path):
    spec, request = prepare(tmp_path)
    output = tmp_path / "managed-plan.json"
    data = compile_plan(spec, output, tmp_path / "leases")
    return data, request, output


def test_plan_and_revalidation_start_no_processes_or_locks(tmp_path):
    with mock.patch("subprocess.Popen", side_effect=AssertionError("must not start")):
        data, request, path = compiled(tmp_path)
        body = read_plan(path, data["sha256"])
        inputs, contract = build_inputs(body, request)
    assert not (tmp_path / "leases").exists()
    assert not body["authorization_granted"]
    assert contract["serial"]["transmit_bytes"] == 0
    assert inputs["firmware"]["sha256"] == request["firmware_sha256"]
    root = Path(__file__).parents[1] / "schemas"
    for name, value in (
        ("managed-spec", json.loads((tmp_path / "spec.json").read_bytes())),
        ("managed-plan", body),
    ):
        schema = json.loads((root / (name + ".schema.json")).read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(value, schema)


def test_modified_plan_cannot_expand_scope_even_with_updated_hash(tmp_path):
    data, _, path = compiled(tmp_path)
    data["body"]["limits"]["duration_seconds"] = 3600
    write(path, data["body"])
    with pytest.raises(HilError, match="differs"):
        read_plan(path, digest(path.read_bytes()))


def test_bound_component_drift_stops_before_execution(tmp_path):
    data, _, path = compiled(tmp_path)
    (tmp_path / "baud.exe").write_bytes(b"changed")
    with pytest.raises(HilError, match="changed"):
        read_plan(path, data["sha256"])


def test_older_native_monitor_is_rejected_before_any_process(tmp_path):
    spec, _ = prepare(tmp_path)
    lock_path = tmp_path / "lock.json"
    value = json.loads(lock_path.read_bytes())
    value["components"]["embedded-debugger"]["version"] = "0.2.4"
    write(lock_path, value)
    with (
        mock.patch("subprocess.Popen", side_effect=AssertionError("must not start")),
        pytest.raises(HilError, match="0.2.5"),
    ):
        compile_plan(spec, tmp_path / "plan.json", tmp_path / "leases")
    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(command="erase"),
        lambda v: v.update(native_confirm_digest="G" * 64),
        lambda v: v.update(replay_fixture=None),
        lambda v: v["limits"].update(native_timeout_seconds=0),
        lambda v: v["limits"].update(duration_seconds=301),
        lambda v: v["limits"].update(shutdown_timeout_seconds=True),
    ],
)
def test_invalid_spec_rejected_before_output(tmp_path, mutation):
    spec, _ = prepare(tmp_path)
    value = json.loads(spec.read_bytes())
    mutation(value)
    write(spec, value)
    with pytest.raises(HilError):
        compile_plan(spec, tmp_path / "plan.json", tmp_path / "leases")
    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("transmit_bytes", 1),
        ("transmit_bytes", False),
        ("port", "COM3"),
        ("usb_serial_number", "OTHER"),
        ("minimum_complete_heartbeats", True),
        ("observe_duration_seconds", 61),
        ("dtr", "false"),
        ("ready_line", "ready\ninjected"),
    ],
)
def test_runtime_policy_is_bound_and_zero_transmit(tmp_path, field, value):
    spec, _ = prepare(tmp_path)
    path = tmp_path / "runtime-template.json"
    template = json.loads(path.read_bytes())
    template["serial"][field] = value
    write(path, template)
    with pytest.raises(HilError):
        compile_plan(spec, tmp_path / "plan.json", tmp_path / "leases")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(firmware_sha256="0" * 64),
        lambda v: v.update(runtime_sha256="0" * 64),
        lambda v: v.update(operation="erase"),
        lambda v: v.update(command="anything"),
    ],
)
def test_build_requests_fail_before_native_operations(tmp_path, mutation):
    data, request, _ = compiled(tmp_path)
    mutation(request)
    with pytest.raises(HilError):
        build_inputs(data["body"], request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dtr", True),
        ("ready_line", "OTHER"),
        ("minimum_complete_heartbeats", 1),
        ("build_id_line", None),
    ],
)
def test_per_build_runtime_policy_cannot_drift(tmp_path, field, value):
    data, request, _ = compiled(tmp_path)
    path = tmp_path / "build/runtime-a.json"
    contract = json.loads(path.read_bytes())
    contract["serial"][field] = value
    write(path, contract)
    request["runtime_sha256"] = digest(path.read_bytes())
    with pytest.raises(HilError):
        build_inputs(data["body"], request)


def test_confirmation_and_runtime_flag_are_one_time_startup_gates(tmp_path):
    data, _, path = compiled(tmp_path)
    with mock.patch("subprocess.Popen", side_effect=AssertionError("no native process")):
        with pytest.raises(HilError):
            execute(
                path, data["sha256"], "0" * 64, tmp_path / "build/run1", allow_runtime_reset=True
            )
        with pytest.raises(HilError):
            execute(
                path, data["sha256"], "a" * 64, tmp_path / "build/run2", allow_runtime_reset=False
            )
    assert not (tmp_path / "build/run1").exists() and not (tmp_path / "leases").exists()


def test_output_outside_native_directory_and_scope_reuse_rejected(tmp_path):
    data, _, path = compiled(tmp_path)
    with pytest.raises(HilError):
        execute(path, data["sha256"], "a" * 64, tmp_path / "outside", allow_runtime_reset=True)
    (tmp_path / "native-scope.json.active").write_bytes(b"")
    with pytest.raises(HilError):
        execute(path, data["sha256"], "a" * 64, tmp_path / "build/run", allow_runtime_reset=True)
    assert (tmp_path / "native-scope.json.active").exists()


def test_native_envelope_and_artifact_hash_must_match(tmp_path):
    path = write(tmp_path / "native.json", {"complete": True})
    ref = {"path": str(path), "sha256": digest(path.read_bytes()), "size": path.stat().st_size}
    assert artifact(ref, path)[1]["complete"]
    ref["sha256"] = "0" * 64
    with pytest.raises(HilError):
        artifact(ref, path)
    with pytest.raises(HilError):
        native_message(
            {"schema_version": "1.0", "ok": 1, "operation": "flash.session.flash", "data": {}},
            "flash.session.flash",
        )
