"""Installed ppi suites and lossless offline Trace views; development only."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from hil_runner.child import Child
from hil_runner.simulation import PPI_LABELS


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def accept(args):
    output = args.output.absolute()
    output.mkdir(parents=True)
    python = args.prefix / "Scripts/python.exe"
    fields = (
        *PPI_LABELS,
        "fault_scenario",
        "fault_request",
        "ppi_evidence",
        "native_errors",
        "virtual_time",
    )
    calls, suites = [], []

    def call(name, module, arguments, expected=0):
        command = [str(python), "-I", "-B", "-m", module, *map(str, arguments)]
        child = Child(command, output, name, jsonl=False)
        try:
            code, raw = child.control(300, lambda: None)
        finally:
            cleanup = child.stop(5)
            calls.append(dict(name=name, argv=command, cleanup=cleanup))
            (output / "calls.json").write_text(json.dumps(calls, indent=2) + "\n")
        assert (
            code == expected and cleanup["process_tree_stopped"] and cleanup["capture_complete"]
        ), (name, cleanup, raw)
        assert not cleanup["forced_termination"]
        assert not (output / (name + ".stderr.log")).read_bytes(), name
        value = json.loads(raw)
        assert value["hardware_access"] is False
        return value

    def suite(name, plans, statuses, preflight=False):
        spec = output / (name + ".spec.json")
        save(
            spec,
            dict(
                schema_version="embedded-hil-runner.simulation-spec.v1",
                python=dict(path=str(python), sha256=sha(python)),
                sim_runner_wheel=dict(path=str(args.sim_wheel), sha256=sha(args.sim_wheel)),
                cases=[
                    dict(id=identity, plan=dict(path=str(path), sha256=sha(path)))
                    for identity, path in plans
                ],
                timeout_seconds=180,
            ),
        )
        plan = output / (name + ".plan.json")
        prepared = call(
            name + "-plan", "hil_runner", ["simulation", "plan", spec, "--output", plan, "--json"]
        )
        assert not prepared["component_processes_started"]
        directory = output / (name + " suite 验收")
        success = all(s == "passed" for s in statuses)
        result = call(
            name + "-run",
            "hil_runner",
            ["simulation", "run", plan, "--sha256", sha(plan), "--output-dir", directory, "--json"],
            0 if success else 1,
        )
        assert [c["status"] for c in result["cases"]] == statuses
        assert result["retries"] == 0 and result["emulator_processes_stopped"] is True
        assert all(
            c["cleanup"]["process_tree_stopped"] and c["cleanup"]["capture_complete"]
            for c in result["calls"]
        )
        for case in result["cases"]:
            if case["status"] == "not_run":
                assert not (directory / "runs" / case["id"]).exists()
        saved = directory / "report.json"
        checked = call(
            name + "-inspect",
            "hil_runner",
            ["simulation", "inspect", saved, "--sha256", sha(saved), "--json"],
        )
        assert checked["report_status"] == result["status"]
        for filename, ref in result["artifacts"].items():
            p = directory / filename
            assert sha(p) == ref["sha256"] and p.stat().st_size == ref["bytes"]
        suites.append(dict(id=name, statuses=statuses, report=str(saved), sha256=sha(saved)))
        if preflight:
            assert result["trace_input"] is None and not list((directory / "runs").iterdir())
            assert result["errors"][0]["code"] == "PREFLIGHT_FAILED"
            return
        timeline = output / (name + ".timeline.json")
        call(
            name + "-correlate",
            "embedded_trace",
            ["correlate", directory / "trace-input.json", "--output", timeline, "--json"],
        )
        doc = json.loads(timeline.read_bytes())
        for source in doc["sources"]:
            case = next(c for c in result["cases"] if c["id"] == source["id"])
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
            if source["profile"] != "nrf52840-ppi-v1":
                continue
            for key in fields:
                assert source[key] == case[key], (name, key)
            assert source["ppi_evidence"] == native["assertions"]
            for key in (
                "model_coverage_complete",
                "physical_timing_verified",
                "event_time_alignment_verified",
                "ppi_routing_verified",
            ):
                assert source[key] is False
            stdout = (native_dir / "backend.stdout.bin").read_bytes()
            spans = [
                *source["ppi_observation_spans"],
                *source["ppi_sample_spans"],
                *([] if source["ppi_fault_span"] is None else [source["ppi_fault_span"]]),
            ]
            for span in spans:
                raw = (uart.read_bytes() if "sample" in span else stdout)[
                    span["byte_start"] : span["byte_end"]
                ]
                assert raw == base64.b64decode(span["raw_base64"])
                assert hashlib.sha256(raw).hexdigest() == span["sha256"]
            if name in ("ppi-fork-misroute", "ppi-channel-disable"):
                assert native["errors"][0]["code"] == "ASSERTION_FAILED"
                assert source["ppi_evidence"]["fault"]["effect_observed"] is True
                assert source["ppi_evidence"]["nominal_regression_passed"] is False
            if name == "wrong-build":
                assert source["ppi_evidence"]["samples"] == []
                assert len(source["ppi_evidence"]["model_observations"]) == 16
                assert source["ppi_evidence"]["fault"]["effect_observed"] is None
            if name == "host-timeout":
                assert source["ppi_evidence"] is None
                assert source["native_errors"][0]["code"] == "TIMEOUT"
                assert source["ppi_observation_spans"] == source["ppi_sample_spans"] == []
        moved = output / (name + ".moved.json")
        timeline.rename(moved)
        for op, suffix, extra in (
            ("inspect", "trace-inspect", []),
            ("query", "samples", ["--contains", "SAMPLE", "--limit", "100"]),
            ("query", "empty", ["--contains", "NO_SUCH_PPI_LINE", "--limit", "1"]),
            ("report", "markdown", ["--output", output / (name + ".md")]),
        ):
            value = call(
                name + "-" + suffix,
                "embedded_trace",
                [op, moved, "--sha256", sha(moved), "--json", *extra],
            )["data"]
            for source in doc["sources"]:
                summary = value["simulation_sources"][source["id"]]
                assert value["capture_outcomes"][source["id"]] == source["capture_outcome"]
                for key in (
                    *fields,
                    "ppi_observation_spans",
                    "ppi_fault_span",
                    "ppi_sample_spans",
                    "recorded_status",
                ):
                    if key in source:
                        assert summary[key] == source[key], (name, suffix, key)
        for mutation in ("evidence", "request", "span"):
            changed = json.loads(moved.read_bytes())
            s = next(s for s in changed["sources"] if "ppi_evidence" in s)
            if s["ppi_evidence"] is None:
                continue
            if mutation == "evidence":
                s["ppi_evidence"]["nominal_regression_passed"] = not s["ppi_evidence"][
                    "nominal_regression_passed"
                ]
            elif mutation == "request":
                s["fault_request"]["stimulus_index"] = 5
            else:
                s["ppi_observation_spans"][0]["byte_end"] += 1
            altered = output / (name + ".altered-" + mutation + ".json")
            save(altered, changed)
            call(
                name + "-reject-" + mutation,
                "embedded_trace",
                ["inspect", altered, "--sha256", sha(altered), "--json"],
                2,
            )
        changed = json.loads(saved.read_bytes())
        s = next(c for c in changed["cases"] if "ppi_evidence" in c)
        s["ppi_evidence"] = {}
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
        ("ppi-fork-misroute", "ppi-fork-misroute-plan.json"),
        ("ppi-channel-disable", "ppi-channel-disable-plan.json"),
        ("wrong-build", "wrong-build-plan.json"),
        ("host-timeout", "timeout-plan.json"),
    ):
        suite(name, [("bad", args.plans / filename), ("unused", normal)], ["failed", "not_run"])
    suite(
        "mixed",
        [
            ("ppi", normal),
            ("gpiote", args.plans / "gpiote-plan.json"),
            ("egu", args.plans / "egu-plan.json"),
        ],
        ["passed", "passed", "passed"],
    )
    changed = json.loads(normal.read_bytes())
    changed["script_sha256"] = "0" * 64
    invalid = output / "bad-native-plan.json"
    save(invalid, changed)
    suite(
        "preflight",
        [("valid", normal), ("invalid", invalid)],
        ["not_run", "not_run"],
        preflight=True,
    )
    result = dict(
        ok=True,
        execution_kind="simulation",
        hardware_access=False,
        physical_board_verified=False,
        commands=len(calls),
        suites=suites,
        native_attempts=sum(s != "not_run" for r in suites for s in r["statuses"]),
    )
    save(output / "acceptance.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prefix", "output", "sim-wheel", "plans"):
        parser.add_argument("--" + name, required=True, type=Path)
    accept(parser.parse_args())
