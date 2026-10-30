"""Fixed SPI inventory selection and lossless native evidence projection."""

import copy
import json
from pathlib import Path

import pytest

from hil_runner import simulation as sim
from hil_runner.common import HilError, digest

from .test_simulation import flash_inputs
from .test_simulation import inputs as inputs


@pytest.mark.parametrize("version", sim.INVENTORIES)
def test_spi_requires_090_exact_inventory_and_matching_profile(inputs, version, monkeypatch):
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("offline spawned"))
    flash_inputs(inputs, version=version, gpio=True)
    spec = json.loads(inputs.read_bytes())
    path = Path(spec["cases"][0]["plan"]["path"])
    native = json.loads(path.read_bytes())
    native.update(schema_version="embedded-sim-runner.spi-sensor-plan.v1", profile=sim.SPI_PROFILE)
    path.write_text(json.dumps(native))
    for row in spec["cases"]:
        row["plan"]["sha256"] = digest(path.read_bytes())
    inputs.write_text(json.dumps(spec))
    if version not in ("0.9.0", "0.10.0"):
        with pytest.raises(HilError, match="SPI sensor plans require"):
            sim.compile_plan(inputs)
    else:
        result = sim.compile_plan(inputs)
        assert len(result["package_files"]) == (28 if version == "0.9.0" else 30)
        assert not result["component_processes_started"]
        assert result["cases"][0]["profile"] == sim.SPI_PROFILE
        native["profile"] = sim.SENSOR_PROFILE
        path.write_text(json.dumps(native))
        for row in spec["cases"]:
            row["plan"]["sha256"] = digest(path.read_bytes())
        inputs.write_text(json.dumps(spec))
        with pytest.raises(HilError, match="unsupported simulation profile"):
            sim.compile_plan(inputs)


@pytest.mark.parametrize("fault", sim.SPI_FAULTS)
@pytest.mark.parametrize("unknown", [False, True])
def test_spi_preserves_signed_q4_slip_and_unknown_without_native_policy_replay(fault, unknown):
    native = dict(
        schema_version="embedded-sim-runner.spi-sensor-report.v1",
        profile=sim.SPI_PROFILE,
        ok=fault == "none" and not unknown,
        fault_scenario=fault,
        **sim.SPI_LABELS,
        virtual_time=dict(domain="renode_emulation", requested_ms=82, completed=not unknown),
        errors=[],
        assertions=None
        if unknown
        else dict(
            nominal_regression_passed=fault == "none",
            samples=[dict(temperature_q4=-162, raw_word=64247)],
            model_observations=[],
            frame_slip_observation=None,
            fault=dict(id=fault, effect_observed=None, status="unknown"),
        ),
    )
    result = sim.sensor_evidence(native)
    assert result["sensor_evidence"] == native["assertions"]
    assert result["spi_electrical_behavior_verified"] is False
    assert "i2c_electrical_behavior_verified" not in result
    assert result["fault_request"] == dict(
        id=fault, requested_virtual_ms=None if fault == "none" else 22
    )
    if not unknown:
        native["assertions"]["samples"][0]["temperature_q4"] = 123
        assert result["sensor_evidence"]["samples"][0]["temperature_q4"] == -162
    for key, value in (
        ("spi_electrical_behavior_verified", True),
        ("fault_scenario", "temperature-offset"),
        ("schema_version", "embedded-sim-runner.sensor-report.v1"),
        ("frame_slip_semantics", "physical_bit_error"),
    ):
        changed = copy.deepcopy(native)
        changed[key] = value
        with pytest.raises(HilError):
            sim.sensor_evidence(changed)
