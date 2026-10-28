"""Explicit thermal evidence import and native canonical JUnit verification."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

from . import __version__
from . import thermal_protocol as protocol
from .common import digest
from .instrument import destination, portable, snapshot
from .simulation import local, read

FLAGS = protocol.FLAGS
canonical = protocol.canonical


def junit_bytes(report, sha):
    counts = dict(
        tests=len(report["checks"]),
        failures=report["summary"]["failed"],
        errors=report["summary"]["invalid_evidence"],
        skipped=0,
    )
    suite = ET.Element(
        "testsuite", name="lab-instruments.thermal", **{k: str(v) for k, v in counts.items()}
    )
    props = ET.SubElement(suite, "properties")
    values = {
        **protocol.NATIVE_FLAGS,
        "time_basis": protocol.TIME,
        "source_status": report["source"]["source_status"],
        "evidence_origin": report["source"]["evidence_origin"],
        "apparent_surface_temperature_only": True,
        "producer_runner_version": report["runner_version"],
        "verifier_version": "0.11.0",
        **{k + "_sha256": report[k]["sha256"] for k in ("spec", "capture")},
        "report_sha256": sha,
    }
    for name, value in sorted(values.items()):
        ET.SubElement(
            props, "property", name=name, value=str(value).lower() if type(value) is bool else value
        )
    for check in report["checks"]:
        case = ET.SubElement(
            suite, "testcase", name=check["id"], classname="lab_instruments.thermal"
        )
        if not check["ok"]:
            ET.SubElement(
                case,
                "error" if check["status"] == "invalid_evidence" else "failure",
                message=check["reason"] or check["status"],
            ).text = canonical(check).decode("ascii")
    return ET.tostring(suite, encoding="utf-8", xml_declaration=True) + b"\n"


def build(manifest, blobs, sources, version):
    value = protocol.project(manifest, blobs, sources, version)
    report = protocol.decode(protocol.unpack(blobs["report"], protocol.LIMITS["report"]))
    protocol.require(
        protocol.unpack(blobs["junit"], protocol.LIMITS["junit"])
        == junit_bytes(report, blobs["report"]["sha256"]),
        "native thermal JUnit bytes differ",
        "EVIDENCE_MISMATCH",
    )
    return value


def load(path, sha):
    raw, ref = read(path, protocol.MAX_BUNDLE, sha)
    value = protocol.decode(raw)
    expected = build(
        value["import_spec"], value["inputs"], value["source_files"], value["producer_version"]
    )
    protocol.same(value, expected, "thermal bundle differs from embedded evidence")
    return value, dict(path=ref["path"], sha256=ref["sha256"], size_bytes=ref["bytes"])


def import_evidence(path, sha, output):
    output = destination(output)
    raw, ref = read(path, protocol.MAX_MANIFEST, sha)
    manifest = protocol.decode(raw)
    protocol.validate_manifest(manifest)
    base = Path(ref["path"]).parent
    capture_path = local(portable(base, manifest["inputs"]["capture"]["path"]))
    protocol.require(
        not output.is_relative_to(capture_path.parent),
        "bundle output must be outside the source capture directory",
    )
    identity = Path(ref["path"]).stat()
    paths = {os.path.normcase(ref["path"]).casefold()}
    identities = {(identity.st_dev, identity.st_ino)}
    source_size = 0

    def select(item, maximum, *, source=False):
        nonlocal source_size
        target = local(portable(base, item["path"]))
        info = target.stat()
        key, identity = os.path.normcase(str(target)).casefold(), (info.st_dev, info.st_ino)
        protocol.require(
            key not in paths and identity not in identities, "duplicate selected file/path"
        )
        paths.add(key)
        identities.add(identity)
        if source:
            maximum = min(maximum, protocol.MAX_SOURCES - source_size)
            protocol.require(maximum >= 0, "thermal source budget exceeded", "LIMIT_EXCEEDED")
        data, bound = read(target, maximum, item["sha256"])
        if source:
            source_size += len(data)
        return snapshot(data, bound)

    # Capture and all its explicitly named artifacts share one 16 MiB source budget.
    blobs = {
        "capture": select(manifest["inputs"]["capture"], protocol.LIMITS["capture"], source=True)
    }
    for role, maximum in protocol.LIMITS.items():
        if role != "capture":
            blobs[role] = select(manifest["inputs"][role], maximum)
    sources = {
        item["name"]: select(item, 1048576, source=True) for item in manifest["source_files"]
    }
    value = build(snapshot(raw, ref), blobs, sources, __version__)
    encoded = canonical(value)
    with output.open("xb") as stream:
        stream.write(encoded)
    return value, dict(path=str(output), sha256=digest(encoded), size_bytes=len(encoded))


def summary(value, ref):
    return dict(
        input=ref,
        verdict_ok=value["ok"],
        source_files_rechecked=False,
        **{
            k: value[k]
            for k in (
                "status",
                "summary",
                "source",
                "checks",
                "native_exit_code",
                "native_recomputation_recorded",
                "validation_kind",
                "junit",
            )
        },
        **FLAGS,
    )
