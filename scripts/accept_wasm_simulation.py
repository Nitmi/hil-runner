"""Development-only cold HIL -> ESP-EMU WASM -> offline Trace acceptance."""

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
    output.mkdir(parents=True)
    python = args.prefix / "Scripts/python.exe"
    calls, suites = [], []

    def call(name, module, arguments, expected=0):
        argv = [str(python), "-I", "-m", module, *map(str, arguments)]
        child = Child(argv, output, name, jsonl=False)
        code, raw = None, b""
        try:
            code, raw = child.control(240, lambda: None)
        finally:
            cleanup = child.stop(5)
            calls.append({"name": name, "argv": argv, "exit_code": code, "cleanup": cleanup})
            (output / "calls.json").write_text(json.dumps(calls, indent=2) + "\n")
        assert cleanup["process_tree_stopped"] and cleanup["capture_complete"]
        assert not cleanup["forced_termination"] and code == expected, (name, code, raw)
        assert not (output / (name + ".stderr.log")).read_bytes(), name
        value = json.loads(raw)
        assert value["hardware_access"] is False
        return value

    def suite(name, plans, statuses, error=None, preflight=False):
        spec, plan = output / (name + ".spec.json"), output / (name + ".plan.json")
        save(
            spec,
            {
                "schema_version": "embedded-hil-runner.simulation-spec.v1",
                "python": {"path": str(python), "sha256": sha(python)},
                "sim_runner_wheel": {"path": str(args.sim_wheel), "sha256": sha(args.sim_wheel)},
                "cases": [
                    {"id": identity, "plan": {"path": str(p), "sha256": sha(p)}}
                    for identity, p in plans
                ],
                "timeout_seconds": 120,
            },
        )
        prepared = call(
            name + "-plan", "hil_runner", ["simulation", "plan", spec, "--output", plan, "--json"]
        )
        assert prepared["component_processes_started"] is False
        directory = output / (name + " suite 验收")
        report = call(
            name + "-run",
            "hil_runner",
            ["simulation", "run", plan, "--sha256", sha(plan), "--output-dir", directory, "--json"],
            0 if all(s in ("passed", "passed_with_model_limits") for s in statuses) else 1,
        )
        assert [c["status"] for c in report["cases"]] == statuses, report
        assert report["retries"] == 0 and report["emulator_processes_stopped"] is True
        assert all(
            c["cleanup"]["process_tree_stopped"]
            and c["cleanup"]["capture_complete"]
            and not c["cleanup"]["forced_termination"]
            for c in report["calls"]
        )
        saved = directory / "report.json"
        checked = call(
            name + "-inspect-hil",
            "hil_runner",
            ["simulation", "inspect", saved, "--sha256", sha(saved), "--json"],
        )
        assert checked["report_status"] == report["status"]
        for n, ref in report["artifacts"].items():
            assert sha(directory / n) == ref["sha256"]
            assert (directory / n).stat().st_size == ref["bytes"]
        for case in report["cases"]:
            if case["status"] == "not_run":
                assert not (directory / "runs" / case["id"]).exists()
        suites.append(
            {
                "name": name,
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
        doc = json.loads(timeline.read_bytes())
        for source in doc["sources"]:
            case = next(c for c in report["cases"] if c["id"] == source["id"])
            native_dir = directory / "runs" / source["id"]
            native = json.loads((native_dir / "report.json").read_bytes())
            assert source["recorded_status"] == case["status"] == native["status"]
            raw = b"".join(
                base64.b64decode(e["payload"]["raw_base64"])
                for e in sorted(doc["events"], key=lambda e: e["source_ordinal"])
                if e["source_id"] == source["id"] and e["kind"] == "line"
            )
            assert raw == (
                (native_dir / "uart.bin").read_bytes()
                if (native_dir / "uart.bin").exists()
                else b""
            )
            if source["profile"] != "esp32c3-wasm-flash-v1":
                continue
            assert source["raw_uart_bytes_verified"] is case["raw_uart_bytes_verified"] is False
            assert source["native_assertions"] == case["assertions"] == native["assertions"]
            assert source["runtime_observation"] == case["runtime_observation"]
            assert source["native_errors"] == case["native_errors"] == native["errors"]
            assert source["virtual_time"]["elapsed_ns"] is None
            assert source["uart_representation"] == "ascii_subset_of_wasm_strings_encoded_utf8"
            if error and source["recorded_status"] == "failed":
                assert native["errors"][0]["code"] == error
            for n, ref in native["artifacts"].items():
                assert sha(native_dir / n) == ref["sha256"]
                assert "runs/" + source["id"] + "/" + n in report["artifacts"]
        for operation in ("inspect", "query", "report"):
            argv = [operation, timeline, "--sha256", sha(timeline), "--json"]
            if operation == "query":
                argv += ["--contains", "HEARTBEAT", "--limit", "1"]
            if operation == "report":
                argv += ["--output", output / (name + ".md"), "--contains", "HEARTBEAT"]
            data = call(name + "-" + operation, "embedded_trace", argv)["data"]
            for source in doc["sources"]:
                if source["profile"] == "esp32c3-wasm-flash-v1":
                    summary = data["simulation_sources"][source["id"]]
                    for k in (
                        "native_errors",
                        "native_assertions",
                        "runtime_observation",
                        "raw_uart_bytes_verified",
                        "uart_representation",
                        "model_limits",
                        "virtual_time",
                        "initial_state",
                    ):
                        assert summary[k] == source[k]
        altered = output / (name + ".altered.json")
        changed = json.loads(timeline.read_bytes())
        changed["sources"][0]["raw_uart_bytes_verified"] = True
        save(altered, changed)
        call(
            name + "-reject-trace",
            "embedded_trace",
            ["inspect", altered, "--sha256", sha(altered), "--json"],
            2,
        )
        altered = directory / "altered-hil.json"
        changed = json.loads(saved.read_bytes())
        changed["cases"][0]["raw_uart_bytes_verified"] = True
        save(altered, changed)
        call(
            name + "-reject-hil",
            "hil_runner",
            ["simulation", "inspect", altered, "--sha256", sha(altered), "--json"],
            2,
        )

    normal = args.plans / "normal-a.plan.json"
    suite("normal-pair", [("a", normal), ("b", normal)], ["passed_with_model_limits"] * 2)
    for name, error in (
        ("wrong-build", "ASSERTION_FAILED"),
        ("panic", "ASSERTION_FAILED"),
        ("hang", "INSTRUCTION_BUDGET_EXCEEDED"),
        ("short-budget", "INSTRUCTION_BUDGET_EXCEEDED"),
    ):
        suite(
            name,
            [("bad", args.plans / (name + ".plan.json")), ("unused", normal)],
            ["failed", "not_run"],
            error,
        )
    # A fast host may consume the largest allowed instruction budget in <1 second.
    # Do not label that valid budget failure as a timeout or depend on host speed.
    # Null timeout observations are covered by explicit offline protocol fixtures.
    invalid = output / "bad-native.json"
    changed = json.loads(normal.read_bytes())
    changed["host_script_sha256"] = "0" * 64
    save(invalid, changed)
    suite("preflight", [("valid", normal), ("invalid", invalid)], ["not_run"] * 2, preflight=True)
    if args.legacy:
        suite(
            "mixed",
            [
                ("wasm", normal),
                ("uart", args.legacy / "renode-uart.plan.json"),
                ("flash", args.legacy / "c3-flash.plan.json"),
            ],
            ["passed_with_model_limits", "passed", "passed_with_model_limits"],
        )
    result = {
        "ok": True,
        "hardware_access": False,
        "suites": suites,
        "commands": len(calls),
        "native_attempts": sum(s != "not_run" for x in suites for s in x["statuses"]),
    }
    save(output / "acceptance.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prefix", "output", "sim-wheel", "plans"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--legacy", type=Path)
    accept(parser.parse_args())
