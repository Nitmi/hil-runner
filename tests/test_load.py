"""Actual lab-produced saved load cases; no lab runtime dependency."""

import base64
import json
import shutil
import socket
import subprocess
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

from hil_runner import load
from hil_runner import load_protocol as protocol
from hil_runner.cli import main
from hil_runner.common import HilError, digest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/load"


def case(root, scenario="passed"):
    folder = root / "inputs"
    shutil.copytree(EXAMPLES / scenario, folder)
    return folder / "import.json", root / "bundle.json"


def write(path, value):
    path.write_bytes(protocol.canonical(value))
    return digest(path.read_bytes())


def rebind(path, role):
    manifest = json.loads(path.read_bytes())
    manifest["inputs"][role]["sha256"] = digest(
        (path.parent / manifest["inputs"][role]["path"]).read_bytes()
    )
    return write(path, manifest)


@pytest.mark.parametrize(
    "scenario,failures,errors",
    [
        ("passed", 0, 0),
        ("failed", 1, 0),
        ("invalid", 0, 1),
        ("mixed", 1, 0),
        ("cleanup", 0, 1),
        ("timeout", 0, 1),
    ],
)
def test_actual_native_verdict_raw_bytes_schemas_and_self_containment(
    tmp_path, scenario, failures, errors, monkeypatch
):
    path, output = case(tmp_path, scenario)

    def forbidden(*a, **kw):
        raise AssertionError("no network/process")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    calls = Counter()
    original = load.read

    def counted(p, *args, **kwargs):
        calls[str(p)] += 1
        return original(p, *args, **kwargs)

    monkeypatch.setattr(load, "read", counted)
    bundle, ref = load.import_evidence(path, digest(path.read_bytes()), output)
    assert len(calls) == 8 and all(n == 1 for n in calls.values())
    assert (
        bundle["ok"] is (scenario == "passed")
        and bundle["junit"]["failures"] == failures
        and bundle["junit"]["errors"] == errors
    )
    assert all(bundle[k] is False for k in protocol.FLAGS)
    for blob in bundle["inputs"].values():
        assert (
            base64.b64decode(blob["raw_base64"], validate=True) == Path(blob["path"]).read_bytes()
        )
    schema = json.loads((EXAMPLES.parents[1] / "schemas/load-report.schema.json").read_bytes())
    jsonschema.validate(bundle, schema)
    jsonschema.validate(
        json.loads(path.read_bytes()),
        json.loads((EXAMPLES.parents[1] / "schemas/load-spec.schema.json").read_bytes()),
    )
    path.parent.rename(tmp_path / "originals-unavailable")
    loaded, _ = load.load(output, ref["sha256"])
    assert loaded == bundle
    if scenario in ("cleanup", "timeout"):
        assert not loaded["source"]["recorded_cleanup"]["input_off_confirmed"]
        assert loaded["checks"][0]["reason"] == "source_failed"
        assert loaded["source"]["recorded_cleanup"]["instrument_state"] == "unknown"


@pytest.mark.parametrize("role", list(protocol.LIMITS))
@pytest.mark.parametrize("rehash", [False, True])
def test_altered_primary_input_is_rejected_even_with_manifest_rehash(tmp_path, role, rehash):
    path, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    source = path.parent / manifest["inputs"][role]["path"]
    if role == "native_result":
        value = json.loads(source.read_bytes())
        value["data"]["verification"]["calibration_verified"] = True
        write(source, value)
    else:
        source.write_bytes(source.read_bytes() + b" ")
    sha = rebind(path, role) if rehash else digest(path.read_bytes())
    with pytest.raises((ValueError, HilError)):
        load.import_evidence(path, sha, output)
    assert not output.exists()


def rewrite_report(path, edit):
    manifest = json.loads(path.read_bytes())
    paths = {r: path.parent / item["path"] for r, item in manifest["inputs"].items()}
    report = json.loads(paths["report"].read_bytes())
    edit(report)
    write(paths["report"], report)
    sha = digest(paths["report"].read_bytes())
    paths["junit"].write_bytes(load.junit_bytes(report, sha))
    response = json.loads(paths["native_result"].read_bytes())
    response["data"]["verification"]["report"].update(
        sha256=sha, size_bytes=paths["report"].stat().st_size
    )
    response["data"]["output"].update(
        sha256=digest(paths["junit"].read_bytes()), size_bytes=paths["junit"].stat().st_size
    )
    write(paths["native_result"], response)
    for r in ("report", "junit", "native_result"):
        manifest["inputs"][r]["sha256"] = digest(paths[r].read_bytes())
    return write(path, manifest)


@pytest.mark.parametrize(
    "mode", ["metric", "raw-span", "tx", "transaction", "source", "comparison"]
)
def test_coherent_rehashes_cannot_hide_recorded_value_or_raw_provenance_drift(tmp_path, mode):
    path, output = case(tmp_path)

    def edit(report):
        check = report["checks"][0]
        if mode == "metric":
            check["metrics"]["mean_voltage_v"] += 0.1
        elif mode == "raw-span":
            check["measurements"][0]["raw_queries"][0]["transcript_span"]["start"] += 1
        elif mode == "tx":
            check["measurements"][0]["raw_queries"][0]["tx_sha256"] = "0" * 64
        elif mode == "transaction":
            check["measurements"][0]["raw_queries"][0]["transaction"] += 1
        elif mode == "source":
            report["source"]["recorded_cleanup"]["off_attempted"] = False
        else:
            check["assertions"][0]["actual"] = 0

    sha = rewrite_report(path, edit)
    with pytest.raises(ValueError):
        load.import_evidence(path, sha, output)
    assert not output.exists()


def test_failed_source_cannot_be_promoted_by_passing_subset(tmp_path):
    path, output = case(tmp_path, "cleanup")
    sha = rewrite_report(
        path,
        lambda r: r["checks"][0].update(
            status="passed", ok=True, metrics={}, assertions=[], measurements=[]
        ),
    )
    with pytest.raises(ValueError):
        load.import_evidence(path, sha, output)


@pytest.mark.parametrize(
    "mode",
    [
        "duplicate",
        "case",
        "traverse",
        "missing",
        "bool-exit",
        "wrong-exit",
        "unknown-schema",
        "unknown-role",
    ],
)
def test_manifest_validation_and_no_implicit_file_search(tmp_path, mode):
    path, output = case(tmp_path)
    manifest = json.loads(path.read_bytes())
    if mode == "duplicate":
        manifest["inputs"]["plan"] = manifest["inputs"]["spec"]
    elif mode == "case":
        manifest["inputs"]["plan"]["path"] = manifest["inputs"]["spec"]["path"].upper()
    elif mode == "traverse":
        manifest["inputs"]["plan"]["path"] = "../plan.json"
    elif mode == "missing":
        (path.parent / "plan.json").unlink()
    elif mode == "bool-exit":
        manifest["native_exit_code"] = False
    elif mode == "wrong-exit":
        manifest["native_exit_code"] = 3
    elif mode == "unknown-schema":
        manifest["schema_version"] = "unknown"
    else:
        manifest["inputs"]["argv"] = {"path": "x", "sha256": "0" * 64}
    with pytest.raises((ValueError, HilError, OSError)):
        load.import_evidence(path, write(path, manifest), output)
    assert not output.exists()


def test_native_response_formatting_can_be_explicitly_rebound(tmp_path):
    path, output = case(tmp_path)
    response = path.parent / "native_result.json"
    response.write_text(json.dumps(json.loads(response.read_bytes()), indent=4), encoding="utf-8")
    bundle, _ = load.import_evidence(path, rebind(path, "native_result"), output)
    assert bundle["ok"]


def test_existing_output_rejected_before_any_input_reads(tmp_path, monkeypatch):
    output = tmp_path / "occupied"
    output.write_bytes(b"keep")
    monkeypatch.setattr(load, "read", lambda *a, **kw: pytest.fail("read after existing output"))
    with pytest.raises(HilError):
        load.import_evidence(tmp_path / "absent", "0" * 64, output)
    assert output.read_bytes() == b"keep"


def test_cli_failing_import_and_successful_processing_keep_original_verdict(tmp_path, capsys):
    path, output = case(tmp_path, "mixed")
    assert (
        main(
            [
                "load",
                "import",
                str(path),
                "--sha256",
                digest(path.read_bytes()),
                "--output",
                str(output),
                "--json",
            ]
        )
        == 3
    )
    response = json.loads(capsys.readouterr().out)
    assert not response["ok"] and not response["data"]["verdict_ok"]
    assert (
        main(["load", "inspect", str(output), "--sha256", digest(output.read_bytes()), "--json"])
        == 0
    )
    response = json.loads(capsys.readouterr().out)
    assert (
        response["ok"]
        and not response["data"]["verdict_ok"]
        and response["data"]["junit"]["failures"] == 1
    )


@pytest.mark.parametrize(
    "missing",
    [
        "load.py",
        "load_protocol.py",
        "schemas/load-spec.schema.json",
        "schemas/load-report.schema.json",
    ],
)
def test_release_inventory_requires_complete_load_payload(tmp_path, missing):
    from scripts import release

    from .test_release import REVISION, archives

    archives(tmp_path, version="0.11.0", wheel_mutation=lambda w: w.pop("hil_runner/" + missing))
    with pytest.raises(ValueError, match="Missing load runtime files"):
        release.create_manifest(tmp_path, "0.11.0", REVISION)


def test_complete_load_release_inventory_and_large_integer_bounds(tmp_path):
    from scripts import release

    from .test_release import REVISION, archives

    archives(tmp_path, version="0.11.0")
    release.create_manifest(tmp_path, "0.11.0", REVISION)
    assert release.verify(tmp_path, REVISION)["ok"]
    with pytest.raises(ValueError):
        protocol.number(10**400)


@pytest.mark.parametrize(
    "domain,scenario",
    [
        (d, s)
        for d, ss in (
            ("instrument", ("passed", "failed", "invalid", "mixed", "legacy")),
            ("waveform", ("passed", "failed", "invalid")),
        )
        for s in ss
    ],
)
def test_actual_lab10_digital_and_waveform_compatibility(tmp_path, domain, scenario):
    from hil_runner import instrument, waveform

    folder = tmp_path / "inputs"
    shutil.copytree(EXAMPLES.parent / (domain + "-10") / scenario, folder)
    selected = {"instrument": instrument, "waveform": waveform}[domain]
    path = folder / "import.json"
    bundle, ref = selected.import_evidence(
        path, digest(path.read_bytes()), tmp_path / "bundle.json"
    )
    assert bundle["ok"] is (scenario in ("passed", "legacy"))
    response = json.loads((folder / "native_result.json").read_bytes())
    assert response["data"]["verification"]["verifier_version"] == "0.10.0"
    assert selected.load(tmp_path / "bundle.json", ref["sha256"])[0] == bundle
