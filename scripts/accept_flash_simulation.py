"""Development-only cold-install Flash/HIL/Trace checks, with actual emulators."""

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

    def call(label, module, arguments, expected=0):
        command = [str(python), "-I", "-m", module, *map(str, arguments)]
        result = subprocess.run(command, cwd=output, capture_output=True, timeout=300)
        (output / (label + ".stdout.json")).write_bytes(result.stdout)
        (output / (label + ".stderr.bin")).write_bytes(result.stderr)
        calls.append({"name": label, "argv": command, "exit_code": result.returncode})
        (output / "calls.json").write_text(json.dumps(calls, indent=2) + "\n")
        assert result.returncode == expected, (label, result.stdout, result.stderr)
        assert not result.stderr, (label, result.stderr)
        value = json.loads(result.stdout)
        assert value["hardware_access"] is False
        return value

    def suite(name, plans, statuses, *, wheel=None, timeout=180, trace=True):
        wheel = wheel or args.sim_wheel
        spec = {
            "schema_version": "embedded-hil-runner.simulation-spec.v1",
            "python": {"path": str(python), "sha256": sha(python)},
            "sim_runner_wheel": {"path": str(wheel), "sha256": sha(wheel)},
            "cases": [
                {"id": identity, "plan": {"path": str(path), "sha256": sha(path)}}
                for identity, path in plans
            ],
            "timeout_seconds": timeout,
        }
        source, plan = output / (name + ".spec.json"), output / (name + ".plan.json")
        source.write_text(json.dumps(spec))
        call(
            name + "-plan", "hil_runner", ["simulation", "plan", source, "--output", plan, "--json"]
        )
        run = output / (name + " suite 输出")
        success = all(s in ("passed", "passed_with_model_limits") for s in statuses)
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
                run,
                "--json",
            ],
            0 if success else 1,
        )
        assert [c["status"] for c in report["cases"]] == statuses, report
        assert report["status"] == (
            "failed"
            if not success
            else "passed_with_model_limits"
            if "passed_with_model_limits" in statuses
            else "passed"
        )
        assert report["emulator_processes_stopped"] is True
        assert all(
            c["cleanup"]["process_tree_stopped"] and c["cleanup"]["capture_complete"]
            for c in report["calls"]
        )
        assert report["retries"] == 0 and report["target_cleanup_verified"] is False
        inspected = call(
            name + "-inspect",
            "hil_runner",
            [
                "simulation",
                "inspect",
                run / "report.json",
                "--sha256",
                sha(run / "report.json"),
                "--json",
            ],
        )
        assert inspected["report_status"] == report["status"]
        if not trace:
            return report
        timeline = output / (name + ".timeline.json")
        call(
            name + "-correlate",
            "embedded_trace",
            ["correlate", run / "trace-input.json", "--output", timeline, "--json"],
        )
        doc = json.loads(timeline.read_bytes())
        expected_outcomes = {
            "passed": "succeeded",
            "passed_with_model_limits": "succeeded_with_model_limits",
            "failed": "failed",
        }
        for source in doc["sources"]:
            case = next(c for c in report["cases"] if c["id"] == source["id"])
            assert source["recorded_status"] == case["status"]
            assert source["capture_outcome"] == expected_outcomes[case["status"]]
            native_dir = run / "runs" / source["id"]
            native = json.loads((native_dir / "report.json").read_bytes())
            lines = sorted(
                (
                    e
                    for e in doc["events"]
                    if e["source_id"] == source["id"] and e["kind"] == "line"
                ),
                key=lambda e: e["source_ordinal"],
            )
            assert (
                b"".join(base64.b64decode(e["payload"]["raw_base64"]) for e in lines)
                == (native_dir / "uart.bin").read_bytes()
            )
            if source["profile"] == "esp32c3-idf-flash-v1":
                assert source["model_diagnostics"] == case["model_diagnostics"]
                assert (
                    source["model_coverage_complete"]
                    is source["security_features_verified"]
                    is False
                )
                if case["status"] == "passed_with_model_limits":
                    assert source["model_diagnostics"] == native["assertions"]["model_diagnostics"]
                    stderr = (native_dir / "backend.stderr.bin").read_text().splitlines()
                    assert all(
                        stderr.count(d["message"]) == d["count"]
                        for d in source["model_diagnostics"]
                    )
        for operation in ("inspect", "query", "report"):
            arguments = [operation, timeline, "--sha256", sha(timeline), "--json"]
            if operation == "query":
                arguments += ["--contains", "HEARTBEAT", "--limit", "100"]
            if operation == "report":
                arguments += ["--output", output / (name + ".md")]
            value = call(name + "-" + operation + "-timeline", "embedded_trace", arguments)
            assert value["data"]["capture_outcomes"] == {
                s["id"]: s["capture_outcome"] for s in doc["sources"]
            }
        if "passed_with_model_limits" in statuses:
            assert doc["status"] == "correlated_with_warnings"
            markdown = (output / (name + ".md")).read_text()
            assert (
                "passed_with_model_limits" in markdown
                and '"model_coverage_complete": false' in markdown
            )
            # A rehashed derived view cannot flatten native limitations.
            changed = json.loads(timeline.read_bytes())
            limited = next(
                s for s in changed["sources"] if s["recorded_status"] == "passed_with_model_limits"
            )
            limited["model_diagnostics"] = []
            tampered = output / (name + ".tampered.json")
            tampered.write_text(json.dumps(changed))
            call(
                name + "-reject-flattened",
                "embedded_trace",
                ["inspect", tampered, "--sha256", sha(tampered), "--json"],
                2,
            )
        return report

    limited = "passed_with_model_limits"
    suite("flash-pair", [("a", args.flash_plan), ("b", args.flash_plan)], [limited, limited])
    suite(
        "mixed",
        [("ram", args.ram_plan), ("renode", args.renode_plan), ("flash", args.flash_plan)],
        ["passed", "passed", limited],
    )
    for name, plan in (
        ("wrong-build", args.wrong_plan),
        ("panic", args.panic_plan),
        ("native-timeout", args.hang_plan),
    ):
        report = suite(name, [("bad", plan), ("unused", args.flash_plan)], ["failed", "not_run"])
        assert not (output / (name + " suite 输出") / "runs/unused").exists()
        native = json.loads(Path(report["cases"][0]["report"]["path"]).read_bytes())
        assert native["errors"][0]["code"] == (
            "TIMEOUT" if name == "native-timeout" else "ASSERTION_FAILED"
        )
    bad = json.loads(args.flash_plan.read_bytes())
    bad["model_sha256"] = "0" * 64
    invalid = output / "invalid-native.json"
    invalid.write_text(json.dumps(bad))
    report = suite(
        "preflight", [("a", args.flash_plan), ("bad", invalid)], ["not_run", "not_run"], trace=False
    )
    assert report["errors"][0]["code"] == "PREFLIGHT_FAILED" and not list(
        (output / "preflight suite 输出/runs").iterdir()
    )
    if args.legacy_wheel:
        suite("legacy-020", [("ram", args.legacy_plan)], ["passed"], wheel=args.legacy_wheel)
    if args.parent_hang_plan:
        report = suite(
            "parent-timeout",
            [("hang", args.parent_hang_plan), ("unused", args.flash_plan)],
            ["execution_attempted", "not_run"],
            timeout=20,
            trace=False,
        )
        assert report["trace_input"] is None and report["errors"][0]["code"] == "TIMEOUT"
        partial = output / "parent-timeout suite 输出/runs/hang"
        assert (partial / "flash-input.bin").is_file() and (partial / "flash-work.bin").is_file()
        assert not (partial / "report.json").exists()
        assert "runs/hang/flash-work.bin" in report["artifacts"]
    summary = {
        "ok": True,
        "commands": len(calls),
        "hardware_access": False,
        "execution_kind": "simulation",
        "physical_board_verified": False,
    }
    (output / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "prefix",
        "output",
        "sim-wheel",
        "flash-plan",
        "wrong-plan",
        "panic-plan",
        "hang-plan",
        "ram-plan",
        "renode-plan",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("legacy-wheel", "legacy-plan", "parent-hang-plan"):
        parser.add_argument("--" + name, type=Path)
    accept(parser.parse_args())
