"""Typed suite tests with explicitly synthetic wheels and native protocol doubles."""

import io
import json
import sys
import zipfile
from pathlib import Path

import jsonschema
import pytest

from hil_runner import simulation as sim
from hil_runner.common import HilError, digest


@pytest.fixture
def inputs(tmp_path):
    # Offline planning and FakeChild tests never execute this synthetic file.
    interpreter = tmp_path / "synthetic-python"
    interpreter.write_bytes(b"synthetic interpreter, never executed")
    wheel = tmp_path / "sim.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in sim.MODULES:
            archive.writestr("sim_runner/" + name, b"synthetic, never executed")
        archive.writestr(
            "embedded_sim_runner-0.2.0.dist-info/METADATA",
            "Name: embedded-sim-runner\nVersion: 0.2.0\n",
        )
    plan = tmp_path / "native.json"
    plan.write_text(
        json.dumps(
            {
                "schema_version": "embedded-sim-runner.qemu-plan.v1",
                "profile": "esp32c3-ram-uart-v1",
                "backend": "espressif-qemu",
                "execution_kind": "simulation",
                "hardware_access": False,
                "physical_board_verified": False,
                "physical_firmware_identity_verified": False,
            }
        )
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": sim.PREFIX + "spec.v1",
                "python": {
                    "path": str(interpreter),
                    "sha256": digest(interpreter.read_bytes()),
                },
                "sim_runner_wheel": {"path": str(wheel), "sha256": digest(wheel.read_bytes())},
                "cases": [
                    {"id": name, "plan": {"path": str(plan), "sha256": digest(plan.read_bytes())}}
                    for name in ("a", "b", "c")
                ],
                "timeout_seconds": 10,
            }
        )
    )
    return spec


def test_interpreter_link_is_rejected(inputs, tmp_path):
    spec = json.loads(inputs.read_bytes())
    linked = tmp_path / "linked-python"
    try:
        linked.symlink_to(spec["python"]["path"])
    except OSError:
        pytest.skip("Symlink creation unavailable")
    spec["python"]["path"] = str(linked)
    inputs.write_text(json.dumps(spec))
    with pytest.raises(HilError, match="links/reparse points"):
        sim.compile_plan(inputs)


def test_plan_is_offline_and_binds_all_package_files(inputs, monkeypatch, tmp_path):
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: pytest.fail("offline plan spawned"))
    plan = sim.compile_plan(inputs)
    schemas = Path(__file__).parents[1] / "schemas"
    jsonschema.validate(
        json.loads(inputs.read_bytes()),
        json.loads((schemas / "simulation-spec.schema.json").read_bytes()),
    )
    jsonschema.validate(plan, json.loads((schemas / "simulation-plan.schema.json").read_bytes()))
    assert len(plan["package_files"]) == 13 and plan["native_validation_performed"] is False
    path = tmp_path / "plan.json"
    ref = sim.json_new(path, plan)
    assert sim.load_plan(path, ref["sha256"])[1] == plan
    (tmp_path / "native.json").write_bytes(b"changed")
    with pytest.raises(HilError, match="changed"):
        sim.load_plan(path, ref["sha256"])


@pytest.mark.parametrize(
    "mutation", ["command", "case-path", "duplicate", "reserved", "timeout", "hardware"]
)
def test_unsafe_or_unknown_suite_settings_are_rejected(inputs, tmp_path, mutation):
    doc = json.loads(inputs.read_bytes())
    if mutation == "command":
        doc["command"] = ["powershell"]
    if mutation == "case-path":
        doc["cases"][0]["id"] = "../escape"
    if mutation == "duplicate":
        doc["cases"][1]["id"] = "a"
    if mutation == "reserved":
        doc["cases"][0]["id"] = "CON"
    if mutation == "timeout":
        doc["timeout_seconds"] = True
    if mutation == "hardware":
        native = tmp_path / "native.json"
        data = json.loads(native.read_bytes())
        data["hardware_access"] = True
        native.write_text(json.dumps(data))
        for row in doc["cases"]:
            row["plan"]["sha256"] = digest(native.read_bytes())
    inputs.write_text(json.dumps(doc))
    with pytest.raises(HilError):
        sim.compile_plan(inputs)


def test_arbitrary_wheel_modules_and_invalid_zip_rejected():
    for name in ("../escape.py", "sim_runner/evil.py", "sitecustomize.py"):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr(name, b"bad")
        with pytest.raises(HilError):
            sim.package(payload.getvalue())
    with pytest.raises(HilError):
        sim.package(b"not a zip")


@pytest.mark.parametrize("name", ["../x", "component/../x", "component/evil.js", ".", "..", "/x"])
def test_native_nested_inventory_is_fixed(name):
    assert not sim.native_artifact_name(name)
    assert sim.native_artifact_name("component/esp_emu_bg.wasm")


def flash_inputs(inputs, *, version="0.3.0", gpio=False, s3=False):
    spec = json.loads(inputs.read_bytes())
    wheel = Path(spec["sim_runner_wheel"]["path"])
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in sim.INVENTORIES[version]:
            archive.writestr("sim_runner/" + name, b"synthetic, never executed")
        archive.writestr(
            f"embedded_sim_runner-{version}.dist-info/METADATA",
            f"Name: embedded-sim-runner\nVersion: {version}\n",
        )
    native = Path(spec["cases"][0]["plan"]["path"])
    plan = json.loads(native.read_bytes())
    plan.update(
        schema_version="embedded-sim-runner.gpio-timer-plan.v1"
        if gpio
        else "embedded-sim-runner.qemu-s3-flash-plan.v1"
        if s3
        else "embedded-sim-runner.qemu-flash-plan.v1",
        profile=sim.GPIO_PROFILE if gpio else sim.S3_PROFILE if s3 else "esp32c3-idf-flash-v1",
        backend="renode" if gpio else "espressif-qemu-xtensa" if s3 else "espressif-qemu",
    )
    native.write_text(json.dumps(plan))
    spec["sim_runner_wheel"]["sha256"] = digest(wheel.read_bytes())
    for case in spec["cases"]:
        case["plan"]["sha256"] = digest(native.read_bytes())
    inputs.write_text(json.dumps(spec))


@pytest.mark.parametrize("version", ["0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.7.0"])
def test_wasm_plan_requires_070_and_its_own_backend(inputs, version):
    flash_inputs(inputs, version=version)
    spec = json.loads(inputs.read_bytes())
    native = Path(spec["cases"][0]["plan"]["path"])
    doc = json.loads(native.read_bytes()) | {
        "schema_version": "embedded-sim-runner.esp-wasm-plan.v1",
        "profile": sim.WASM_PROFILE,
        "backend": "espressif-esp-emulator-wasm",
    }
    native.write_text(json.dumps(doc))
    for row in spec["cases"]:
        row["plan"]["sha256"] = digest(native.read_bytes())
    inputs.write_text(json.dumps(spec))
    if version == "0.7.0":
        plan = sim.compile_plan(inputs)
        assert len(plan["package_files"]) == 24
        jsonschema.validate(
            plan,
            json.loads(
                (Path(__file__).parents[1] / "schemas/simulation-plan.schema.json").read_bytes()
            ),
        )
    else:
        with pytest.raises(HilError, match="WASM plans require"):
            sim.compile_plan(inputs)


@pytest.mark.parametrize("version", ["0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "0.7.0"])
def test_flash_profile_requires_versioned_module_inventory(inputs, version):
    flash_inputs(inputs, version=version)
    if version == "0.2.0":
        with pytest.raises(HilError, match="require sim-runner 0.3.0"):
            sim.compile_plan(inputs)
    else:
        assert len(sim.compile_plan(inputs)["package_files"]) == len(sim.INVENTORIES[version])


@pytest.mark.parametrize("version", ["0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0"])
def test_gpio_plan_requires_040_inventory(inputs, version):
    flash_inputs(inputs, version=version, gpio=True)
    if version in ("0.4.0", "0.5.0", "0.6.0"):
        assert len(sim.compile_plan(inputs)["package_files"]) == len(sim.INVENTORIES[version])
    else:
        with pytest.raises(HilError, match="GPIO plans require"):
            sim.compile_plan(inputs)


@pytest.mark.parametrize("version", ["0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0"])
def test_s3_requires_050_inventory_and_its_own_backend(inputs, version):
    flash_inputs(inputs, version=version, s3=True)
    if version not in ("0.5.0", "0.6.0"):
        with pytest.raises(HilError, match="S3 plans require"):
            sim.compile_plan(inputs)
    else:
        assert len(sim.compile_plan(inputs)["package_files"]) == len(sim.INVENTORIES[version])
        spec = json.loads(inputs.read_bytes())
        native = Path(spec["cases"][0]["plan"]["path"])
        doc = json.loads(native.read_bytes()) | {"backend": "espressif-qemu"}
        native.write_text(json.dumps(doc))
        for row in spec["cases"]:
            row["plan"]["sha256"] = digest(native.read_bytes())
        inputs.write_text(json.dumps(spec))
        with pytest.raises(HilError, match="unsupported simulation profile"):
            sim.compile_plan(inputs)


@pytest.mark.parametrize("version", ["0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0"])
def test_fault_profile_requires_060_inventory(inputs, version):
    flash_inputs(inputs, version=version, gpio=True)
    spec = json.loads(inputs.read_bytes())
    native = Path(spec["cases"][0]["plan"]["path"])
    doc = json.loads(native.read_bytes())
    doc.update(schema_version="embedded-sim-runner.gpio-fault-plan.v1", profile=sim.FAULT_PROFILE)
    native.write_text(json.dumps(doc))
    for row in spec["cases"]:
        row["plan"]["sha256"] = digest(native.read_bytes())
    inputs.write_text(json.dumps(spec))
    if version == "0.6.0":
        plan = sim.compile_plan(inputs)
        assert len(plan["package_files"]) == 21
    else:
        with pytest.raises(HilError, match="fault plans require"):
            sim.compile_plan(inputs)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process supervision")
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "native-failed",
        "preflight",
        "timeout",
        "startup",
        "limited",
        "limited-failed",
        "gpio",
        "gpio-failed",
        "fault-failed",
        "fault-unknown",
        "s3",
        "s3-failed",
        "wasm",
        "wasm-failed",
        "wasm-unknown",
    ],
)
def test_suite_stops_and_preserves_native_failure_and_cleanup(
    inputs, tmp_path, monkeypatch, failure
):
    attempts = []
    wasm = failure in ("wasm", "wasm-failed", "wasm-unknown")
    if wasm:
        flash_inputs(inputs, version="0.7.0")
        spec = json.loads(inputs.read_bytes())
        native = Path(spec["cases"][0]["plan"]["path"])
        value = json.loads(native.read_bytes()) | {
            "schema_version": "embedded-sim-runner.esp-wasm-plan.v1",
            "profile": sim.WASM_PROFILE,
            "backend": "espressif-esp-emulator-wasm",
        }
        native.write_text(json.dumps(value))
        for row in spec["cases"]:
            row["plan"]["sha256"] = digest(native.read_bytes())
        inputs.write_text(json.dumps(spec))
    s3 = failure in ("s3", "s3-failed")
    limited = failure in ("limited", "limited-failed") or s3
    if limited:
        flash_inputs(inputs, version="0.5.0" if s3 else "0.3.0", s3=s3)
    fault = failure in ("fault-failed", "fault-unknown")
    gpio = failure in ("gpio", "gpio-failed") or fault
    if gpio:
        flash_inputs(inputs, version="0.6.0" if fault else "0.4.0", gpio=True)
        if fault:
            spec = json.loads(inputs.read_bytes())
            native = Path(spec["cases"][0]["plan"]["path"])
            value = json.loads(native.read_bytes())
            value.update(
                schema_version="embedded-sim-runner.gpio-fault-plan.v1", profile=sim.FAULT_PROFILE
            )
            native.write_text(json.dumps(value))
            for row in spec["cases"]:
                row["plan"]["sha256"] = digest(native.read_bytes())
            inputs.write_text(json.dumps(spec))

    class FakeChild:
        def __init__(self, command, directory, name, *, jsonl):
            assert command[1:6] == ["-I", "-S", "-B", "-c", sim.BOOTSTRAP]
            assert jsonl is False
            self.args, self.directory, self.name = command[7:], directory, name
            self.timed_out = False
            if failure == "startup":
                raise OSError("synthetic startup error")

        def control(self, timeout, guard):
            operation = self.args[0]
            value = {
                "execution_kind": "simulation",
                "hardware_access": False,
                "physical_board_verified": False,
                "ok": True,
                "executables_started": False,
                "profile": sim.WASM_PROFILE
                if wasm
                else sim.FAULT_PROFILE
                if fault
                else sim.GPIO_PROFILE
                if gpio
                else sim.S3_PROFILE
                if s3
                else "esp32c3-idf-flash-v1"
                if limited
                else "esp32c3-ram-uart-v1",
            }
            code = 0
            if failure == "preflight" and operation == "inspect-plan":
                value["ok"], code = False, 1
            if operation == "run":
                folder = Path(self.args[self.args.index("--output-dir") + 1])
                folder.mkdir()
                attempts.append(folder.name)
                if failure == "timeout":
                    self.timed_out = True
                    raise HilError("TIMEOUT", "synthetic native timeout")
                failed = (
                    failure
                    in (
                        "native-failed",
                        "limited-failed",
                        "gpio-failed",
                        "s3-failed",
                        "fault-failed",
                        "fault-unknown",
                        "wasm-failed",
                        "wasm-unknown",
                    )
                    and folder.name == "b"
                )
                value.update(
                    ok=not failed,
                    status="failed" if failed else "passed",
                    artifacts={},
                    errors=[{"code": "ASSERTION_FAILED"}] if failed else [],
                )
                if limited:
                    value.update(
                        status="failed" if failed else "passed_with_model_limits",
                        assertions=None
                        if failed
                        else {
                            "model_diagnostics": [
                                {
                                    "message": "synthetic model limit",
                                    "count": 1,
                                    "meaning": "synthetic",
                                }
                            ]
                        },
                        model_coverage_complete=False,
                        security_features_verified=False,
                    )
                if gpio:
                    value.update(
                        schema_version="embedded-sim-runner.gpio-timer-report.v1",
                        model_coverage_complete=False,
                        physical_timing_verified=False,
                        gpio_observation_semantics="paused_model_register_snapshot_not_electrical_waveform",
                        timer_observation_semantics="guest_reported_250kHz_capture_in_TIMER0_IRQ_not_host_time",
                        assertions=None
                        if failed
                        else {"samples": [{"sequence": 1}], "model_observations": [{"phase": 0}]},
                    )
                if s3:
                    value.update(
                        schema_version="embedded-sim-runner.qemu-s3-flash-report.v1",
                        backend="espressif-qemu-xtensa",
                        backend_version="synthetic",
                        runtime_archive_sha256="a" * 64,
                        virtual_time={
                            "domain": "qemu_device_clock_unmeasured",
                            "elapsed_ns": None,
                            "budget_enforced": False,
                        },
                    )
                    if not failed:
                        value["assertions"]["app_core_markers"] = [0, 1]
                if fault:
                    value.update(
                        schema_version="embedded-sim-runner.gpio-fault-report.v1",
                        fault_scenario="timer-stop" if failed else "none",
                        fault_scope=sim.FAULT_SCOPE,
                        virtual_time={
                            "domain": "renode_emulation",
                            "requested_ms": 82,
                            "completed": not (failed and failure == "fault-unknown"),
                        },
                    )
                    if failure == "fault-unknown" and failed:
                        value["assertions"] = None
                        value["errors"] = [{"code": "TIMEOUT"}]
                    else:
                        value["assertions"] = {
                            "samples": [],
                            "model_observations": [],
                            "nominal_regression_passed": not failed,
                            "nominal_failure": "synthetic IRQ failure" if failed else None,
                            "fault": {
                                "id": value["fault_scenario"],
                                "effect_observed": True if failed else None,
                                "status": "observed" if failed else "not_requested",
                            },
                        }
                if wasm:
                    value.update(
                        schema_version="embedded-sim-runner.esp-wasm-report.v1",
                        status="failed" if failed else "passed_with_model_limits",
                        backend="espressif-esp-emulator-wasm",
                        backend_version="0.50.0",
                        runtime_archive_sha256="a" * 64,
                        virtual_time={
                            "domain": "esp_emulator_unmeasured_device_clock",
                            "elapsed_ns": None,
                            "budget_enforced": False,
                        },
                        uart_timestamps_available=False,
                        uart_representation="ascii_subset_of_wasm_strings_encoded_utf8",
                        raw_uart_bytes_verified=False,
                        model_coverage_complete=False,
                        physical_timing_verified=False,
                        security_features_verified=False,
                        initial_state="synthetic",
                        model_limits=["synthetic string API limit"],
                        runtime_observation=None if failed else {"restart_performed": False},
                        assertions=None if failed else {"ready": True},
                    )
                    file = folder / "component" / "esp_emu_bg.wasm"
                    file.parent.mkdir()
                    file.write_bytes(b"synthetic WASM, never executed")
                    value["artifacts"] = {
                        "component/esp_emu_bg.wasm": {
                            "sha256": digest(file.read_bytes()),
                            "bytes": file.stat().st_size,
                        }
                    }
                (folder / "report.json").write_text(json.dumps(value))
                code = 1 if failed else 0
            if operation == "inspect-report":
                report = json.loads(Path(self.args[2]).read_bytes())
                value["recorded_status" if wasm else "report_status"] = report["status"]
            raw = json.dumps(value).encode()
            (self.directory / (self.name + ".stdout.bin")).write_bytes(raw)
            (self.directory / (self.name + ".stderr.log")).write_bytes(b"")
            return code, raw

        def stop(self, timeout):
            return {
                "process_tree_stopped": True,
                "capture_complete": True,
                "forced_termination": self.timed_out,
                "errors": [],
            }

    monkeypatch.setattr(sim, "Child", FakeChild)
    path = tmp_path / "plan.json"
    ref = sim.json_new(path, sim.compile_plan(inputs))
    output = tmp_path / "run"
    report = sim.run(path, ref["sha256"], output)
    jsonschema.validate(
        report,
        json.loads(
            (Path(__file__).parents[1] / "schemas/simulation-report.schema.json").read_bytes()
        ),
    )
    assert report["ok"] is (failure in (None, "limited", "gpio", "s3", "wasm"))
    if failure in (
        "native-failed",
        "limited-failed",
        "gpio-failed",
        "s3-failed",
        "fault-failed",
        "fault-unknown",
        "wasm-failed",
        "wasm-unknown",
    ):
        assert attempts == ["a", "b"] and report["cases"][-1]["status"] == "not_run"
        assert len(json.loads((output / "trace-input.json").read_bytes())["sources"]) == 2
    if failure in ("preflight", "startup"):
        assert attempts == []
    if failure == "timeout":
        assert attempts == ["a"]
    if failure == "startup":
        assert report["emulator_processes_stopped"] is False
    saved = output / "report.json"
    if wasm:
        assert "component/sim_runner/assets/esp_wasm_runner.mjs" in report["artifacts"]
        assert "runs/a/component/esp_emu_bg.wasm" in report["artifacts"]
        assert report["cases"][0]["raw_uart_bytes_verified"] is False
        changed = json.loads(json.dumps(report))
        changed["cases"][0]["raw_uart_bytes_verified"] = True
        saved.write_text(json.dumps(changed))
        with pytest.raises(HilError, match="WASM case declarations"):
            sim.inspect_report(saved, digest(saved.read_bytes()))
        saved.write_text(json.dumps(report))
    assert (
        sim.inspect_report(saved, digest(saved.read_bytes()))["report_status"] == report["status"]
    )
    if limited:
        assert report["cases"][0]["status"] == "passed_with_model_limits"
        assert report["cases"][0]["model_diagnostics"][0]["count"] == 1
        changed = json.loads(saved.read_bytes())
        changed["cases"][0]["model_diagnostics"] = []
        saved.write_text(json.dumps(changed))
        with pytest.raises(HilError, match="limitations differ"):
            sim.inspect_report(saved, digest(saved.read_bytes()))
        if failure in ("limited", "s3"):
            assert report["status"] == "passed_with_model_limits" and attempts == ["a", "b", "c"]
            changed = {**report, "status": "passed"}
            saved.write_text(json.dumps(changed))
            with pytest.raises(HilError, match="limitations were changed"):
                sim.inspect_report(saved, digest(saved.read_bytes()))
        saved.write_text(json.dumps(report))
    if s3:
        assert report["cases"][0]["app_core_markers"] == [0, 1]
        if failure == "s3-failed":
            assert report["cases"][1]["app_core_markers"] is None
        for key, value in (
            ("backend", "espressif-qemu"),
            ("runtime_archive_sha256", "b" * 64),
            ("app_core_markers", [False, 1]),
            (
                "virtual_time",
                {"domain": "qemu_icount_shift_0", "elapsed_ns": 5, "budget_enforced": True},
            ),
        ):
            changed = json.loads(json.dumps(report))
            changed["cases"][0][key] = value
            saved.write_text(json.dumps(changed))
            with pytest.raises(HilError, match="S3 case identity"):
                sim.inspect_report(saved, digest(saved.read_bytes()))
        saved.write_text(json.dumps(report))
    if fault:
        failed = report["cases"][1]
        assert failed["status"] == "failed" and report["cases"][2]["status"] == "not_run"
        assert failed["fault_scenario"] == "timer-stop"
        if failure == "fault-unknown":
            assert failed["fault_evidence"] is None and failed["virtual_time"]["completed"] is False
        else:
            assert failed["fault_evidence"]["fault"]["effect_observed"] is True
            assert failed["fault_evidence"]["nominal_regression_passed"] is False
        for key, value in (
            ("fault_evidence", {}),
            ("fault_scenario", "none"),
            ("native_errors", []),
            ("virtual_time", {}),
        ):
            changed = json.loads(json.dumps(report))
            changed["cases"][1][key] = value
            saved.write_text(json.dumps(changed))
            with pytest.raises(HilError, match="GPIO case summary"):
                sim.inspect_report(saved, digest(saved.read_bytes()))
        saved.write_text(json.dumps(report))
    if gpio and not fault:
        assert report["cases"][0]["gpio_evidence"]["model_observations"] == [{"phase": 0}]
        for key, value in (
            ("gpio_evidence", {}),
            ("physical_timing_verified", True),
            ("model_coverage_complete", 0),
            ("timer_observation_semantics", "host_time"),
        ):
            changed = json.loads(json.dumps(report))
            changed["cases"][0][key] = value
            saved.write_text(json.dumps(changed))
            with pytest.raises(HilError, match="GPIO case summary"):
                sim.inspect_report(saved, digest(saved.read_bytes()))
        saved.write_text(json.dumps(report))
    (output / "plan.json").write_bytes(b"changed")
    with pytest.raises(HilError):
        sim.inspect_report(saved, digest(saved.read_bytes()))
