"""Typed simulation suites; native simulator semantics stay in sim-runner."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import zipfile
from pathlib import Path

from . import __version__
from .child import Child
from .common import HilError, decode, digest

PREFIX = "embedded-hil-runner.simulation-"
FLAGS = {
    "execution_kind": "simulation",
    "hardware_access": False,
    "physical_board_verified": False,
    "authorization_granted": False,
    "target_cleanup_verified": False,
}
MODULES = {
    "__init__.py",
    "__main__.py",
    "backend.py",
    "cli.py",
    "common.py",
    "inspect.py",
    "plan.py",
    "process.py",
    "qemu.py",
    "run.py",
    "winjob.py",
    "assets/nrf52840-uart.repl",
    "assets/esp32c3-uart.json",
}
FLASH_MODULES = MODULES | {
    "flash_image.py",
    "qemu_flash.py",
    "assets/esp32c3-idf-flash.json",
}
INVENTORIES = {"0.2.0": MODULES, "0.3.0": FLASH_MODULES}
SUCCESS = ("passed", "passed_with_model_limits")
PROFILES = {
    "embedded-sim-runner.plan.v1": ("nrf52840-uart-v1", "renode"),
    "embedded-sim-runner.qemu-plan.v1": ("esp32c3-ram-uart-v1", "espressif-qemu"),
    "embedded-sim-runner.qemu-flash-plan.v1": ("esp32c3-idf-flash-v1", "espressif-qemu"),
}
BOOTSTRAP = (
    "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
    'runpy.run_module("sim_runner",run_name="__main__")'
)


def require(value, message, code="INVALID_INPUT"):
    if not value:
        raise HilError(code, message)


def local(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    require(not str(path).startswith(("\\\\", "//")), "local paths required")
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(
            not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "links/reparse points are not supported",
        )
    return path


def read(path: Path, maximum: int, expected=None) -> tuple[bytes, dict]:
    path = local(path)
    require(path.is_file(), "regular file required")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, "file exceeds byte budget", "LIMIT_EXCEEDED")
    sha = digest(data)
    if expected is not None:
        require(
            isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected), "invalid SHA-256"
        )
        require(sha == expected, "bound input changed", "INPUT_DRIFT")
    return data, {"path": str(path), "sha256": sha, "bytes": len(data)}


def exact(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys), "unexpected document fields")
    return value


def json_new(path: Path, doc):
    data = (json.dumps(doc, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()
    require(len(data) <= 1024 * 1024, "JSON exceeds 1 MiB", "LIMIT_EXCEEDED")
    with path.open("xb") as stream:
        stream.write(data)
    return read(path, 1024 * 1024)[1]


def package(data: bytes) -> dict[str, bytes]:
    try:
        return _package(data)
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError, UnicodeError) as error:
        raise HilError("INVALID_INPUT", "invalid simulator wheel") from error


def _package(data: bytes) -> dict[str, bytes]:
    require(len(data) <= 8 * 1024 * 1024, "simulator wheel exceeds byte budget")
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        items = archive.infolist()
        require(
            len(items) <= 64 and len({i.filename.casefold() for i in items}) == len(items),
            "invalid wheel inventory",
        )
        require(sum(i.file_size for i in items) <= 8 * 1024 * 1024, "inflated wheel exceeds budget")
        versions = [
            version
            for version in INVENTORIES
            if f"embedded_sim_runner-{version}.dist-info/METADATA" in archive.namelist()
        ]
        require(len(versions) == 1, "requires sim-runner 0.2.0 or 0.3.0 wheel")
        version = versions[0]
        modules = INVENTORIES[version]
        metadata = f"embedded_sim_runner-{version}.dist-info/"
        for item in items:
            require(not item.flag_bits & 1, "encrypted wheel members unsupported")
            name = item.filename
            require(
                re.fullmatch(r"[A-Za-z0-9_./-]+", name)
                and all(p not in ("", ".", "..") for p in name.split("/")),
                "unsafe wheel member",
            )
            require(
                item.file_size <= 1024 * 1024 and not stat.S_ISLNK(item.external_attr >> 16),
                "invalid wheel member",
            )
            if name.startswith("sim_runner/"):
                relative = name.removeprefix("sim_runner/")
                require(relative in modules, "unexpected simulator module")
                result[relative] = archive.read(item)
            else:
                require(name.startswith(metadata), "unexpected wheel package")
        require(set(result) == modules, "incomplete simulator package")
        meta = archive.read(metadata + "METADATA").decode("utf-8")
        require(
            "\nName: embedded-sim-runner\n" in "\n" + meta
            and f"\nVersion: {version}\n" in "\n" + meta,
            "simulator wheel version differs",
        )
        require(
            all(
                "extra ==" in line
                for line in meta.splitlines()
                if line.startswith("Requires-Dist:")
            ),
            "simulator runtime dependencies unsupported",
        )
    return result


def compile_plan(spec_path: Path, expected=None) -> dict:
    raw, ref = read(spec_path, 65536, expected)
    spec = exact(
        decode(raw), ("schema_version", "python", "sim_runner_wheel", "cases", "timeout_seconds")
    )
    require(spec["schema_version"] == PREFIX + "spec.v1", "unsupported simulation spec")
    timeout = spec["timeout_seconds"]
    require(
        type(timeout) is int and 1 <= timeout <= 600, "component timeout must be 1..600 seconds"
    )
    inputs = {"spec": ref}
    for key in ("python", "sim_runner_wheel"):
        row = exact(spec[key], ("path", "sha256"))
        require(isinstance(row["path"], str), "input path must be a string")
        path = Path(row["path"])
        path = path if path.is_absolute() else Path(ref["path"]).parent / path
        data, inputs[key] = read(path, 8 * 1024 * 1024, row["sha256"])
        if key == "sim_runner_wheel":
            files = package(data)
    cases = spec["cases"]
    require(isinstance(cases, list) and 1 <= len(cases) <= 8, "select 1..8 simulation cases")
    selected = []
    identities = set()
    for row in cases:
        exact(row, ("id", "plan"))
        identity = row["id"]
        require(
            isinstance(identity, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identity)
            and identity not in identities,
            "invalid/duplicate case ID",
        )
        identities.add(identity)
        require(
            identity.upper()
            not in {"CON", "PRN", "AUX", "NUL"}
            | {prefix + str(i) for prefix in ("COM", "LPT") for i in range(1, 10)},
            "reserved case ID",
        )
        native = exact(row["plan"], ("path", "sha256"))
        require(isinstance(native["path"], str), "native plan path must be a string")
        path = Path(native["path"])
        path = path if path.is_absolute() else Path(ref["path"]).parent / path
        data, reference = read(path, 65536, native["sha256"])
        doc = decode(data)
        require(isinstance(doc, dict), "native plan must be an object")
        profile = PROFILES.get(doc.get("schema_version"))
        require(profile is not None, "unsupported native plan")
        require(
            (doc.get("profile"), doc.get("backend")) == profile,
            "unsupported simulation profile",
        )
        require(
            profile[0] != "esp32c3-idf-flash-v1" or set(files) == FLASH_MODULES,
            "Flash plans require sim-runner 0.3.0",
        )
        for key, value in {
            "execution_kind": "simulation",
            "hardware_access": False,
            "physical_board_verified": False,
            "physical_firmware_identity_verified": False,
        }.items():
            require(
                type(doc.get(key)) is type(value) and doc[key] == value, "invalid native boundary"
            )
        selected.append(
            {
                "id": identity,
                "plan": reference,
                "profile": doc["profile"],
                "backend": doc["backend"],
            }
        )
    return {
        "schema_version": PREFIX + "plan.v1",
        "runner_version": __version__,
        **FLAGS,
        "component_processes_started": False,
        "native_validation_performed": False,
        "inputs": inputs,
        "package_files": {k: digest(v) for k, v in files.items()},
        "cases": selected,
        "component_timeout_seconds": timeout,
        "retries": 0,
        "python_runtime_coverage": "hash_bound_interpreter_executable_and_trusted_standard_library",
    }


def load_plan(path: Path, sha: str) -> tuple[bytes, dict]:
    raw, _ = read(path, 65536, sha)
    doc = decode(raw)
    expected = compile_plan(Path(doc["inputs"]["spec"]["path"]), doc["inputs"]["spec"]["sha256"])
    require(
        json.dumps(doc, sort_keys=True) == json.dumps(expected, sort_keys=True),
        "suite plan differs from current inputs",
        "INPUT_DRIFT",
    )
    return raw, doc


def run(path: Path, sha: str, output: Path) -> dict:
    require(
        os.name == "nt",
        "simulation orchestration currently requires Windows",
        "UNSUPPORTED_PLATFORM",
    )
    raw, plan = load_plan(path, sha)
    output = local(output.parent) / output.name
    require(not output.exists() and not output.is_symlink(), "output directory exists")
    output.mkdir()
    (output / "plan.json").write_bytes(raw)
    (output / "source-spec.json").write_bytes(
        read(Path(plan["inputs"]["spec"]["path"]), 65536, plan["inputs"]["spec"]["sha256"])[0]
    )
    component = output / "component"
    bundle = package(
        read(
            Path(plan["inputs"]["sim_runner_wheel"]["path"]),
            8 * 1024 * 1024,
            plan["inputs"]["sim_runner_wheel"]["sha256"],
        )[0]
    )
    for name, data in bundle.items():
        target = component / "sim_runner" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (output / "plans").mkdir()
    (output / "runs").mkdir()
    cases = [
        {"id": row["id"], "status": "not_run", "preflight_passed": False} for row in plan["cases"]
    ]
    calls = []
    errors = []
    trace_sources = []
    native_files = []

    def invoke(arguments):
        python = plan["inputs"]["python"]
        read(Path(python["path"]), 8 * 1024 * 1024, python["sha256"])
        for name, expected_hash in plan["package_files"].items():
            read(component / "sim_runner" / name, 1024 * 1024, expected_hash)
        name = f"call-{len(calls) + 1:03}"
        command = [python["path"], "-I", "-S", "-B", "-c", BOOTSTRAP, str(component), *arguments]
        try:
            child = Child(command, output, name, jsonl=False)
        except (HilError, OSError, RuntimeError) as error:
            calls.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "exit_code": None,
                    "cleanup": {"process_tree_stopped": False, "capture_complete": False},
                    "error": "PROCESS_START_UNCERTAIN",
                }
            )
            with (output / "calls.jsonl").open("ab") as stream:
                stream.write((json.dumps(calls[-1], ensure_ascii=True) + "\n").encode())
            raise HilError(
                "PROCESS_START_UNCERTAIN", "component startup cleanup not observed"
            ) from error
        error = None
        code, stdout = None, b""
        try:
            code, stdout = child.control(plan["component_timeout_seconds"], lambda: None)
        except (HilError, KeyboardInterrupt) as caught:
            error = (
                caught
                if isinstance(caught, HilError)
                else HilError("CANCELLED", "simulation suite cancelled")
            )
        finally:
            cleanup = child.stop(5)
            record = {
                "name": name,
                "arguments": arguments,
                "exit_code": code,
                "cleanup": cleanup,
                "error": None if error is None else error.code,
            }
            calls.append(record)
            with (output / "calls.jsonl").open("ab") as stream:
                stream.write((json.dumps(record, ensure_ascii=True) + "\n").encode())
        require(
            cleanup["process_tree_stopped"] and cleanup["capture_complete"],
            "component cleanup incomplete",
            "CLEANUP_FAILED",
        )
        if error:
            raise error
        require(
            not cleanup["forced_termination"], "component was forcibly stopped", "COMPONENT_FAILED"
        )
        value = decode(stdout)
        require(isinstance(value, dict), "component returned no JSON object", "COMPONENT_FAILED")
        require(
            value.get("hardware_access") is False
            and value.get("physical_board_verified") is False
            and value.get("execution_kind") == "simulation",
            "component boundary differs",
            "COMPONENT_FAILED",
        )
        return code, value

    try:
        for row, state in zip(plan["cases"], cases, strict=True):
            staged = output / "plans" / (row["id"] + ".json")
            staged.write_bytes(read(Path(row["plan"]["path"]), 65536, row["plan"]["sha256"])[0])
            code, value = invoke(
                ["inspect-plan", "--plan", str(staged), "--sha256", row["plan"]["sha256"]]
            )
            require(
                code == 0
                and value.get("ok") is True
                and value.get("executables_started") is False
                and value.get("profile") == row["profile"],
                "native preflight failed",
                "PREFLIGHT_FAILED",
            )
            state["preflight_passed"] = True
        for row, state in zip(plan["cases"], cases, strict=True):
            state["status"] = "execution_attempted"
            staged = output / "plans" / (row["id"] + ".json")
            destination = output / "runs" / row["id"]
            code, value = invoke(
                [
                    "run",
                    "--plan",
                    str(staged),
                    "--sha256",
                    row["plan"]["sha256"],
                    "--output-dir",
                    str(destination),
                ]
            )
            report_path = destination / "report.json"
            report_data, reference = read(report_path, 1024 * 1024)
            require(
                decode(report_data) == value and value.get("profile") == row["profile"],
                "native response/report differs",
                "COMPONENT_FAILED",
            )
            inspect_code, inspected = invoke(
                ["inspect-report", "--report", str(report_path), "--sha256", reference["sha256"]]
            )
            require(
                inspect_code == 0
                and inspected.get("ok") is True
                and inspected.get("executables_started") is False
                and inspected.get("report_status") == value.get("status"),
                "native report integrity failed",
                "COMPONENT_FAILED",
            )
            require(
                type(value.get("ok")) is bool and code == (0 if value["ok"] else 1),
                "native exit/verdict mismatch",
                "COMPONENT_FAILED",
            )
            require(
                value.get("status") in (*SUCCESS, "failed")
                and value["ok"] is (value["status"] in SUCCESS),
                "native verdict mismatch",
                "COMPONENT_FAILED",
            )
            state.update(
                status=value["status"],
                report=reference,
                native_report_inspected=True,
                native_errors=value.get("errors"),
            )
            if row["profile"] == "esp32c3-idf-flash-v1":
                state.update(model_limits(value))
            native_files.append(report_path)
            for filename, artifact in value["artifacts"].items():
                require(re.fullmatch(r"[A-Za-z0-9_.-]+", filename), "invalid native artifact name")
                artifact_path = destination / filename
                read(artifact_path, 16 * 1024 * 1024, artifact["sha256"])
                native_files.append(artifact_path)
            trace_sources.append(
                {
                    "id": row["id"],
                    "format": "sim-runner-report",
                    "path": report_path.relative_to(output).as_posix(),
                    "sha256": reference["sha256"],
                    "clock_domain": "sim-" + row["id"],
                }
            )
            if not value["ok"]:
                raise HilError(
                    "SIMULATION_FAILED", "native simulation failed; subsequent cases not run"
                )
        load_plan(path, sha)
    except (HilError, OSError, ValueError, KeyError, TypeError, KeyboardInterrupt) as error:
        errors.append(
            {
                "code": getattr(
                    error,
                    "code",
                    "CANCELLED" if isinstance(error, KeyboardInterrupt) else "EVIDENCE_INVALID",
                ),
                "message": str(error)[:1024],
            }
        )
    trace_ref = None
    if trace_sources:
        trace_ref = json_new(
            output / "trace-input.json",
            {"schema_version": "embedded-trace.input.v1", "sources": trace_sources},
        )
    partial_names = {
        "plan.json",
        "runtime-lock.json",
        "firmware.elf",
        "firmware.bin",
        "model.json",
        "model.repl",
        "run.resc",
        "renode.config",
        "backend.stdout.bin",
        "backend.stderr.bin",
        "uart.bin",
        "report.json",
        "flash-input.bin",
        "flash-work.bin",
        "esp32c3-rom.bin",
        "efuse-initial.bin",
        "efuse-work.bin",
    }
    for row in plan["cases"]:
        directory = output / "runs" / row["id"]
        if directory.is_dir():
            native_files += [
                p for p in directory.iterdir() if p.name in partial_names and p.is_file()
            ]
    evidence_paths = [p for p in output.iterdir() if p.is_file()]
    evidence_paths += (
        list((output / "plans").glob("*.json"))
        + list(component.rglob("*.py"))
        + list(component.rglob("*.json"))
        + list(component.rglob("*.repl"))
        + native_files
    )
    evidence = {
        p.relative_to(output).as_posix(): read(p, 16 * 1024 * 1024)[1] for p in evidence_paths
    }
    report = {
        "schema_version": PREFIX + "report.v1",
        **FLAGS,
        "ok": not errors,
        "status": "failed"
        if errors
        else (
            "passed_with_model_limits"
            if any(case["status"] == "passed_with_model_limits" for case in cases)
            else "passed"
        ),
        "plan_sha256": digest(raw),
        "component_start_attempted": bool(calls),
        "component_processes_started": any(
            c["cleanup"].get("owner_pid") is not None for c in calls
        ),
        "cases": cases,
        "calls": calls,
        "trace_input": trace_ref,
        "artifacts": evidence,
        "errors": errors,
        "emulator_processes_stopped": all(c["cleanup"]["process_tree_stopped"] for c in calls),
        "retries": 0,
    }
    json_new(output / "report.json", report)
    return report


def model_limits(native):
    require(
        native.get("model_coverage_complete") is False
        and native.get("security_features_verified") is False,
        "invalid Flash coverage claim",
        "COMPONENT_FAILED",
    )
    assertions = native.get("assertions")
    diagnostics = assertions.get("model_diagnostics") if isinstance(assertions, dict) else []
    require(isinstance(diagnostics, list), "invalid model diagnostics", "COMPONENT_FAILED")
    if native["ok"]:
        require(
            (native["status"] == "passed_with_model_limits") is bool(diagnostics),
            "model diagnostic status differs",
            "COMPONENT_FAILED",
        )
    return {
        "model_diagnostics": diagnostics,
        "model_coverage_complete": False,
        "security_features_verified": False,
    }


def inspect_report(path: Path, sha: str) -> dict:
    raw, _ = read(path, 1024 * 1024, sha)
    doc = decode(raw)
    require(doc.get("schema_version") == PREFIX + "report.v1", "unsupported suite report")
    for key, value in FLAGS.items():
        require(type(doc.get(key)) is type(value) and doc[key] == value, "invalid suite boundary")
    require(
        doc.get("status") in (*SUCCESS, "failed") and doc.get("ok") is (doc["status"] in SUCCESS),
        "suite verdict mismatch",
    )
    artifacts = doc.get("artifacts")
    require(
        isinstance(artifacts, dict) and 1 <= len(artifacts) <= 512, "invalid artifact inventory"
    )
    total = 0
    for name, reference in artifacts.items():
        require(
            re.fullmatch(r"[A-Za-z0-9_./-]+", name)
            and all(p not in ("", ".", "..") for p in name.split("/")),
            "unsafe artifact name",
        )
        data, ref = read(path.parent / name, 16 * 1024 * 1024, reference["sha256"])
        require(ref["bytes"] == reference["bytes"], "artifact size differs")
        total += len(data)
        require(total <= 256 * 1024 * 1024, "suite evidence exceeds budget")
    require(
        "plan.json" in artifacts and artifacts["plan.json"]["sha256"] == doc.get("plan_sha256"),
        "suite plan binding differs",
    )
    plan = decode(read(path.parent / "plan.json", 65536)[0])
    require(plan.get("schema_version") == PREFIX + "plan.v1", "invalid saved suite plan")
    for key, value in FLAGS.items():
        require(
            type(plan.get(key)) is type(value) and plan[key] == value, "invalid saved plan boundary"
        )
    cases = doc.get("cases")
    require(
        isinstance(cases, list)
        and 1 <= len(cases) <= 8
        and [c.get("id") for c in cases] == [c["id"] for c in plan["cases"]],
        "suite case inventory differs",
    )
    stopped = False
    limited = False
    for case, planned in zip(cases, plan["cases"], strict=True):
        status = case.get("status")
        require(
            status in (*SUCCESS, "failed", "not_run", "execution_attempted")
            and (not stopped or status == "not_run"),
            "suite did not stop at failure",
        )
        stopped |= status not in SUCCESS
        limited |= status == "passed_with_model_limits"
        if status in (*SUCCESS, "failed"):
            name = "runs/" + case["id"] + "/report.json"
            require(
                name in artifacts and artifacts[name]["sha256"] == case["report"]["sha256"],
                "case report binding differs",
            )
            native = decode(read(path.parent / name, 1024 * 1024)[0])
            require(
                native.get("status") == status and native.get("ok") is (status in SUCCESS),
                "case verdict differs from native report",
            )
            if planned["profile"] == "esp32c3-idf-flash-v1":
                require(
                    all(case.get(k) == v for k, v in model_limits(native).items()),
                    "case model limitations differ from native report",
                )
            else:
                require(status != "passed_with_model_limits", "unsupported limited verdict")
    if doc.get("trace_input") is not None:
        require(
            "trace-input.json" in artifacts
            and artifacts["trace-input.json"]["sha256"] == doc["trace_input"]["sha256"],
            "trace input binding differs",
        )
    if doc["ok"]:
        require(
            doc.get("errors") == []
            and doc.get("emulator_processes_stopped") is True
            and all(
                case.get("status") in SUCCESS and case.get("native_report_inspected") is True
                for case in doc["cases"]
            ),
            "passing suite incomplete",
        )
        require(
            doc["status"] == ("passed_with_model_limits" if limited else "passed"),
            "suite model limitations were changed",
        )
    return {
        "schema_version": PREFIX + "inspection.v1",
        **FLAGS,
        "ok": True,
        "component_processes_started": False,
        "report_status": doc["status"],
        "artifacts_verified": len(artifacts),
        "scope": "saved_simulation_suite_integrity",
    }
