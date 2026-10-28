"""Import recorded native logic verification; no device, decoder or executor."""

from __future__ import annotations

import base64
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import __version__
from .common import decode, digest
from .simulation import exact, local, read, require

PREFIX = "embedded-hil-runner.instrument-"
LIMITS = {
    "report": 1048576,
    "spec": 65536,
    "capture": 1048576,
    "native_result": 131072,
    "junit": 1048576,
}
MAX_BUNDLE = 8 * 1024 * 1024
FLAGS = {
    key: False
    for key in (
        "hardware_access",
        "executables_started",
        "authorization_granted",
        "physical_device_verified",
        "physical_timing_verified",
        "calibration_verified",
        "endpoint_identity_verified",
        "report_authenticated",
        "native_recomputed_now",
        "source_execution_performed",
    )
}
NATIVE_FLAGS = {
    key: False
    for key in (
        "hardware_access",
        "executables_started",
        "authorization_granted",
        "physical_device_verified",
        "physical_timing_verified",
        "calibration_verified",
        "protocol_timing_compliance_verified",
        "endpoint_identity_verified",
    )
}
VERIFIER_PRODUCERS = {
    "0.8.0": ("0.7.0", "0.8.0"),
    "0.9.0": ("0.7.0", "0.8.0", "0.9.0"),
    "0.10.0": ("0.7.0", "0.8.0", "0.9.0", "0.10.0"),
    "0.11.0": ("0.7.0", "0.8.0", "0.9.0", "0.10.0", "0.11.0"),
}


def checked_verifier(report, version):
    require(
        type(version) is str and report["runner_version"] in VERIFIER_PRODUCERS.get(version, ()),
        "unsupported native producer/verifier pair",
    )
    return version


def canonical(value):
    raw = (
        json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        + "\n"
    ).encode("ascii")
    require(len(raw) <= MAX_BUNDLE, "instrument document exceeds 8 MiB", "LIMIT_EXCEEDED")
    return raw


def same(actual, expected, message):
    require(canonical(actual) == canonical(expected), message, "EVIDENCE_MISMATCH")


def label(value):
    require(
        type(value) is str and 0 < len(value) <= 4096 and all(ord(c) >= 32 for c in value),
        "invalid recorded path label",
    )
    return value


def reference(value, blob):
    exact(value, ("path", "sha256", "size_bytes"))
    label(value["path"])
    same(
        {k: value[k] for k in ("sha256", "size_bytes")},
        {k: blob[k] for k in ("sha256", "size_bytes")},
        "native input reference differs",
    )
    return value


def portable(base, value):
    label(value)
    require(
        len(value) <= 1024 and "\\" not in value and ":" not in value,
        "portable relative input path required",
    )
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        p + str(i) for p in ("COM", "LPT") for i in range(1, 10)
    }
    for part in value.split("/"):
        require(
            part not in ("", ".", "..")
            and not part.endswith((" ", "."))
            and not any(c in '<>"|?*' for c in part)
            and part.split(".")[0].upper() not in reserved,
            "unsafe relative input path",
        )
    return base.joinpath(*value.split("/"))


def snapshot(raw, ref):
    return {
        "path": ref["path"],
        "sha256": digest(raw),
        "size_bytes": len(raw),
        "raw_base64": base64.b64encode(raw).decode("ascii"),
    }


def unpack(blob, maximum):
    exact(blob, ("path", "sha256", "size_bytes", "raw_base64"))
    label(blob["path"])
    size = blob["size_bytes"]
    require(type(size) is int and 0 < size <= maximum, "invalid snapshot size", "LIMIT_EXCEEDED")
    encoded = blob["raw_base64"]
    require(
        type(encoded) is str and len(encoded) == 4 * ((size + 2) // 3),
        "invalid snapshot base64 length",
    )
    raw = base64.b64decode(encoded, validate=True)
    require(
        len(raw) == size
        and digest(raw) == blob["sha256"]
        and base64.b64encode(raw).decode("ascii") == encoded,
        "snapshot hash/content differs",
        "EVIDENCE_MISMATCH",
    )
    return raw


def validate_spec(spec):
    exact(spec, ("schema_version", "native_exit_code", "inputs"))
    require(spec["schema_version"] == PREFIX + "spec.v1", "unsupported instrument spec")
    require(
        type(spec["native_exit_code"]) is int and spec["native_exit_code"] in (0, 3),
        "native verification/JUnit must have completed with exit 0 or 3",
    )
    exact(spec["inputs"], LIMITS)
    for item in spec["inputs"].values():
        exact(item, ("path", "sha256"))
        require(
            type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
            "invalid input SHA-256",
        )
        portable(Path("."), item["path"])


def native_report(report, spec, capture, blobs):
    require(
        spec.get("schema_version") == "lab-instruments.logic-check-spec.v1"
        and set(spec) == {"schema_version", "checks"},
        "invalid native assertion spec",
    )
    require(
        report.get("schema_version") == "lab-instruments.logic-check-report.v1"
        and report.get("runner_version") in ("0.7.0", "0.8.0", "0.9.0", "0.10.0", "0.11.0")
        and report.get("scope") == "host_only_saved_logic_evaluation"
        and report.get("complete") is True,
        "unsupported native report",
    )
    require(
        all(report.get(k) is False for k in NATIVE_FLAGS),
        "native report upgrades a physical/safety claim",
    )
    require(
        capture.get("schema_version") == "lab-instruments.capture.v1"
        and capture.get("instrument") == "logic"
        and type(capture.get("ok")) is bool
        and capture.get("evidence_origin") in ("test_double", "physical_instrument"),
        "invalid capture source",
    )
    reference(report["spec"], blobs["spec"])
    reference(report["capture"], blobs["capture"])
    same(report["evidence_origin"], capture["evidence_origin"], "source origin differs")
    checks = report["checks"]
    require(
        type(checks) is list and 1 <= len(checks) <= 8 and len(checks) == len(spec["checks"]),
        "invalid check count",
    )
    seen = set()
    for check, contract in zip(checks, spec["checks"], strict=True):
        exact(contract, ("id", "kind", "configuration", "expect"))
        require(
            type(contract["id"]) is str
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", contract["id"])
            and contract["id"] not in seen
            and contract["kind"] in ("uart", "pwm", "i2c", "spi"),
            "invalid check identity",
        )
        seen.add(contract["id"])
        exact(check, (*contract, "native", "native_sha256", "assertions", "ok", "status"))
        same(
            {key: check[key] for key in contract},
            contract,
            "report check differs from original spec",
        )
        native = check["native"]
        require(
            isinstance(native, dict) and digest(canonical(native)) == check["native_sha256"],
            "native analysis hash differs",
        )
        same(native["capture"], report["capture"], "native capture differs")
        for key, value in {
            "source_ok": capture["ok"],
            "source_status": capture["status"],
            "source_error": capture.get("error"),
            "source_cleanup": capture["cleanup"],
            "evidence_origin": capture["evidence_origin"],
        }.items():
            same(native[key], value, "native source declaration differs")
        require(
            type(native.get("ok")) is bool and (capture["ok"] or native["ok"] is False),
            "failed source upgraded",
        )
        require(
            all(
                native.get(k) is False
                for k in (
                    "hardware_access",
                    "executables_started",
                    "physical_timing_verified",
                    "calibration_verified",
                )
            ),
            "native analysis upgrades a physical/safety claim",
        )
        assertions = check["assertions"]
        require(
            type(assertions) is list
            and 1 <= len(assertions) <= 16
            and all(
                isinstance(a, dict) and a.get("status") in ("passed", "failed", "not_evaluated")
                for a in assertions
            ),
            "invalid assertion records",
        )
        passed = all(a["status"] == "passed" for a in assertions)
        same(check["ok"], passed, "check verdict differs")
        same(
            check["status"],
            "passed" if passed else ("failed" if native["ok"] else "invalid_evidence"),
            "check status differs",
        )
        require(not passed or native["ok"], "invalid native evidence upgraded")
        if not native["ok"]:
            same(
                assertions,
                [
                    {"name": "source_and_decode", "status": "failed", "actual": native["status"]},
                    {
                        "name": "expectation",
                        "status": "not_evaluated",
                        "reason": "source or decoding failed",
                    },
                ],
                "invalid evidence gate differs",
            )
    summary = {
        "checks": len(checks),
        "passed": sum(c["ok"] for c in checks),
        "failed": sum(not c["ok"] for c in checks),
    }
    same(report["summary"], summary, "native summary differs")
    same(report["ok"], all(c["ok"] for c in checks), "native report verdict differs")
    same(report["status"], "passed" if report["ok"] else "failed", "native report status differs")


def junit_bytes(report, report_sha, verifier_version="0.8.0"):
    checked_verifier(report, verifier_version)
    counts = {
        "tests": len(report["checks"]),
        "failures": sum(c["status"] == "failed" for c in report["checks"]),
        "errors": sum(c["status"] == "invalid_evidence" for c in report["checks"]),
        "skipped": 0,
    }
    root = ET.Element(
        "testsuite", name="lab-instruments.logic", **{k: str(v) for k, v in counts.items()}
    )
    props = ET.SubElement(root, "properties")
    values = {
        "report_sha256": report_sha,
        "spec_sha256": report["spec"]["sha256"],
        "capture_sha256": report["capture"]["sha256"],
        "producer_runner_version": report["runner_version"],
        "verifier_version": verifier_version,
        "evidence_origin": report["evidence_origin"],
        "scope": "host_only_saved_logic_verification",
        "report_authenticated": False,
        "recorded_paths_followed": False,
        "duration_measured": False,
        **NATIVE_FLAGS,
    }
    for key, value in sorted(values.items()):
        ET.SubElement(
            props, "property", name=key, value=str(value).lower() if type(value) is bool else value
        )
    for check in report["checks"]:
        case = ET.SubElement(
            root, "testcase", name=check["id"], classname="lab_instruments.logic." + check["kind"]
        )
        if check["status"] != "passed":
            detail = {
                "status": check["status"],
                "assertions": check["assertions"],
                "native_sha256": check["native_sha256"],
                "native_status": check["native"]["status"],
                **{
                    key: check["native"][key]
                    for key in ("source_status", "source_error", "source_cleanup")
                },
            }
            ET.SubElement(
                case,
                "error" if check["status"] == "invalid_evidence" else "failure",
                type=check["status"],
                message=check["status"],
            ).text = canonical(detail).decode("ascii")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n", counts


def build(spec_blob, blobs, producer_version):
    require(
        producer_version in ("0.9.0", "0.10.0", "0.11.0", "0.12.0"),
        "unsupported HIL instrument producer",
    )
    spec = decode(unpack(spec_blob, 16384))
    validate_spec(spec)
    exact(blobs, LIMITS)
    raw = {role: unpack(blobs[role], maximum) for role, maximum in LIMITS.items()}
    for role, blob in blobs.items():
        same(spec["inputs"][role]["sha256"], blob["sha256"], "manifest input binding differs")
    report, contract, capture, response = (
        decode(raw[role]) for role in ("report", "spec", "capture", "native_result")
    )
    native_report(report, contract, capture, blobs)
    require(
        response.get("schema_version") == "lab-instruments.result.v1"
        and all(
            response.get(k) is False
            for k in (
                "hardware_access",
                "executables_started",
                "authorization_granted",
                "physical_device_verified",
                "outputs_commanded",
            )
        ),
        "invalid native CLI result",
    )
    same(response["ok"], report["ok"], "native CLI verdict differs")
    same(spec["native_exit_code"], 0 if report["ok"] else 3, "native exit code differs")
    exact(response["data"], ("verification", "junit", "output"))
    verified = response["data"]["verification"]
    verifier_version = checked_verifier(report, verified.get("verifier_version"))
    expected = {
        "schema_version": "lab-instruments.logic-check-verification.v1",
        "ok": True,
        "status": "verified",
        "complete": True,
        "scope": "host_only_saved_logic_verification",
        "report": reference(verified["report"], blobs["report"]),
        "producer_runner_version": report["runner_version"],
        "verifier_version": verifier_version,
        "verdict": {k: report[k] for k in ("ok", "status", "summary")},
        "checks": [{k: c[k] for k in ("id", "kind", "status")} for c in report["checks"]],
        "evidence_origin": report["evidence_origin"],
        "report_authenticated": False,
        "recorded_paths_followed": False,
        **NATIVE_FLAGS,
    }
    for role in ("spec", "capture"):
        supplied = reference(verified[role + "_binding"]["supplied"], blobs[role])
        expected[role + "_binding"] = {
            "recorded": report[role],
            "supplied": supplied,
            "path_label_differs": report[role]["path"] != supplied["path"],
        }
    same(verified, expected, "native verification record differs")
    expected_xml, counts = junit_bytes(report, blobs["report"]["sha256"], verifier_version)
    same(response["data"]["junit"], counts, "native JUnit counts differ")
    reference(response["data"]["output"], blobs["junit"])
    require(
        raw["junit"] == expected_xml,
        "JUnit differs from recorded native verdict/details",
        "EVIDENCE_MISMATCH",
    )
    return {
        "schema_version": PREFIX + "report.v1",
        "producer_version": producer_version,
        "scope": "host_only_saved_instrument_import",
        **FLAGS,
        "ok": report["ok"],
        "status": report["status"],
        "summary": report["summary"],
        "checks": [
            {k: c[k] for k in ("id", "kind", "status", "native_sha256")} for c in report["checks"]
        ],
        "evidence_origin": report["evidence_origin"],
        "native_exit_code": spec["native_exit_code"],
        "native_recomputation_recorded": True,
        "validation_kind": "recorded_native_verification_and_explicit_input_integrity",
        "junit": counts,
        "import_spec": spec_blob,
        "inputs": blobs,
    }


def load(path, sha):
    raw, ref = read(path, MAX_BUNDLE, sha)
    value = decode(raw)
    require(isinstance(value, dict), "instrument report must be an object")
    expected = build(value["import_spec"], value["inputs"], value["producer_version"])
    same(value, expected, "HIL instrument report differs from embedded evidence")
    return value, {"path": ref["path"], "sha256": ref["sha256"], "size_bytes": ref["bytes"]}


def destination(path):
    parent = local(path.parent)
    require(parent.is_dir(), "output parent must exist")
    target = portable(parent, path.name)
    require(not target.exists() and not target.is_symlink(), "output exists", "OUTPUT_EXISTS")
    return target


def import_evidence(path, sha, output):
    output = destination(output)  # Reject before reading any input.
    raw, ref = read(path, 16384, sha)
    spec = decode(raw)
    validate_spec(spec)
    blobs = {}
    paths = set()
    for role, maximum in LIMITS.items():
        payload, bound = read(
            portable(Path(ref["path"]).parent, spec["inputs"][role]["path"]),
            maximum,
            spec["inputs"][role]["sha256"],
        )
        require(bound["path"] not in paths, "same input file selected twice")
        paths.add(bound["path"])
        blobs[role] = snapshot(payload, bound)
    value = build(snapshot(raw, ref), blobs, __version__)
    encoded = canonical(value)
    with output.open("xb") as stream:
        stream.write(encoded)
    return value, {"path": str(output), "sha256": digest(encoded), "size_bytes": len(encoded)}


def summary(value, ref):
    return {
        "input": ref,
        **{
            key: value[key]
            for key in (
                "status",
                "summary",
                "checks",
                "evidence_origin",
                "native_exit_code",
                "native_recomputation_recorded",
                "validation_kind",
                "junit",
            )
        },
        "verdict_ok": value["ok"],
        "source_files_rechecked": False,
        **FLAGS,
    }
