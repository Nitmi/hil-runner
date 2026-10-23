from __future__ import annotations

import base64
import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from hil_runner import instrument
from hil_runner.cli import main
from hil_runner.common import HilError, digest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/instrument"


def case(tmp_path, scenario="passed"):
    root = tmp_path / "inputs"
    shutil.copytree(EXAMPLES / scenario, root)
    path = root / "import.json"
    return path, digest(path.read_bytes()), tmp_path / "bundle.json"


def write(path, value):
    path.write_bytes(instrument.canonical(value))
    return digest(path.read_bytes())


@pytest.mark.parametrize(
    "scenario,code,failures,errors",
    [("passed", 0, 0, 0), ("failed", 3, 1, 0), ("invalid", 3, 0, 4), ("mixed", 3, 1, 1)],
)
def test_import_preserves_native_verdict_and_junit(
    tmp_path, capsys, scenario, code, failures, errors
):
    path, sha, output = case(tmp_path, scenario)
    command = [
        "instrument",
        "import",
        str(path),
        "--sha256",
        sha,
        "--output",
        str(output),
        "--json",
    ]
    assert main(command) == code
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is (code == 0)
    assert result["data"]["verdict_ok"] is (code == 0)
    assert result["data"]["junit"] == {
        "tests": 4,
        "failures": failures,
        "errors": errors,
        "skipped": 0,
    }
    assert result["data"]["native_recomputation_recorded"]
    assert all(result[k] is False for k in instrument.FLAGS)
    assert (
        main(["instrument", "inspect", str(output), "--sha256", digest(output.read_bytes())]) == 0
    )
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["ok"] and inspected["data"]["verdict_ok"] is (code == 0)
    bundle = json.loads(output.read_bytes())
    assert bundle["evidence_origin"] == "test_double"
    assert (
        base64.b64decode(bundle["inputs"]["junit"]["raw_base64"])
        == (path.parent / "junit.xml").read_bytes()
    )


def test_inputs_read_once_no_device_process_or_saved_path_access(tmp_path, monkeypatch):
    path, sha, output = case(tmp_path)
    actual_read = instrument.read
    calls = []

    def once(path, *args):
        assert path not in calls
        calls.append(path)
        raw, ref = actual_read(path, *args)
        path.write_bytes(b"changed after snapshot")
        return raw, ref

    def forbidden(*args, **kwargs):
        raise AssertionError("offline import started network/process")

    monkeypatch.setattr(instrument, "read", once)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    bundle, _ = instrument.import_evidence(path, sha, output)
    assert bundle["ok"] and len(calls) == 6
    # Inspection consumes only the bundle, even after removing original inputs.
    monkeypatch.setattr(instrument, "read", actual_read)
    shutil.rmtree(path.parent)
    assert instrument.load(output, digest(output.read_bytes()))[0] == bundle


@pytest.mark.parametrize("role", list(instrument.LIMITS))
def test_changed_bound_input_is_rejected(tmp_path, role):
    path, sha, output = case(tmp_path)
    spec = json.loads(path.read_bytes())
    source = path.parent / spec["inputs"][role]["path"]
    if role == "native_result":
        response = json.loads(source.read_bytes())
        response["data"]["verification"]["ok"] = False
        write(source, response)
    else:
        source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(HilError):
        instrument.import_evidence(path, sha, output)
    assert not output.exists()


@pytest.mark.parametrize("role", list(instrument.LIMITS))
def test_rehashed_different_original_does_not_match_native_verification(tmp_path, role):
    path, _, output = case(tmp_path)
    spec = json.loads(path.read_bytes())
    source = path.parent / spec["inputs"][role]["path"]
    if role == "native_result":
        response = json.loads(source.read_bytes())
        response["data"]["verification"]["ok"] = False
        write(source, response)
    else:
        source.write_bytes(source.read_bytes() + b" ")
    spec["inputs"][role]["sha256"] = digest(source.read_bytes())
    sha = write(path, spec)
    with pytest.raises((HilError, ValueError)):
        instrument.import_evidence(path, sha, output)
    assert not output.exists()


def test_explicitly_reselected_native_response_formatting_preserves_bytes(tmp_path):
    path, _, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    response = path.parent / "native_result.json"
    response.write_bytes(response.read_bytes() + b" ")
    manifest["inputs"]["native_result"]["sha256"] = digest(response.read_bytes())
    value, _ = instrument.import_evidence(path, write(path, manifest), output)
    assert value["ok"]
    assert base64.b64decode(value["inputs"]["native_result"]["raw_base64"]) == response.read_bytes()


@pytest.mark.parametrize(
    "value",
    [
        "../outside.json",
        "/absolute.json",
        "C:/absolute.json",
        "a\\b.json",
        "CON.json",
        "a//b",
        "a/./b",
        "trailing.",
    ],
)
def test_unsafe_manifest_paths_stop_before_input_read(tmp_path, value):
    path, _, output = case(tmp_path)
    spec = json.loads(path.read_bytes())
    spec["inputs"]["report"]["path"] = value
    sha = write(path, spec)
    with pytest.raises(HilError):
        instrument.import_evidence(path, sha, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("ok", 1),
        ("status", "failed"),
        ("producer_version", "99.0.0"),
        ("native_exit_code", True),
        ("native_recomputation_recorded", False),
        ("validation_kind", "fully_authenticated"),
        *[(key, True) for key in instrument.FLAGS],
    ],
)
def test_rehashed_bundle_cannot_upgrade_or_change_declarations(tmp_path, field, value):
    path, sha, output = case(tmp_path)
    instrument.import_evidence(path, sha, output)
    bundle = json.loads(output.read_bytes())
    bundle[field] = value
    changed = write(output, bundle)
    with pytest.raises(HilError):
        instrument.load(output, changed)


def test_rehashed_native_summary_and_assertions_do_not_launder_failure(tmp_path):
    path, _, output = case(tmp_path, "failed")
    spec = json.loads(path.read_bytes())
    source = path.parent / "report.json"
    report = json.loads(source.read_bytes())
    report["ok"] = True
    report["checks"][0]["ok"] = True
    report["checks"][0]["status"] = "passed"
    spec["inputs"]["report"]["sha256"] = write(source, report)
    with pytest.raises(HilError):
        instrument.import_evidence(path, write(path, spec), output)
    assert not output.exists()


def test_existing_output_preflight_precedes_reads(tmp_path, monkeypatch):
    path, sha, output = case(tmp_path)
    output.write_bytes(b"preserve")

    def forbidden(*args):
        raise AssertionError("read before output preflight")

    monkeypatch.setattr(instrument, "read", forbidden)
    with pytest.raises(HilError) as error:
        instrument.import_evidence(path, sha, output)
    assert error.value.code == "OUTPUT_EXISTS" and output.read_bytes() == b"preserve"


def test_manifest_and_snapshot_limits_are_bounded(tmp_path):
    path, _, output = case(tmp_path)
    path.write_bytes(b" " * 16385)
    with pytest.raises(HilError) as error:
        instrument.import_evidence(path, digest(path.read_bytes()), output)
    assert error.value.code == "LIMIT_EXCEEDED"
    with pytest.raises(HilError):
        instrument.unpack(
            {"path": "label", "sha256": "0" * 64, "size_bytes": True, "raw_base64": "AA=="}, 1048576
        )


@pytest.mark.parametrize("code", [True, 1, 2, -1, 0.0])
def test_incomplete_or_bad_exit_codes_are_rejected(tmp_path, code):
    path, _, output = case(tmp_path)
    spec = json.loads(path.read_bytes())
    spec["native_exit_code"] = code
    with pytest.raises(HilError):
        instrument.import_evidence(path, write(path, spec), output)


def test_schemas_validate_manifest_and_self_contained_artifact(tmp_path):
    import jsonschema

    path, sha, output = case(tmp_path, "mixed")
    value, _ = instrument.import_evidence(path, sha, output)
    root = Path(__file__).resolve().parents[1] / "schemas"
    for name, document in (
        ("instrument-spec", json.loads(path.read_bytes())),
        ("instrument-report", value),
    ):
        schema = json.loads((root / (name + ".schema.json")).read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(document, schema)
