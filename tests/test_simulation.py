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
                    "path": sys.executable,
                    "sha256": digest(Path(sys.executable).read_bytes()),
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process supervision")
@pytest.mark.parametrize("failure", [None, "native-failed", "preflight", "timeout", "startup"])
def test_suite_stops_and_preserves_native_failure_and_cleanup(
    inputs, tmp_path, monkeypatch, failure
):
    attempts = []

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
                "profile": "esp32c3-ram-uart-v1",
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
                failed = failure == "native-failed" and folder.name == "b"
                value.update(
                    ok=not failed,
                    status="failed" if failed else "passed",
                    artifacts={},
                    errors=[{"code": "ASSERTION_FAILED"}] if failed else [],
                )
                (folder / "report.json").write_text(json.dumps(value))
                code = 1 if failed else 0
            if operation == "inspect-report":
                report = json.loads(Path(self.args[2]).read_bytes())
                value["report_status"] = report["status"]
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
    assert report["ok"] is (failure is None)
    if failure == "native-failed":
        assert attempts == ["a", "b"] and report["cases"][-1]["status"] == "not_run"
        assert len(json.loads((output / "trace-input.json").read_bytes())["sources"]) == 2
    if failure in ("preflight", "startup"):
        assert attempts == []
    if failure == "timeout":
        assert attempts == ["a"]
    if failure == "startup":
        assert report["emulator_processes_stopped"] is False
    saved = output / "report.json"
    assert (
        sim.inspect_report(saved, digest(saved.read_bytes()))["report_status"] == report["status"]
    )
    (output / "plan.json").write_bytes(b"changed")
    with pytest.raises(HilError):
        sim.inspect_report(saved, digest(saved.read_bytes()))
