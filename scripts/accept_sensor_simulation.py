"""Development-only installed sensor suites and offline Trace checks; no hardware."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from hil_runner.child import Child


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        assert json.loads(path.read_bytes()) == value, path
        return
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def accept(args):
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=args.resume)
    journal = output / "calls.json"
    previous = json.loads(journal.read_bytes()) if args.resume else []
    if args.resume:
        save(
            output / f"resume-inputs-{len(list(output.glob('resume-inputs-*.json'))) + 1}.json",
            {
                "calls": previous,
                "files": {
                    p.relative_to(output).as_posix(): sha(p)
                    for p in output.rglob("*")
                    if p.is_file()
                },
            },
        )
    calls, suites, reused = [], [], []
    python = args.prefix / "Scripts/python.exe"
    fields = (
        "sensor_evidence",
        "fault_scenario",
        "fault_request",
        "native_errors",
        "virtual_time",
        "model_coverage_complete",
        "physical_timing_verified",
        "sensor_accuracy_verified",
        "i2c_electrical_behavior_verified",
        "sensor_observation_semantics",
        "sensor_sample_semantics",
        "timer_observation_semantics",
    )

    def call(name, module, arguments, expected=0):
        command = [str(python), "-I", "-B", "-m", module, *map(str, arguments)]
        cached = next((row for row in previous if row["name"] == name), None)
        if cached is not None:
            assert cached["argv"] == command
            cleanup = cached["cleanup"]
            assert cleanup["exit_code"] == expected and cleanup["process_tree_stopped"]
            assert cleanup["capture_complete"] and not cleanup["forced_termination"]
            assert not (output / (name + ".stderr.log")).read_bytes()
            raw = (output / (name + ".stdout.bin")).read_bytes()
            calls.append(cached)
            reused.append(name)
            return json.loads(raw)
        child = Child(command, output, name, jsonl=False)
        try:
            code, raw = child.control(300, lambda: None)
        finally:
            cleanup = child.stop(5)
            calls.append({"name": name, "argv": command, "cleanup": cleanup})
            (output / "calls.json").write_text(json.dumps(calls, indent=2) + "\n")
        assert cleanup["process_tree_stopped"] and cleanup["capture_complete"]
        assert not cleanup["forced_termination"] and code == expected, (name, cleanup, raw)
        assert not (output / (name + ".stderr.log")).read_bytes(), name
        value = json.loads(raw)
        assert value["hardware_access"] is False, name
        return value

    def suite(name, native_plans, statuses, *, preflight=False):
        spec = output / (name + ".spec.json")
        save(
            spec,
            {
                "schema_version": "embedded-hil-runner.simulation-spec.v1",
                "python": {"path": str(python), "sha256": sha(python)},
                "sim_runner_wheel": {"path": str(args.sim_wheel), "sha256": sha(args.sim_wheel)},
                "cases": [
                    {"id": identity, "plan": {"path": str(path), "sha256": sha(path)}}
                    for identity, path in native_plans
                ],
                "timeout_seconds": 180,
            },
        )
        plan = output / (name + ".plan.json")
        prepared = call(
            name + "-plan", "hil_runner", ["simulation", "plan", spec, "--output", plan, "--json"]
        )
        assert prepared["component_processes_started"] is False
        directory = output / (name + " suite 验收")
        success = all(status in ("passed", "passed_with_model_limits") for status in statuses)
        report = call(
            name + "-run",
            "hil_runner",
            ["simulation", "run", plan, "--sha256", sha(plan), "--output-dir", directory, "--json"],
            0 if success else 1,
        )
        assert [row["status"] for row in report["cases"]] == statuses, report
        assert report["retries"] == 0 and report["emulator_processes_stopped"] is True
        assert all(
            c["cleanup"]["process_tree_stopped"] and c["cleanup"]["capture_complete"]
            for c in report["calls"]
        )
        for case in report["cases"]:
            if case["status"] == "not_run":
                assert not (directory / "runs" / case["id"]).exists()
        saved = directory / "report.json"
        inspected = call(
            name + "-inspect",
            "hil_runner",
            ["simulation", "inspect", saved, "--sha256", sha(saved), "--json"],
        )
        assert inspected["report_status"] == report["status"]
        for filename, ref in report["artifacts"].items():
            artifact = directory / filename
            assert sha(artifact) == ref["sha256"] and artifact.stat().st_size == ref["bytes"]
        suites.append(
            {
                "id": name,
                "statuses": statuses,
                "report": str(saved),
                "sha256": sha(saved),
                "artifacts_verified": len(report["artifacts"]),
            }
        )
        if preflight:
            assert report["trace_input"] is None and not list((directory / "runs").iterdir())
            assert report["errors"][0]["code"] == "PREFLIGHT_FAILED"
            return
        timeline = output / (name + ".timeline.json")
        call(
            name + "-correlate",
            "embedded_trace",
            ["correlate", directory / "trace-input.json", "--output", timeline, "--json"],
        )
        moved = output / (name + ".moved.json")
        doc = json.loads((timeline if timeline.exists() else moved).read_bytes())
        for source in doc["sources"]:
            case = next(c for c in report["cases"] if c["id"] == source["id"])
            native_dir = directory / "runs" / source["id"]
            native = json.loads((native_dir / "report.json").read_bytes())
            assert source["recorded_status"] == case["status"] == native["status"]
            events = sorted(
                (
                    e
                    for e in doc["events"]
                    if e["source_id"] == source["id"] and e["kind"] == "line"
                ),
                key=lambda e: e["source_ordinal"],
            )
            uart = native_dir / "uart.bin"
            assert b"".join(base64.b64decode(e["payload"]["raw_base64"]) for e in events) == (
                uart.read_bytes() if uart.exists() else b""
            )
            assert all(e["time"] == source["host_window"] for e in events)
            if source["profile"] != "nrf52840-i2c-sensor-v1":
                continue
            assert source["sensor_evidence"] == native["assertions"]
            for key in fields:
                assert source[key] == case[key], (name, key)
            assert all(
                source[k] is False
                for k in (
                    "model_coverage_complete",
                    "physical_timing_verified",
                    "sensor_accuracy_verified",
                    "i2c_electrical_behavior_verified",
                )
            )
            raw = (native_dir / "backend.stdout.bin").read_bytes()
            for span in source["sensor_observation_spans"]:
                record = raw[span["byte_start"] : span["byte_end"]]
                assert record == base64.b64decode(span["raw_base64"])
                assert hashlib.sha256(record).hexdigest() == span["sha256"]
            if name == "normal-pair":
                assert any(
                    row["celsius"] == -10 and row["raw_byte"] == 246
                    for row in source["sensor_evidence"]["samples"]
                )
                assert len(source["sensor_evidence"]["samples"]) == 16
            if name in ("frozen", "offset"):
                assert source["native_errors"][0]["code"] == "ASSERTION_FAILED"
                assert source["sensor_evidence"]["fault"]["effect_observed"] is True
                assert source["sensor_evidence"]["nominal_regression_passed"] is False
            if name == "wrong-build":
                assert source["sensor_evidence"]["build_matches"] is False
            if name == "host-timeout":
                assert source["native_errors"][0]["code"] == "TIMEOUT"
                assert source["sensor_evidence"] is None
                assert source["sensor_observation_spans"] == []
        # Move the self-contained timeline; these views cannot reopen original inputs.
        if timeline.exists():
            timeline.rename(moved)
        for operation, suffix, extra in (
            ("inspect", "trace-inspect", []),
            ("query", "samples", ["--contains", "SAMPLE", "--limit", "100"]),
            ("query", "empty", ["--contains", "NO_SUCH_SENSOR_LINE_7ad", "--limit", "1"]),
            ("report", "markdown", ["--output", output / (name + ".md")]),
        ):
            value = call(
                name + "-" + suffix,
                "embedded_trace",
                [operation, moved, "--sha256", sha(moved), "--json", *extra],
            )["data"]
            for source in doc["sources"]:
                summary = value["simulation_sources"][source["id"]]
                assert value["capture_outcomes"][source["id"]] == source["capture_outcome"]
                for key in (
                    *fields,
                    "sensor_observation_spans",
                    "recorded_status",
                ):
                    if key in source:
                        assert summary[key] == source[key], (name, suffix, key)
        for mutation in ("evidence", "request", "span"):
            changed = json.loads(moved.read_bytes())
            source = next(s for s in changed["sources"] if "sensor_evidence" in s)
            if source["sensor_evidence"] is None:
                continue
            if mutation == "evidence":
                source["sensor_evidence"]["samples"][0]["celsius"] += 1
            elif mutation == "request":
                source["fault_request"]["requested_virtual_ms"] = 23
            else:
                source["sensor_observation_spans"][0]["byte_end"] += 1
            altered = output / (name + ".altered-" + mutation + ".json")
            save(altered, changed)
            call(
                name + "-reject-" + mutation,
                "embedded_trace",
                ["inspect", altered, "--sha256", sha(altered), "--json"],
                2,
            )
        changed = json.loads(saved.read_bytes())
        source = next(c for c in changed["cases"] if "sensor_evidence" in c)
        source["sensor_evidence"] = {}
        altered = directory / "altered-summary.json"
        save(altered, changed)
        call(
            name + "-reject-hil-summary",
            "hil_runner",
            ["simulation", "inspect", altered, "--sha256", sha(altered), "--json"],
            2,
        )

    normal = args.plans / "normal-1-plan.json"
    suite(
        "normal-pair",
        [("a", normal), ("b", args.plans / "normal-2-plan.json")],
        ["passed", "passed"],
    )
    for name, filename in (
        ("frozen", "frozen-plan.json"),
        ("offset", "offset-plan.json"),
        ("wrong-build", "wrong-build-plan.json"),
        ("host-timeout", "timeout-plan.json"),
    ):
        suite(name, [("bad", args.plans / filename), ("unused", normal)], ["failed", "not_run"])
    suite(
        "mixed",
        [
            ("sensor", normal),
            ("gpio", args.plans / "gpio-timer-legacy-plan.json"),
            ("wasm", args.plans / "c3-wasm-legacy-plan.json"),
        ],
        ["passed", "passed", "passed_with_model_limits"],
    )
    invalid = output / "bad-native-plan.json"
    changed = json.loads(normal.read_bytes())
    changed["script_sha256"] = "0" * 64
    save(invalid, changed)
    suite(
        "preflight",
        [("valid", normal), ("invalid", invalid)],
        ["not_run", "not_run"],
        preflight=True,
    )
    result = {
        "ok": True,
        "execution_kind": "simulation",
        "hardware_access": False,
        "physical_board_verified": False,
        "commands": len(calls),
        "reused_completed_commands": reused,
        "suites": suites,
        "native_attempts": sum(status != "not_run" for row in suites for status in row["statuses"]),
    }
    save(output / "acceptance.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prefix", "output", "sim-wheel", "plans"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Use recorded matching completed calls; never retry a command",
    )
    accept(parser.parse_args())
