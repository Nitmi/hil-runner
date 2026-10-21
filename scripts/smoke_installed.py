"""Check an installed wheel from an isolated Python, using synthetic inputs only."""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import os
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

        def run(*args):
            result = subprocess.run(args, cwd=work, capture_output=True, check=True, timeout=10)
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
    print(
        json.dumps(
            {
                "ok": True,
                "version": version,
                "module": str(module),
                "schema_count": 7,
                "hardware_access": False,
            }
        )
    )


if __name__ == "__main__":
    main()
