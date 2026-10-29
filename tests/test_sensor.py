"""Sensor wheel selection and copied native declarations; native policy stays native."""

import copy

import pytest

from hil_runner import simulation as sim
from hil_runner.common import HilError


@pytest.mark.parametrize("fault", sim.SENSOR_FAULTS)
@pytest.mark.parametrize("unknown", [False, True])
def test_native_nominal_verdict_and_effect_are_copied_without_inference(fault, unknown):
    assertions = dict(
        nominal_regression_passed=fault == "none",
        samples=[],
        model_observations=[],
        fault=dict(id=fault, effect_observed=None if fault == "none" else False),
    )
    native = dict(
        schema_version="embedded-sim-runner.sensor-report.v1",
        profile=sim.SENSOR_PROFILE,
        ok=fault == "none" and not unknown,
        fault_scenario=fault,
        **sim.SENSOR_LABELS,
        virtual_time=dict(domain="renode_emulation", requested_ms=82, completed=not unknown),
        errors=[],
        assertions=None if unknown else assertions,
    )
    result = sim.sensor_evidence(native)
    assert result["sensor_evidence"] == native["assertions"]
    assert result["sensor_accuracy_verified"] is result["i2c_electrical_behavior_verified"] is False
    if not unknown:
        assertions["samples"].append({})
        assert result["sensor_evidence"]["samples"] == []
    for mutation in ("coverage", "clock", "effect", "fault"):
        changed = copy.deepcopy(native)
        if mutation == "coverage":
            changed["sensor_accuracy_verified"] = True
        if mutation == "clock":
            changed["virtual_time"]["completed"] = 1
        if mutation == "effect":
            if unknown:
                continue
            changed["assertions"]["fault"]["effect_observed"] = 1
        if mutation == "fault":
            changed["fault_scenario"] = "arbitrary"
        with pytest.raises(HilError):
            sim.sensor_evidence(changed)
