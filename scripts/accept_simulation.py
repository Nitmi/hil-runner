"""Drive installed HIL -> actual sim-runner -> offline Trace, preserving every CLI call."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accept(prefix, output, wheel, positive, wrong, hang):
    assert json.loads(positive.read_bytes()).get("backend") == "espressif-qemu"
    output.mkdir(parents=True, exist_ok=False)
    hil, trace = prefix / "Scripts/hil-runner.exe", prefix / "Scripts/embedded-trace.exe"
    python = prefix / "Scripts/python.exe"
    calls = []

    def call(name, executable, args, expected=0):
        result = subprocess.run(
            [str(executable), *args], cwd=output, capture_output=True, timeout=240
        )
        (output / (name + ".stdout.json")).write_bytes(result.stdout)
        (output / (name + ".stderr.bin")).write_bytes(result.stderr)
        calls.append(
            {"name": name, "argv": [str(executable), *args], "exit_code": result.returncode}
        )
        (output / "calls.json").write_text(json.dumps(calls, indent=2) + "\n")
        assert result.returncode == expected, (
            name,
            result.returncode,
            result.stdout,
            result.stderr,
        )
        assert not result.stderr, (name, result.stderr)
        value = json.loads(result.stdout)
        assert value["hardware_access"] is False
        return value

    native_plans = {"a": positive, "b": positive, "bad": wrong, "unused": positive}
    for suite, ids, expected in (
        ("positive", ["a", "b"], 0),
        ("failure", ["a", "bad", "unused"], 1),
    ):
        spec = {
            "schema_version": "embedded-hil-runner.simulation-spec.v1",
            "python": {"path": str(python), "sha256": sha(python)},
            "sim_runner_wheel": {"path": str(wheel), "sha256": sha(wheel)},
            "cases": [
                {
                    "id": identity,
                    "plan": {
                        "path": str(native_plans[identity]),
                        "sha256": sha(native_plans[identity]),
                    },
                }
                for identity in ids
            ],
            "timeout_seconds": 180,
        }
        selected = output / (suite + ".spec.json")
        selected.write_text(json.dumps(spec))
        plan = output / (suite + ".plan.json")
        prepared = call(
            suite + "-plan",
            hil,
            ["simulation", "plan", str(selected), "--output", str(plan), "--json"],
        )
        assert (
            prepared["component_processes_started"] is False
            and prepared["native_validation_performed"] is False
        )
        destination = output / (suite + " suite 输出")
        report = call(
            suite + "-run",
            hil,
            [
                "simulation",
                "run",
                str(plan),
                "--sha256",
                sha(plan),
                "--output-dir",
                str(destination),
                "--json",
            ],
            expected,
        )
        assert report["emulator_processes_stopped"] is True
        assert [c["status"] for c in report["cases"]] == (
            ["passed", "passed"] if expected == 0 else ["passed", "failed", "not_run"]
        )
        assert all(
            c["cleanup"]["process_tree_stopped"] and c["cleanup"]["capture_complete"]
            for c in report["calls"]
        )
        assert not (destination / "runs/unused").exists()
        saved = destination / "report.json"
        inspected = call(
            suite + "-inspect",
            hil,
            ["simulation", "inspect", str(saved), "--sha256", sha(saved), "--json"],
        )
        assert inspected["report_status"] == ("passed" if expected == 0 else "failed")
        timeline = output / (suite + ".timeline.json")
        imported = call(
            suite + "-correlate",
            trace,
            [
                "correlate",
                str(destination / "trace-input.json"),
                "--output",
                str(timeline),
                "--json",
            ],
        )
        assert imported["ok"] and imported["data"]["source_count"] == 2
        document = json.loads(timeline.read_bytes())
        assert [s["capture_outcome"] for s in document["sources"]] == (
            ["succeeded", "succeeded"] if expected == 0 else ["succeeded", "failed"]
        )
        assert all(
            s["execution_kind"] == "simulation"
            and s["native_summary_verified"] is False
            and s["native_assertions_reexecuted"] is False
            for s in document["sources"]
        )
        assert document["status"] == ("correlated" if expected == 0 else "correlated_with_warnings")
        queried = call(
            suite + "-query",
            trace,
            [
                "query",
                str(timeline),
                "--sha256",
                sha(timeline),
                "--contains",
                "HEARTBEAT",
                "--limit",
                "20",
                "--json",
            ],
        )
        assert len(queried["data"]["events"]) == 10
        markdown = output / (suite + ".md")
        rendered = call(
            suite + "-report",
            trace,
            [
                "report",
                str(timeline),
                "--sha256",
                sha(timeline),
                "--output",
                str(markdown),
                "--limit",
                "20",
                "--json",
            ],
        )
        assert rendered["ok"] and '"execution_kind": "simulation"' in markdown.read_text()
        call(
            suite + "-inspect-timeline",
            trace,
            ["inspect", str(timeline), "--sha256", sha(timeline), "--json"],
        )
    # Native validation for all cases must finish before the first emulator run.
    drift = json.loads(positive.read_bytes())
    drift["firmware"]["sha256"] = "0" * 64
    bad_plan = output / "drift.native.json"
    bad_plan.write_text(json.dumps(drift))
    spec["cases"] = [
        {"id": "first", "plan": {"path": str(positive), "sha256": sha(positive)}},
        {"id": "drift", "plan": {"path": str(bad_plan), "sha256": sha(bad_plan)}},
    ]
    selected = output / "preflight.spec.json"
    selected.write_text(json.dumps(spec))
    plan = output / "preflight.plan.json"
    call("preflight-plan", hil, ["simulation", "plan", str(selected), "--output", str(plan)])
    destination = output / "preflight failure"
    report = call(
        "preflight-run",
        hil,
        ["simulation", "run", str(plan), "--sha256", sha(plan), "--output-dir", str(destination)],
        1,
    )
    assert report["errors"][0]["code"] == "PREFLIGHT_FAILED"
    assert all(c["status"] == "not_run" for c in report["cases"])
    assert all(c["arguments"][0] == "inspect-plan" for c in report["calls"])
    assert not list((destination / "runs").iterdir())
    # Parent deadline must kill the nested Python/QEMU tree and retain partials.
    bounded = json.loads(hang.read_bytes())
    bounded["host_timeout_seconds"] = 10
    hanging = output / "hanging.native.json"
    hanging.write_text(json.dumps(bounded))
    spec["timeout_seconds"] = 1
    spec["cases"] = [{"id": "hang", "plan": {"path": str(hanging), "sha256": sha(hanging)}}]
    selected = output / "parent-timeout.spec.json"
    selected.write_text(json.dumps(spec))
    plan = output / "parent-timeout.plan.json"
    call("parent-timeout-plan", hil, ["simulation", "plan", str(selected), "--output", str(plan)])
    destination = output / "parent timeout"
    report = call(
        "parent-timeout-run",
        hil,
        ["simulation", "run", str(plan), "--sha256", sha(plan), "--output-dir", str(destination)],
        1,
    )
    assert (
        report["errors"][0]["code"] == "TIMEOUT"
        and report["cases"][0]["status"] == "execution_attempted"
    )
    assert report["trace_input"] is None and report["emulator_processes_stopped"] is True
    assert report["calls"][-1]["cleanup"]["forced_termination"] is True
    assert (destination / "runs/hang/firmware.elf").is_file() and not (
        destination / "runs/hang/report.json"
    ).exists()
    saved = destination / "report.json"
    call(
        "parent-timeout-inspect", hil, ["simulation", "inspect", str(saved), "--sha256", sha(saved)]
    )
    # A copied timeline remains valid with no native directory; native artifact drift does not.
    copied = output / "copied.timeline.json"
    shutil.copyfile(output / "positive.timeline.json", copied)
    call("copied-timeline", trace, ["inspect", str(copied), "--sha256", sha(copied)])
    tamper = output / "tampered suite"
    shutil.copytree(output / "positive suite 输出", tamper, ignore=shutil.ignore_patterns("host"))
    uart = tamper / "runs/a/uart.bin"
    original = uart.read_bytes()
    uart.write_bytes(original + b"changed\n")
    call(
        "tampered-suite",
        hil,
        [
            "simulation",
            "inspect",
            str(tamper / "report.json"),
            "--sha256",
            sha(tamper / "report.json"),
        ],
        2,
    )
    call(
        "tampered-native",
        trace,
        [
            "correlate",
            str(tamper / "trace-input.json"),
            "--output",
            str(output / "should-not-exist.json"),
        ],
        2,
    )
    assert not (output / "should-not-exist.json").exists()
    summary = {
        "ok": True,
        "hardware_access": False,
        "actual_qemu_runs": 5,
        "positive_suites": 1,
        "fail_fast_suites": 1,
        "preflight_rejection_suites": 1,
        "parent_timeout_suites": 1,
        "trace_sources": 4,
        "calls": len(calls),
    }
    (output / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sim-wheel", type=Path, required=True)
    p.add_argument("--positive-plan", type=Path, required=True)
    p.add_argument("--negative-plan", type=Path, required=True)
    p.add_argument("--hang-plan", type=Path, required=True)
    args = p.parse_args()
    accept(
        args.prefix,
        args.output,
        args.sim_wheel,
        args.positive_plan,
        args.negative_plan,
        args.hang_plan,
    )
