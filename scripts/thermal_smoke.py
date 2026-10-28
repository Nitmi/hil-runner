"""Installed HIL thermal CLI checks on explicit synthetic saved fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def verify(run, binary, root):
    archive = Path(__file__).resolve().parents[1] / "examples/thermal/fixtures.zip"
    scenarios = []
    with ZipFile(archive) as z:
        for name in sorted({i.filename.split("/")[0] for i in z.infolist()}):
            for info in (i for i in z.infolist() if i.filename.startswith(name + "/")):
                parts = PurePosixPath(info.filename).parts
                assert all(p not in ("", ".", "..") for p in parts) and info.file_size <= 1048576
                target = root.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))
            manifest, output = root / name / "import.json", root / (name + "-bundle.json")
            passed = name == "passed"
            imported = json.loads(
                run(
                    str(binary),
                    "thermal",
                    "import",
                    str(manifest),
                    "--sha256",
                    hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    "--output",
                    str(output),
                    "--json",
                    expected=0 if passed else 3,
                )
            )
            inspected = json.loads(
                run(
                    str(binary),
                    "thermal",
                    "inspect",
                    str(output),
                    "--sha256",
                    imported["data"]["output"]["sha256"],
                    "--json",
                )
            )
            assert inspected["ok"] and inspected["data"]["verdict_ok"] is passed
            assert inspected["data"]["source"]["evidence_origin"] == "test_double"
            assert inspected["native_temperature_conversion_performed"] is False
            scenarios.append(name)
    assert len(scenarios) == 11
    return scenarios
