"""Development-only cold HIL -> Renode fault -> offline Trace acceptance. No hardware."""

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
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def accept(args):
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    calls, suites = [], []
    python = args.prefix / "Scripts/python.exe"

    def call(name, module, arguments, expected=0):
        command = [str(python), "-I", "-m", module, *map(str, arguments)]
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

    def suite(name, native_plans, statuses, *, trace=True):
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
        if not trace:
            assert report["trace_input"] is None and not list((directory / "runs").iterdir())
            assert report["errors"][0]["code"] == "PREFLIGHT_FAILED"
            return
        timeline = output / (name + ".timeline.json")
        call(
            name + "-correlate",
            "embedded_trace",
            ["correlate", directory / "trace-input.json", "--output", timeline, "--json"],
        )
        doc = json.loads(timeline.read_bytes())
        for source in doc["sources"]:
            case = next(c for c in report["cases"] if c["id"] == source["id"])
            native_dir = directory / "runs" / source["id"]
            native = json.loads((native_dir / "report.json").read_bytes())
            assert source["recorded_status"] == case["status"] == native["status"]
            assert source["capture_outcome"] == (
                "failed"
                if native["status"] == "failed"
                else "succeeded_with_model_limits"
                if native["status"] == "passed_with_model_limits"
                else "succeeded"
            )
            events = sorted(
                (
                    e
                    for e in doc["events"]
                    if e["source_id"] == source["id"] and e["kind"] == "line"
                ),
                key=lambda e: e["source_ordinal"],
            )
            assert b"".join(base64.b64decode(e["payload"]["raw_base64"]) for e in events) == (
                (native_dir / "uart.bin").read_bytes()
                if (native_dir / "uart.bin").exists()
                else b""
            )
            assert all(e["time"] == source["host_window"] for e in events)
            if source["profile"] == "nrf52840-gpio-timer-fault-v1":
                assert source["fault_evidence"] == case["fault_evidence"] == native["assertions"]
                for key in (
                    "fault_scenario",
                    "fault_scope",
                    "fault_request",
                    "native_errors",
                    "virtual_time",
                    "gpio_evidence",
                ):
                    assert source[key] == case[key]
                assert (
                    source["model_coverage_complete"] is source["physical_timing_verified"] is False
                )
                raw = (native_dir / "backend.stdout.bin").read_bytes()
                for span in source["gpio_observation_spans"]:
                    record = raw[span["byte_start"] : span["byte_end"]]
                    assert record == base64.b64decode(span["raw_base64"])
                    assert hashlib.sha256(record).hexdigest() == span["sha256"]
                if name in ("stuck-low", "stuck-high", "stopped-timer", "masked-irq"):
                    assert native["errors"][0]["code"] == "ASSERTION_FAILED"
                    assert source["fault_evidence"]["fault"]["effect_observed"] is True
                    assert source["fault_evidence"]["nominal_regression_passed"] is False
                if name == "wrong-build":
                    assert source["fault_evidence"]["build_matches"] is False
                if name == "host-timeout":
                    assert native["errors"][0]["code"] == "TIMEOUT"
                    assert source["fault_evidence"] is None
        for operation in ("inspect", "query", "report"):
            arguments = [operation, timeline, "--sha256", sha(timeline), "--json"]
            if operation == "query":
                arguments += ["--contains", "SAMPLE", "--limit", "100"]
            if operation == "report":
                arguments += ["--output", output / (name + ".md")]
            value = call(name + "-" + operation + "-timeline", "embedded_trace", arguments)["data"]
            for source in doc["sources"]:
                summary = value["simulation_sources"][source["id"]]
                for key in (
                    "recorded_status",
                    "fault_scenario",
                    "fault_scope",
                    "fault_request",
                    "fault_evidence",
                    "native_errors",
                    "gpio_observation_spans",
                    "virtual_time",
                ):
                    if key in source:
                        assert summary[key] == source[key]
        if any("fault_scenario" in source for source in doc["sources"]):
            assert "fault_evidence" in (output / (name + ".md")).read_text()
            for mutation in ("effect", "request", "span"):
                changed = json.loads(timeline.read_bytes())
                source = next(s for s in changed["sources"] if "fault_scenario" in s)
                if source["fault_evidence"] is None:
                    continue
                if mutation == "effect":
                    source["fault_evidence"]["fault"]["effect_observed"] = "promoted"
                if mutation == "request":
                    source["fault_request"]["requested_virtual_ms"] = 23
                if mutation == "span":
                    source["gpio_observation_spans"][0]["byte_end"] += 1
                altered = output / (name + ".altered-" + mutation + ".json")
                save(altered, changed)
                call(
                    name + "-reject-" + mutation,
                    "embedded_trace",
                    ["inspect", altered, "--sha256", sha(altered), "--json"],
                    2,
                )
            changed = json.loads(saved.read_bytes())
            changed["cases"][0]["fault_evidence"] = {}
            altered = directory / "altered-summary.json"
            save(altered, changed)
            call(
                name + "-reject-hil-summary",
                "hil_runner",
                ["simulation", "inspect", altered, "--sha256", sha(altered), "--json"],
                2,
            )

    normal = args.plans / "normal-a.plan.json"
    suite("normal-pair", [("a", normal), ("b", normal)], ["passed", "passed"])
    for name in (
        "stuck-low",
        "stuck-high",
        "stopped-timer",
        "masked-irq",
        "wrong-build",
        "host-timeout",
    ):
        suite(
            name,
            [("bad", args.plans / (name + ".plan.json")), ("unused", normal)],
            ["failed", "not_run"],
        )
    invalid = output / "bad-native-plan.json"
    changed = json.loads(normal.read_bytes())
    changed["script_sha256"] = "0" * 64
    save(invalid, changed)
    suite(
        "preflight", [("valid", normal), ("invalid", invalid)], ["not_run", "not_run"], trace=False
    )
    if args.legacy:
        suite(
            "legacy",
            [
                (name, args.legacy / filename)
                for name, filename in (
                    ("uart", "renode-uart.json"),
                    ("gpio", "gpio-timer.json"),
                    ("ram", "c3-ram.json"),
                    ("c3flash", "c3-flash.json"),
                    ("s3flash", "s3-flash.json"),
                )
            ],
            ["passed", "passed", "passed", "passed_with_model_limits", "passed_with_model_limits"],
        )
    result = {
        "ok": True,
        "execution_kind": "simulation",
        "hardware_access": False,
        "physical_board_verified": False,
        "commands": len(calls),
        "suites": suites,
        "native_attempts": sum(
            s in ("passed", "failed", "passed_with_model_limits")
            for suite in suites
            for s in suite["statuses"]
        ),
    }
    save(output / "acceptance.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prefix", "output", "sim-wheel", "plans"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--legacy", type=Path)
    accept(parser.parse_args())
