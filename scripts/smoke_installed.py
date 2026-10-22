"""Check an installed wheel from an isolated Python, using synthetic inputs only."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import hil_runner


def main() -> None:
    prefix = Path(sys.prefix).resolve()
    module = Path(hil_runner.__file__).resolve()
    assert module.is_relative_to(prefix), f"Import is outside installation: {module}"
    version = importlib.metadata.version("embedded-hil-runner")
    assert version == hil_runner.__version__
    for name in (
        "result",
        "managed-spec",
        "managed-plan",
        "managed-result",
        "simulation-spec",
        "simulation-plan",
        "simulation-report",
        "instrument-spec",
        "instrument-report",
    ):
        resource = importlib.resources.files("hil_runner") / "schemas" / f"{name}.schema.json"
        assert json.loads(resource.read_bytes())["$schema"]
    binary = prefix / ("Scripts/hil-runner.exe" if os.name == "nt" else "bin/hil-runner")
    identity = {"probe_selector": "ffff:0001:CI-INSTALL"}
    selection = {
        "schema_version": "embedded-board-registry.selection.v1",
        "ok": True,
        "status": "selected",
        "board_id": "ci-install",
        "required_transports": ["debug"],
        "bindings": [
            {
                "transport": "debug",
                "selector_id": "synthetic",
                "observation_id": "synthetic",
                "selector_identity": identity,
                "observed_identity": identity,
                "source": {"path": "synthetic.json", "sha256": "a" * 64, "point_in_time": True},
            }
        ],
        "inputs": {
            key: {"path": key + ".json", "sha256": "b" * 64} for key in ("registry", "observations")
        },
        "authorization": {"granted": False, "allowed_operations": []},
        "hardware_access": False,
        "executables_started": False,
    }
    with tempfile.TemporaryDirectory(prefix="hil-installed-smoke-") as directory:
        work = Path(directory)

        def run(*args, expected=0):
            result = subprocess.run(args, cwd=work, capture_output=True, check=False, timeout=10)
            assert result.returncode == expected, (
                args,
                result.returncode,
                result.stdout,
                result.stderr,
            )
            assert not result.stderr, result.stderr
            return result.stdout

        assert run(str(binary), "--version").decode().strip() == "hil-runner " + version
        assert run(sys.executable, "-m", "hil_runner", "--version").decode().strip() == (
            "hil-runner " + version
        )
        run(str(binary), "managed", "--help")
        saved = work / "synthetic-selection.json"
        saved.write_text(json.dumps(selection), encoding="utf-8")
        report = json.loads(
            run(
                str(binary),
                "lease",
                "plan",
                str(saved),
                "--lease-root",
                str(work / "leases"),
                "--json",
            )
        )
        assert report["ok"] and not report["hardware_access"]
        assert report["data"]["effects"] == [] and not (work / "leases").exists()
        examples = Path(__file__).resolve().parents[1] / "examples/instrument"
        for scenario in ("passed", "failed", "invalid", "mixed"):
            selected = work / scenario
            shutil.copytree(examples / scenario, selected)
            manifest = selected / "import.json"
            output = selected / "bundle.json"
            imported = json.loads(
                run(
                    str(binary),
                    "instrument",
                    "import",
                    str(manifest),
                    "--sha256",
                    hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    "--output",
                    str(output),
                    "--json",
                    expected=0 if scenario == "passed" else 3,
                )
            )
            assert imported["data"]["verdict_ok"] is (scenario == "passed")
            inspected = json.loads(
                run(
                    str(binary),
                    "instrument",
                    "inspect",
                    str(output),
                    "--sha256",
                    imported["data"]["output"]["sha256"],
                    "--json",
                )
            )
            assert inspected["ok"] and inspected["data"]["verdict_ok"] is (scenario == "passed")
    print(
        json.dumps(
            {
                "ok": True,
                "version": version,
                "module": str(module),
                "schema_count": 9,
                "instrument_cases_verified": 4,
                "hardware_access": False,
            }
        )
    )


if __name__ == "__main__":
    main()
