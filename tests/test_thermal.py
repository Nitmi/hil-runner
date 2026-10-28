from __future__ import annotations

import base64
import copy
import json
import socket
import subprocess
from pathlib import Path

import jsonschema
import pytest

from hil_runner import thermal
from hil_runner import thermal_protocol as protocol
from hil_runner.cli import main
from hil_runner.common import digest

from .thermal_fixture import CASES, extract


def change_blob(blob, value):
    raw = protocol.canonical(value)
    blob.update(sha256=digest(raw), size_bytes=len(raw), raw_base64=base64.b64encode(raw).decode())


@pytest.mark.parametrize("scenario", CASES)
def test_native_fixtures_bind_all_bytes_and_keep_verdict(tmp_path, scenario, monkeypatch):
    path = extract(tmp_path, scenario)

    def forbidden(*a, **kw):
        pytest.fail("offline import cannot execute or access a device")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    original, reads = thermal.read, []

    def once(path, *a, **kw):
        reads.append(str(path))
        return original(path, *a, **kw)

    monkeypatch.setattr(thermal, "read", once)
    value, ref = thermal.import_evidence(path, digest(path.read_bytes()), tmp_path / "bundle.json")
    assert len(reads) == len(set(reads))
    assert value["ok"] is (scenario == "passed")
    assert value["native_exit_code"] == (0 if scenario == "passed" else 3)
    assert value["native_recomputation_recorded"] and all(value[k] is False for k in thermal.FLAGS)
    assert value["source"]["evidence_origin"] == "test_double"
    if scenario == "cleanup-unknown":
        assert value["source"]["source_cleanup"]["native"]["cleanup_complete"] is False
        assert value["checks"][0]["frames"] == []
    reads.clear()
    inspected, _ = thermal.load(tmp_path / "bundle.json", ref["sha256"])
    assert len(reads) == 1 and inspected == value
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    jsonschema.validate(
        value, json.loads((schema_root / "thermal-report.schema.json").read_bytes())
    )
    jsonschema.validate(
        json.loads(path.read_bytes()),
        json.loads((schema_root / "thermal-spec.schema.json").read_bytes()),
    )


@pytest.mark.parametrize(
    "mode",
    ["verdict", "source", "checks", "claim", "raw", "missing", "xml", "exit", "native", "mask"],
)
def test_rehashed_edits_are_rejected(tmp_path, mode):
    path = extract(tmp_path)
    bundle, ref = thermal.import_evidence(
        path, digest(path.read_bytes()), tmp_path / "original.json"
    )
    if mode == "verdict":
        bundle["ok"] = False
    if mode == "source":
        bundle["source"]["source_cleanup"]["native"]["cleanup_complete"] = False
    if mode == "checks":
        bundle["checks"][0]["frames"][0]["raw_roi_span"]["first_byte"] += 2
    if mode == "claim":
        bundle["calibration_verified"] = True
    if mode == "raw":
        blob = bundle["source_files"]["native/frame-0000.y16"]
        blob["raw_base64"] = "AA=="
    if mode == "missing":
        bundle["source_files"].pop("native/warmup.y16")
    if mode == "xml":
        blob = bundle["inputs"]["junit"]
        raw = base64.b64decode(blob["raw_base64"]) + b" "
        blob.update(
            sha256=digest(raw), size_bytes=len(raw), raw_base64=base64.b64encode(raw).decode()
        )
    if mode == "exit":
        bundle["native_exit_code"] = 3
    if mode == "native":
        blob = bundle["inputs"]["native_result"]
        native = protocol.decode(protocol.unpack(blob, protocol.LIMITS["native_result"]))
        native["data"]["verification"]["verifier_version"] = "0.10.0"
        change_blob(blob, native)
    if mode == "mask":
        bundle["checks"][0]["frames"][0]["roi"]["valid_mask_sha256"] = "0" * 64
    target = tmp_path / "tampered.json"
    target.write_bytes(protocol.canonical(bundle))
    with pytest.raises((ValueError, KeyError)):
        thermal.load(target, digest(target.read_bytes()))


@pytest.mark.parametrize(
    "mode", ["duplicate", "traversal", "reserved", "missing", "unknown", "alias"]
)
def test_manifest_and_exact_selection_rejected_before_output(tmp_path, mode):
    path = extract(tmp_path)
    value = json.loads(path.read_bytes())
    if mode == "duplicate":
        value["source_files"].append(copy.deepcopy(value["source_files"][0]))
    if mode == "traversal":
        value["inputs"]["report"]["path"] = "../outside.json"
    if mode == "reserved":
        value["inputs"]["report"]["path"] = "CON.txt"
    if mode == "missing":
        value["source_files"].pop()
    if mode == "unknown":
        value["schema_version"] = "embedded-hil-runner.load-spec.v1"
    if mode == "alias":
        value["inputs"]["report"]["path"] = value["inputs"]["spec"]["path"]
    path.write_bytes(protocol.canonical(value))
    output = tmp_path / "output.json"
    with pytest.raises((ValueError, KeyError)):
        thermal.import_evidence(path, digest(path.read_bytes()), output)
    assert not output.exists()


def test_originals_may_move_after_self_contained_import(tmp_path):
    path = extract(tmp_path)
    output = tmp_path / "bundle.json"
    _, ref = thermal.import_evidence(path, digest(path.read_bytes()), output)
    path.parent.rename(tmp_path / "unavailable-originals")
    assert thermal.load(output, ref["sha256"])[0]["ok"]


def test_exclusive_output_and_cli_verdict(tmp_path, capsys):
    path = extract(tmp_path, "mixed")
    output = tmp_path / "bundle.json"
    args = [
        "thermal",
        "import",
        str(path),
        "--sha256",
        digest(path.read_bytes()),
        "--output",
        str(output),
        "--json",
    ]
    assert main(args) == 3
    result = json.loads(capsys.readouterr().out)
    assert not result["data"]["verdict_ok"] and result["data"]["summary"]["passed"] == 1
    assert (
        main(["thermal", "inspect", str(output), "--sha256", digest(output.read_bytes()), "--json"])
        == 0
    )
    assert not json.loads(capsys.readouterr().out)["data"]["verdict_ok"]
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["errors"]


def test_protocol_bounds_types_and_roundoff_not_assertion_tolerance():
    with pytest.raises(ValueError):
        protocol.number(10**10000)
    with pytest.raises(ValueError):
        protocol.decode(b'{"x":1,"x":2}')
    with pytest.raises(ValueError):
        protocol.integer(True, 0, 1)
    with pytest.raises(ValueError):
        protocol.source_name("native/../plan.json")


def test_output_cannot_pollute_source_capture_inventory(tmp_path):
    path = extract(tmp_path)
    output = path.parent / "capture/new-bundle.json"
    with pytest.raises(ValueError, match="outside"):
        thermal.import_evidence(path, digest(path.read_bytes()), output)
    assert not output.exists()


@pytest.mark.parametrize("mode", ["geometry", "assertion", "qualification"])
def test_coherently_rebound_native_records_still_need_semantic_consistency(tmp_path, mode):
    path = extract(tmp_path)
    bundle, _ = thermal.import_evidence(path, digest(path.read_bytes()), tmp_path / "bundle.json")
    blobs = bundle["inputs"]
    report = protocol.decode(protocol.unpack(blobs["report"], protocol.LIMITS["report"]))
    if mode == "geometry":
        report["checks"][0]["frames"][0]["raw_roi_span"]["first_byte"] += 2
    elif mode == "assertion":
        report["checks"][0]["assertions"][0]["actual"][0] += 1
    else:
        report["calibration_verified"] = True
    change_blob(blobs["report"], report)
    native = protocol.decode(
        protocol.unpack(blobs["native_result"], protocol.LIMITS["native_result"])
    )
    native["data"]["verification"]["report"].update(
        sha256=blobs["report"]["sha256"], size_bytes=blobs["report"]["size_bytes"]
    )
    xml = thermal.junit_bytes(report, blobs["report"]["sha256"])
    blobs["junit"].update(
        sha256=digest(xml), size_bytes=len(xml), raw_base64=base64.b64encode(xml).decode()
    )
    native["data"]["output"].update(sha256=digest(xml), size_bytes=len(xml))
    change_blob(blobs["native_result"], native)
    manifest = protocol.decode(protocol.unpack(bundle["import_spec"], protocol.MAX_MANIFEST))
    for role in blobs:
        manifest["inputs"][role]["sha256"] = blobs[role]["sha256"]
    change_blob(bundle["import_spec"], manifest)
    with pytest.raises(ValueError):
        thermal.build(bundle["import_spec"], blobs, bundle["source_files"], "0.12.0")


@pytest.mark.parametrize(
    "missing",
    [
        "thermal.py",
        "thermal_protocol.py",
        "schemas/thermal-spec.schema.json",
        "schemas/thermal-report.schema.json",
    ],
)
def test_release_requires_thermal_payloads(tmp_path, missing):
    from scripts import release

    from .test_release import REVISION, archives

    archives(
        tmp_path, version="0.12.0", wheel_mutation=lambda wheel: wheel.pop("hil_runner/" + missing)
    )
    with pytest.raises(ValueError, match="Missing thermal runtime"):
        release.create_manifest(tmp_path, "0.12.0", REVISION)
