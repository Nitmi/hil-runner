"""Explicit saved-load import and canonical native XML verification, no execution."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

from . import __version__
from . import load_protocol as protocol
from .common import digest
from .instrument import destination, portable, snapshot
from .simulation import local, read

FLAGS = protocol.FLAGS
canonical = protocol.canonical


def junit_bytes(report, sha, verifier="0.10.0"):
    counts = dict(
        tests=len(report["checks"]),
        failures=report["summary"]["failed"],
        errors=report["summary"]["invalid_evidence"],
        skipped=0,
    )
    suite = ET.Element(
        "testsuite", name="lab-instruments.load", **{k: str(v) for k, v in counts.items()}
    )
    props = ET.SubElement(suite, "properties")
    for name, value in sorted(
        {
            **protocol.NATIVE_FLAGS,
            "report_sha256": sha,
            "capture_sha256": report["capture"]["sha256"],
            "spec_sha256": report["spec"]["sha256"],
            "producer_runner_version": report["runner_version"],
            "verifier_version": verifier,
            "time_semantics": protocol.TIME,
            "source_status": report["source"]["source_status"],
            "evidence_origin": report["source"]["evidence_origin"],
        }.items()
    ):
        ET.SubElement(
            props, "property", name=name, value=str(value).lower() if type(value) is bool else value
        )
    for check in report["checks"]:
        case = ET.SubElement(suite, "testcase", name=check["id"], classname="lab_instruments.load")
        if not check["ok"]:
            ET.SubElement(
                case,
                "error" if check["status"] == "invalid_evidence" else "failure",
                message=check["status"],
            ).text = canonical(check).decode("ascii")
    return ET.tostring(suite, encoding="utf-8", xml_declaration=True) + b"\n"


def build(manifest_blob, blobs, version):
    value = protocol.project(manifest_blob, blobs, version)
    report = protocol.decode(protocol.unpack(blobs["report"], protocol.LIMITS["report"]))
    xml = protocol.unpack(blobs["junit"], protocol.LIMITS["junit"])
    protocol.require(
        xml
        == junit_bytes(
            report,
            blobs["report"]["sha256"],
            protocol.decode(
                protocol.unpack(blobs["native_result"], protocol.LIMITS["native_result"])
            )["data"]["verification"]["verifier_version"],
        ),
        "native load JUnit bytes differ",
        "EVIDENCE_MISMATCH",
    )
    return value


def load(path, sha):
    raw, ref = read(path, protocol.MAX_BUNDLE, sha)
    value = protocol.decode(raw)
    expected = build(value["import_spec"], value["inputs"], value["producer_version"])
    protocol.same(value, expected, "load bundle differs from embedded evidence")
    return value, dict(path=ref["path"], sha256=ref["sha256"], size_bytes=ref["bytes"])


def import_evidence(path, sha, output):
    output = destination(output)
    raw, ref = read(path, protocol.MAX_MANIFEST, sha)
    manifest = protocol.decode(raw)
    protocol.validate_manifest(manifest)
    paths = {os.path.normcase(ref["path"]).casefold()}
    info = Path(ref["path"]).stat()
    identities = {(info.st_dev, info.st_ino)}
    blobs = {}
    for role, maximum in protocol.LIMITS.items():
        item = manifest["inputs"][role]
        target = local(portable(Path(ref["path"]).parent, item["path"]))
        key = os.path.normcase(str(target)).casefold()
        info = target.stat()
        identity = (info.st_dev, info.st_ino)
        protocol.require(
            key not in paths and identity not in identities, "duplicate selected file/path"
        )
        paths.add(key)
        identities.add(identity)
        payload, bound = read(target, maximum, item["sha256"])
        blobs[role] = snapshot(payload, bound)
    value = build(snapshot(raw, ref), blobs, __version__)
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
