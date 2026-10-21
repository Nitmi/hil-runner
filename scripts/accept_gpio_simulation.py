"""Development-only cold HIL -> actual simulator -> offline Trace GPIO acceptance."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accept(args):
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    python = args.prefix / "Scripts/python.exe"
    calls = []

    def call(name, module, arguments, expected=0):
        command = [str(python), "-I", "-m", module, *map(str, arguments)]
        result = subprocess.run(command, cwd=output, capture_output=True, timeout=300)
        (output / (name + ".stdout.json")).write_bytes(result.stdout)
        (output / (name + ".stderr.bin")).write_bytes(result.stderr)
        calls.append({"name": name, "argv": command, "exit_code": result.returncode})
        (output / "calls.json").write_text(json.dumps(calls, indent=2) + "\n")
        assert result.returncode == expected and not result.stderr, (
            name,
            result.stdout,
            result.stderr,
        )
        value = json.loads(result.stdout)
        assert value["hardware_access"] is False
        return value

    def suite(name, native_plans, statuses, *, wheel=None, timeout=180, trace=True):
        wheel = wheel or args.sim_wheel
        spec = {
            "schema_version": "embedded-hil-runner.simulation-spec.v1",
            "python": {"path": str(python), "sha256": sha(python)},
            "sim_runner_wheel": {"path": str(wheel), "sha256": sha(wheel)},
            "cases": [
                {"id": identity, "plan": {"path": str(path), "sha256": sha(path)}}
                for identity, path in native_plans
            ],
            "timeout_seconds": timeout,
        }
        source, plan = output / (name + ".spec.json"), output / (name + ".plan.json")
        source.write_text(json.dumps(spec))
        prepared = call(
            name + "-plan", "hil_runner", ["simulation", "plan", source, "--output", plan, "--json"]
        )
        assert prepared["component_processes_started"] is False
        destination = output / (name + " suite 输出")
        successful = all(status in ("passed", "passed_with_model_limits") for status in statuses)
        report = call(
            name + "-run",
            "hil_runner",
            [
                "simulation",
                "run",
                plan,
                "--sha256",
                sha(plan),
                "--output-dir",
                destination,
                "--json",
            ],
            0 if successful else 1,
        )
        assert [c["status"] for c in report["cases"]] == statuses, report
        assert report["emulator_processes_stopped"] is True and report["retries"] == 0
        assert all(
            c["cleanup"]["process_tree_stopped"] and c["cleanup"]["capture_complete"]
            for c in report["calls"]
        )
        saved = destination / "report.json"
        inspected = call(
            name + "-inspect",
            "hil_runner",
            ["simulation", "inspect", saved, "--sha256", sha(saved), "--json"],
        )
        assert inspected["report_status"] == report["status"]
        if not trace:
            return report
        timeline = output / (name + ".timeline.json")
        call(
            name + "-correlate",
            "embedded_trace",
            ["correlate", destination / "trace-input.json", "--output", timeline, "--json"],
        )
        doc = json.loads(timeline.read_bytes())
        gpio = []
        for source in doc["sources"]:
            case = next(c for c in report["cases"] if c["id"] == source["id"])
            native_dir = destination / "runs" / source["id"]
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
            assert b"".join(base64.b64decode(e["payload"]["raw_base64"]) for e in events) == (
                (native_dir / "uart.bin").read_bytes()
                if (native_dir / "uart.bin").is_file()
                else b""
            )
            assert all(e["time"] == source["host_window"] for e in events)
            if source["profile"] == "nrf52840-gpio-timer-v1":
                gpio.append(source)
                assert source["gpio_evidence"] == case["gpio_evidence"]
                assert (
                    source["model_coverage_complete"] is source["physical_timing_verified"] is False
                )
                expected = {
                    key: native["assertions"][key] if native["assertions"] is not None else None
                    for key in ("samples", "model_observations")
                }
                assert source["gpio_evidence"] == expected
                raw = (native_dir / "backend.stdout.bin").read_bytes()
                for span in source["gpio_observation_spans"]:
                    record = raw[span["byte_start"] : span["byte_end"]]
                    assert record == base64.b64decode(span["raw_base64"])
                    assert hashlib.sha256(record).hexdigest() == span["sha256"]
                assert source["warnings"]["model_coverage_incomplete"] == 1
            if source["recorded_status"] == "passed_with_model_limits":
                assert source["capture_outcome"] == "succeeded_with_model_limits"
                assert source["model_diagnostics"] == native["assertions"]["model_diagnostics"]
        for operation in ("inspect", "query", "report"):
            arguments = [operation, timeline, "--sha256", sha(timeline), "--json"]
            if operation == "query":
                arguments += ["--contains", "SAMPLE", "--limit", "100"]
            if operation == "report":
                arguments += ["--output", output / (name + ".md")]
            value = call(name + "-" + operation + "-timeline", "embedded_trace", arguments)["data"]
            for source in gpio:
                summary = value["simulation_sources"][source["id"]]
                assert summary["gpio_evidence"] == source["gpio_evidence"]
                assert summary["gpio_observation_spans"] == source["gpio_observation_spans"]
                assert summary["physical_timing_verified"] is False
        if gpio:
            assert doc["status"] == "correlated_with_warnings"
            assert "gpio_observation_semantics" in (output / (name + ".md")).read_text()
        if gpio and gpio[0]["gpio_observation_spans"]:
            for mutation in ("coverage", "snapshot", "span"):
                changed = json.loads(timeline.read_bytes())
                source = next(s for s in changed["sources"] if s["id"] == gpio[0]["id"])
                if mutation == "coverage":
                    source["physical_timing_verified"] = True
                if mutation == "snapshot":
                    source["gpio_evidence"]["model_observations"][0]["requested_virtual_ms"] += 1
                if mutation == "span":
                    source["gpio_observation_spans"][0]["byte_end"] += 1
                altered = output / (name + ".altered-" + mutation + ".json")
                altered.write_text(json.dumps(changed))
                call(
                    name + "-reject-" + mutation,
                    "embedded_trace",
                    ["inspect", altered, "--sha256", sha(altered), "--json"],
                    2,
                )
            changed = json.loads(saved.read_bytes())
            next(c for c in changed["cases"] if c["id"] == gpio[0]["id"])["gpio_evidence"] = {}
            altered = destination / "altered-summary.json"
            altered.write_text(json.dumps(changed))
            call(
                name + "-reject-hil-summary",
                "hil_runner",
                ["simulation", "inspect", altered, "--sha256", sha(altered), "--json"],
                2,
            )
        return report

    suite(
        "gpio-pair",
        [("a", args.plans / "normal.json"), ("b", args.plans / "normal.json")],
        ["passed", "passed"],
    )
    suite(
        "mixed",
        [
            ("gpio", args.plans / "normal.json"),
            ("uart", args.uart_plan),
            ("ram", args.ram_plan),
            ("flash", args.flash_plan),
        ],
        ["passed", "passed", "passed", "passed_with_model_limits"],
    )
    for name in (
        "wrong-build",
        "invert_output",
        "slow_timer",
        "missing_irq",
        "unmapped_write",
        "host-timeout",
    ):
        report = suite(
            name,
            [("bad", args.plans / (name + ".json")), ("unused", args.plans / "normal.json")],
            ["failed", "not_run"],
        )
        assert not (output / (name + " suite 输出/runs/unused")).exists()
        native = json.loads(Path(report["cases"][0]["report"]["path"]).read_bytes())
        expected = (
            "TIMEOUT"
            if name == "host-timeout"
            else "MODEL_COVERAGE_FAILED"
            if name == "unmapped_write"
            else "ASSERTION_FAILED"
        )
        assert native["errors"][0]["code"] == expected
    invalid = output / "bad-native-plan.json"
    doc = json.loads((args.plans / "normal.json").read_bytes())
    doc["script_sha256"] = "0" * 64
    invalid.write_text(json.dumps(doc))
    report = suite(
        "preflight",
        [("a", args.plans / "normal.json"), ("bad", invalid)],
        ["not_run", "not_run"],
        trace=False,
    )
    assert report["errors"][0]["code"] == "PREFLIGHT_FAILED"
    assert not list((output / "preflight suite 输出/runs").iterdir())
    if args.legacy_wheel:
        suite("legacy-020", [("ram", args.legacy_plan)], ["passed"], wheel=args.legacy_wheel)
        suite(
            "legacy-030",
            [("flash", args.legacy_flash_plan)],
            ["passed_with_model_limits"],
            wheel=args.legacy_flash_wheel,
        )
    if args.parent_timeout:
        report = suite(
            "parent-timeout",
            [("gpio", args.plans / "normal.json"), ("unused", args.plans / "normal.json")],
            ["execution_attempted", "not_run"],
            timeout=3,
            trace=False,
        )
        assert report["errors"][0]["code"] == "TIMEOUT" and report["trace_input"] is None
        assert report["cases"][0]["preflight_passed"] is True
        assert not (output / "parent-timeout suite 输出/runs/unused").exists()
    summary = {
        "ok": True,
        "commands": len(calls),
        "execution_kind": "simulation",
        "hardware_access": False,
        "physical_board_verified": False,
    }
    (output / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prefix", "output", "sim-wheel", "plans", "uart-plan", "ram-plan", "flash-plan"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("legacy-wheel", "legacy-plan", "legacy-flash-wheel", "legacy-flash-plan"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--parent-timeout", action="store_true")
    accept(parser.parse_args())
