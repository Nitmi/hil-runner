"""Exact inventory and native watchdog projection, without firmware-policy replay."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from hil_runner import simulation as sim
from hil_runner.common import HilError, digest

from .test_simulation import flash_inputs
from .test_simulation import inputs as inputs


@pytest.mark.parametrize("version", sim.INVENTORIES)
def test_watchdog_requires_exact_0100_inventory(inputs, version, monkeypatch):
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("offline spawned"))
    flash_inputs(inputs, version=version, gpio=True)
    spec = json.loads(inputs.read_bytes())
    path = Path(spec["cases"][0]["plan"]["path"])
    native = json.loads(path.read_bytes())
    native.update(
        schema_version="embedded-sim-runner.watchdog-plan.v1", profile=sim.WATCHDOG_PROFILE
    )
    path.write_text(json.dumps(native))
    for row in spec["cases"]:
        row["plan"]["sha256"] = digest(path.read_bytes())
    inputs.write_text(json.dumps(spec))
    if version != "0.10.0":
        with pytest.raises(HilError, match="watchdog plans require"):
            sim.compile_plan(inputs)
    else:
        result = sim.compile_plan(inputs)
        assert len(result["package_files"]) == 30
        assert not result["component_processes_started"]
        jsonschema.validate(
            result,
            json.loads(
                (Path(__file__).parents[1] / "schemas/simulation-plan.schema.json").read_bytes()
            ),
        )
        native["profile"] = sim.SPI_PROFILE
        path.write_text(json.dumps(native))
        for row in spec["cases"]:
            row["plan"]["sha256"] = digest(path.read_bytes())
        inputs.write_text(json.dumps(spec))
        with pytest.raises(HilError, match="unsupported simulation profile"):
            sim.compile_plan(inputs)


@pytest.mark.parametrize("fault", sim.WATCHDOG_FAULTS)
@pytest.mark.parametrize("unknown", [False, True])
def test_watchdog_copies_native_boots_resets_effect_and_nulls(fault, unknown):
    native = dict(
        schema_version="embedded-sim-runner.watchdog-report.v1",
        profile=sim.WATCHDOG_PROFILE,
        ok=fault == "none" and not unknown,
        fault_scenario=fault,
        **sim.WATCHDOG_LABELS,
        virtual_time=dict(domain="renode_emulation", requested_ms=82, completed=not unknown),
        errors=[],
        assertions=None
        if unknown
        else dict(
            nominal_regression_passed=fault == "none",
            boots=[dict(samples=[dict(partial_requests=2)])],
            model_observations=[],
            reset_observations=[],
            fault=dict(id=fault, effect_observed=None, status="not_evaluated"),
        ),
    )
    result = sim.watchdog_evidence(native)
    assert result["watchdog_evidence"] == native["assertions"]
    assert result["physical_reset_verified"] is False
    assert result["low_power_behavior_verified"] is False
    assert result["fault_request"] == dict(
        id=fault, requested_virtual_ms=None if fault == "none" else 22
    )
    if not unknown:
        native["assertions"]["boots"][0]["samples"][0]["partial_requests"] = 123
        assert result["watchdog_evidence"]["boots"][0]["samples"][0]["partial_requests"] == 2
    for key, value in (
        ("physical_reset_verified", True),
        ("fault_scenario", "timer-stop"),
        ("schema_version", "embedded-sim-runner.sensor-report.v1"),
        ("reset_evidence_semantics", "physical_reset"),
    ):
        changed = copy.deepcopy(native)
        changed[key] = value
        with pytest.raises(HilError):
            sim.watchdog_evidence(changed)
