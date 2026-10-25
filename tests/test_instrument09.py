"""Actual lab 0.9 saved verification, not relabeled old native responses."""

import json
import shutil
from pathlib import Path

import pytest

from hil_runner import instrument
from hil_runner.common import HilError, digest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/instrument-09"


def case(tmp_path, scenario="passed"):
    shutil.copytree(EXAMPLES / scenario, tmp_path / "inputs")
    path = tmp_path / "inputs/import.json"
    return path, digest(path.read_bytes()), tmp_path / "bundle.json"


def write(path, value):
    path.write_bytes(instrument.canonical(value))
    return digest(path.read_bytes())


@pytest.mark.parametrize("scenario", ["passed", "failed", "invalid", "mixed", "legacy"])
def test_actual_native09_results_preserve_old_and_current_producers(tmp_path, scenario):
    path, sha, output = case(tmp_path, scenario)
    value, ref = instrument.import_evidence(path, sha, output)
    assert value["ok"] is (scenario in ("passed", "legacy"))
    response = json.loads((path.parent / "native_result.json").read_bytes())
    verified = response["data"]["verification"]
    assert verified["verifier_version"] == "0.9.0"
    assert verified["producer_runner_version"] == ("0.8.0" if scenario == "legacy" else "0.9.0")
    assert value["junit"] == response["data"]["junit"]
    assert all(value[key] is False for key in instrument.FLAGS)
    assert instrument.load(output, ref["sha256"])[0] == value


@pytest.mark.parametrize("version", ["0.8.0", "0.7.0", "99.0.0", True, 0.9, None, []])
def test_current_producer_cannot_claim_older_or_unknown_verifier(tmp_path, version):
    path, _, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    source = path.parent / "native_result.json"
    response = json.loads(source.read_bytes())
    response["data"]["verification"]["verifier_version"] = version
    manifest["inputs"]["native_result"]["sha256"] = write(source, response)
    with pytest.raises(HilError, match="producer/verifier"):
        instrument.import_evidence(path, write(path, manifest), output)
    assert not output.exists()


def test_xml_verifier_must_match_native_record_even_after_rebinding_all_file_hashes(tmp_path):
    path, _, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    xml = path.parent / "junit.xml"
    raw = xml.read_bytes()
    assert b'name="verifier_version" value="0.9.0"' in raw
    xml.write_bytes(
        raw.replace(
            b'name="verifier_version" value="0.9.0"', b'name="verifier_version" value="0.8.0"'
        )
    )
    response_path = path.parent / "native_result.json"
    response = json.loads(response_path.read_bytes())
    response["data"]["output"].update(
        sha256=digest(xml.read_bytes()), size_bytes=xml.stat().st_size
    )
    manifest["inputs"]["native_result"]["sha256"] = write(response_path, response)
    manifest["inputs"]["junit"]["sha256"] = digest(xml.read_bytes())
    with pytest.raises(HilError, match="JUnit differs"):
        instrument.import_evidence(path, write(path, manifest), output)
