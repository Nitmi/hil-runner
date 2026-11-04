"""RTC inventory gate and faithful native declarations, without policy replay."""

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
def test_rtc_requires_exact_0110_inventory(inputs, version, monkeypatch):
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("offline spawned"))
    flash_inputs(inputs, version=version, gpio=True)
    spec = json.loads(inputs.read_bytes())
    path = Path(spec["cases"][0]["plan"]["path"])
    native = json.loads(path.read_bytes())
    native.update(schema_version="embedded-sim-runner.rtc-plan.v1", profile=sim.RTC_PROFILE)
    path.write_text(json.dumps(native))
    for row in spec["cases"]:
        row["plan"]["sha256"] = digest(path.read_bytes())
    inputs.write_text(json.dumps(spec))
    if version not in ("0.11.0", "0.12.0", "0.13.0", "0.14.0", "0.15.0"):
        with pytest.raises(HilError, match="RTC plans require"):
            sim.compile_plan(inputs)
    else:
        result = sim.compile_plan(inputs)
        assert len(result["package_files"]) == len(sim.INVENTORIES[version])
        assert not result["component_processes_started"]
        jsonschema.validate(
            result,
            json.loads(
                (Path(__file__).parents[1] / "schemas/simulation-plan.schema.json").read_bytes()
            ),
        )


@pytest.mark.parametrize("fault", sim.RTC_FAULTS)
@pytest.mark.parametrize("unknown", [False, True])
def test_rtc_preserves_native_effect_samples_unknowns_and_errors(fault, unknown):
    native = dict(
        schema_version="embedded-sim-runner.rtc-report.v1",
        profile=sim.RTC_PROFILE,
        ok=fault == "none" and not unknown,
        fault_scenario=fault,
        **sim.RTC_LABELS,
        virtual_time=dict(domain="renode_emulation", requested_ms=162, completed=not unknown),
        errors=[dict(code="TIMEOUT", message="recorded failure")] if unknown else [],
        assertions=None
        if unknown
        else dict(
            nominal_regression_passed=fault == "none",
            samples=[dict(counter=16)],
            model_observations=[],
            fault=dict(id=fault, effect_observed=None, status="not_evaluated"),
        ),
    )
    result = sim.rtc_evidence(native)
    assert result["rtc_evidence"] == native["assertions"]
    assert result["native_errors"] == native["errors"]
    assert result["fault_request"] == dict(
        id=fault, requested_virtual_ms=None if fault == "none" else 42
    )
    assert result["physical_timing_verified"] is result["low_power_behavior_verified"] is False
    if not unknown:
        native["assertions"]["samples"][0]["counter"] = 99
        assert result["rtc_evidence"]["samples"][0]["counter"] == 16
    for key, value in (
        ("physical_timing_verified", True),
        ("fault_scenario", "timer-stop"),
        ("schema_version", "embedded-sim-runner.watchdog-report.v1"),
        ("observation_semantics", "physical_clock"),
    ):
        changed = copy.deepcopy(native)
        changed[key] = value
        with pytest.raises(HilError):
            sim.rtc_evidence(changed)
