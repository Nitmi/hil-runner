"""Native-generated, explicitly synthetic waveform records; no lab dependency."""

import base64
import json
import shutil
import socket
import subprocess
from pathlib import Path

import jsonschema
import pytest

from hil_runner import waveform
from hil_runner.cli import main
from hil_runner.common import HilError, digest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/waveform"


def case(tmp_path, scenario="passed"):
    shutil.copytree(EXAMPLES / scenario, tmp_path / "inputs")
    path = tmp_path / "inputs/import.json"
    return path, digest(path.read_bytes()), tmp_path / "bundle.json"


def write(path, value):
    path.write_bytes(waveform.canonical(value))
    return digest(path.read_bytes())


@pytest.mark.parametrize(
    "scenario,failures,errors",
    [
        ("passed", 0, 0),
        ("failed", 1, 0),
        ("invalid", 0, 1),
        ("mixed", 1, 1),
        ("sds", 0, 0),
    ],
)
def test_native_verdict_full_raw_binding_and_self_contained_reload(
    tmp_path, scenario, failures, errors
):
    path, sha, output = case(tmp_path, scenario)
    value, ref = waveform.import_evidence(path, sha, output)
    assert value["junit"]["failures"] == failures and value["junit"]["errors"] == errors
    assert value["ok"] is (failures + errors == 0)
    assert value["native_recomputation_recorded"] and all(value[k] is False for k in waveform.FLAGS)
    if scenario == "sds":
        assert len(value["source_files"]) == 212
        assert any(b["size_bytes"] == 0 for b in value["source_files"].values())
        assert (
            value["checks"][0]["source_samples"]["raw"]["encoding"]
            == "s16le_left_aligned_adc_words"
        )
    shutil.rmtree(path.parent)  # Only synthetic copies created by this test.
    loaded, _ = waveform.load(output, ref["sha256"])
    assert loaded == value
    schema = json.loads((EXAMPLES.parents[1] / "schemas/waveform-report.schema.json").read_bytes())
    jsonschema.validate(value, schema)


@pytest.mark.parametrize("role", list(waveform.LIMITS))
@pytest.mark.parametrize("rehash", [False, True])
def test_changed_native_input_cannot_rebind_verification(tmp_path, role, rehash):
    path, sha, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    item = manifest["inputs"][role]
    source = path.parent / item["path"]
    if role == "native_result":
        response = json.loads(source.read_bytes())
        response["data"]["verification"]["sample_zero_utc_verified"] = True
        write(source, response)
    else:
        source.write_bytes(source.read_bytes() + b" ")
    if rehash:
        item["sha256"] = digest(source.read_bytes())
        sha = write(path, manifest)
    with pytest.raises((HilError, ValueError)):
        waveform.import_evidence(path, sha, output)
    assert not output.exists()


@pytest.mark.parametrize("name", ["../escape", "/root", "a\\b", "CON.json", "C:/bad", "a/./b"])
def test_manifest_traversal_rejected_before_read(tmp_path, name, monkeypatch):
    path, _, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    manifest["inputs"]["capture"]["path"] = name
    sha = write(path, manifest)
    calls = []
    original = waveform.read

    def only_manifest(selected, *args):
        calls.append(selected)
        return original(selected, *args)

    monkeypatch.setattr(waveform, "read", only_manifest)
    with pytest.raises(HilError):
        waveform.import_evidence(path, sha, output)
    assert len(calls) == 1


def test_single_file_reads_no_network_subprocess_or_recorded_paths(tmp_path, monkeypatch):
    path, sha, output = case(tmp_path, "sds")
    original = waveform.read
    calls = set()

    def once(selected, *args):
        assert str(selected) not in calls
        calls.add(str(selected))
        return original(selected, *args)

    def forbidden(*args, **kwargs):
        pytest.fail("offline import opened network or started executable")

    monkeypatch.setattr(waveform, "read", once)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    value, _ = waveform.import_evidence(path, sha, output)
    assert value["ok"] and len(calls) == 218


@pytest.mark.parametrize("change", ["missing", "extra", "wrong_hash", "duplicate", "alias"])
def test_sds_sources_must_be_explicit_unique_and_match_native_inventory(tmp_path, change):
    path, _, output = case(tmp_path, "sds")
    manifest = json.loads(path.read_bytes())
    files = manifest["source_files"]
    if change == "missing":
        files.pop()
    elif change == "extra":
        files.append({**files[0], "name": "wire-0999-tx.bin"})
    elif change == "wrong_hash":
        files[0]["sha256"] = "0" * 64
    elif change == "duplicate":
        files.append(files[0])
    else:
        files[0]["path"] = files[1]["path"]
    with pytest.raises((HilError, KeyError)):
        waveform.import_evidence(path, write(path, manifest), output)
    assert not output.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("ok", 1),
        ("status", "passed"),
        ("producer_version", "99.0.0"),
        ("native_exit_code", True),
        *[(key, True) for key in waveform.FLAGS],
    ],
)
def test_rehashed_bundle_projection_and_claim_changes_rejected(tmp_path, field, value):
    path, sha, output = case(tmp_path, "mixed")
    bundle, _ = waveform.import_evidence(path, sha, output)
    bundle[field] = value
    with pytest.raises(HilError):
        waveform.load(output, write(output, bundle))


def test_cli_failed_import_successful_inspect_and_existing_output(tmp_path, capsys):
    path, sha, output = case(tmp_path, "mixed")
    args = ["waveform", "import", str(path), "--sha256", sha, "--output", str(output), "--json"]
    assert main(args) == 3
    result = json.loads(capsys.readouterr().out)
    assert not result["ok"] and result["data"]["junit"]["errors"] == 1
    assert (
        main(
            ["waveform", "inspect", str(output), "--sha256", digest(output.read_bytes()), "--json"]
        )
        == 0
    )
    assert not json.loads(capsys.readouterr().out)["data"]["verdict_ok"]
    assert main(args) == 2
    assert not json.loads(capsys.readouterr().out)["ok"]


def test_source_limits_before_unpack_and_noncanonical_empty_bytes():
    with pytest.raises(HilError):
        waveform.unpack_source(
            {"path": "empty", "size_bytes": 0, "sha256": digest(b""), "raw_base64": "AA=="}
        )
    with pytest.raises(HilError):
        waveform.canonical({"large": "x" * waveform.MAX_BUNDLE})
    with pytest.raises(HilError):
        waveform.validate_manifest(
            {
                "schema_version": "embedded-hil-runner.waveform-spec.v1",
                "native_exit_code": 0,
                "inputs": {},
                "source_files": [None] * 1615,
            }
        )


def test_metric_contradiction_detected_even_before_native_verification(tmp_path):
    path, sha, output = case(tmp_path)
    bundle, _ = waveform.import_evidence(path, sha, output)
    report = json.loads(base64.b64decode(bundle["inputs"]["report"]["raw_base64"]))
    report["checks"][0]["metrics"]["mean_v"] = 999.0
    contract = json.loads(base64.b64decode(bundle["inputs"]["spec"]["raw_base64"]))
    with pytest.raises(HilError, match="assertion"):
        waveform.validate_report(report, contract, bundle["inputs"], {}, {})


def test_junit_must_be_canonical_native_bytes_even_with_rebound_response(tmp_path):
    path, _, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    xml = path.parent / "junit.xml"
    xml.write_bytes(xml.read_bytes() + b" ")
    response_path = path.parent / "native-result.json"
    response = json.loads(response_path.read_bytes())
    response["data"]["output"].update(
        sha256=digest(xml.read_bytes()), size_bytes=xml.stat().st_size
    )
    write(response_path, response)
    for role in ("native_result", "junit"):
        manifest["inputs"][role]["sha256"] = digest(
            (path.parent / manifest["inputs"][role]["path"]).read_bytes()
        )
    with pytest.raises(HilError, match="JUnit bytes"):
        waveform.import_evidence(path, write(path, manifest), output)


def test_same_file_hardlink_is_rejected(tmp_path):
    path, _, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    alias = path.parent / "alias.json"
    alias.hardlink_to(path.parent / "spec.json")
    manifest["inputs"]["capture"] = dict(path="alias.json", sha256=digest(alias.read_bytes()))
    with pytest.raises(HilError, match="same waveform input file"):
        waveform.import_evidence(path, write(path, manifest), output)


def test_reload_validates_duplicate_paths_inside_rehashed_embedded_manifest(tmp_path):
    path, sha, output = case(tmp_path, "sds")
    bundle, _ = waveform.import_evidence(path, sha, output)
    manifest = json.loads(base64.b64decode(bundle["import_spec"]["raw_base64"]))
    manifest["source_files"][0]["path"] = manifest["source_files"][1]["path"]
    raw = waveform.canonical(manifest)
    bundle["import_spec"].update(
        raw_base64=base64.b64encode(raw).decode(), sha256=digest(raw), size_bytes=len(raw)
    )
    with pytest.raises(HilError, match="duplicate waveform manifest path"):
        waveform.load(output, write(output, bundle))
