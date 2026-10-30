"""Import saved lab 0.9 waveform verification without decoding or device access."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import __version__
from .common import decode, digest
from .instrument import destination, label, portable, reference, snapshot, unpack
from .simulation import exact, local, read, require

PREFIX = "embedded-hil-runner.waveform-"
LIMITS = dict(report=1048576, spec=65536, capture=1048576, native_result=131072, junit=1048576)
MAX_SPEC = 512 * 1024
MAX_SOURCES = 8 * 1024 * 1024
MAX_BUNDLE = 20 * 1024 * 1024
METRICS = ("minimum_v", "maximum_v", "mean_v", "peak_to_peak_v", "rms_v", "ac_rms_v")
NATIVE_FLAGS = dict.fromkeys(
    (
        "hardware_access",
        "executables_started",
        "authorization_granted",
        "physical_device_verified",
        "physical_timing_verified",
        "calibration_verified",
        "dut_identity_verified",
        "sample_zero_utc_verified",
        "cross_channel_alignment_verified",
        "clipping_absent_verified",
        "analog_bandwidth_verified",
        "report_authenticated",
        "recorded_paths_followed",
    ),
    False,
)
FLAGS = {**NATIVE_FLAGS, "native_recomputed_now": False, "source_execution_performed": False}


def canonical(value):
    raw = (
        json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        + "\n"
    ).encode("ascii")
    require(len(raw) <= MAX_BUNDLE, "waveform document exceeds 20 MiB", "LIMIT_EXCEEDED")
    return raw


def same(actual, expected, message="waveform evidence differs"):
    require(canonical(actual) == canonical(expected), message, "EVIDENCE_MISMATCH")


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, "invalid waveform integer")
    return value


def number(value, low=-2e100, high=2e100):
    require(
        type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
        "invalid waveform number",
    )
    return value


def source_name(name):
    require(
        type(name) is str
        and re.fullmatch(
            r"(?:plan\.json|transcript\.jsonl|wire-[0-9]{4}-(?:tx|rx)\.bin|"
            r"c[1-4]-(?:preamble\.bin|words\.bin|samples\.csv))",
            name,
        ),
        "unsupported waveform source file name",
    )
    return name


def unpack_source(blob):
    if blob.get("size_bytes") == 0 and type(blob.get("size_bytes")) is int:
        exact(blob, ("path", "sha256", "size_bytes", "raw_base64"))
        label(blob["path"])
        same((blob["sha256"], blob["raw_base64"]), (digest(b""), ""))
        return b""
    return unpack(blob, 1048576)


def validate_manifest(value):
    exact(value, ("schema_version", "native_exit_code", "inputs", "source_files"))
    require(value["schema_version"] == PREFIX + "spec.v1", "unsupported waveform import spec")
    require(
        type(value["native_exit_code"]) is int and value["native_exit_code"] in (0, 3),
        "native waveform JUnit must have completed with exit 0 or 3",
    )
    exact(value["inputs"], LIMITS)
    sources = value["source_files"]
    require(isinstance(sources, list) and len(sources) <= 1614, "too many waveform sources")
    names = []
    for item in sources:
        exact(item, ("name", "path", "sha256"))
        names.append(source_name(item["name"]))
    require(len(set(names)) == len(names), "duplicate waveform source name")
    paths = set()
    for item in [*value["inputs"].values(), *sources]:
        portable(Path("."), item["path"])
        require(item["path"].casefold() not in paths, "duplicate waveform manifest path")
        paths.add(item["path"].casefold())
        require(
            type(item["sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", item["sha256"]),
            "invalid waveform input hash",
        )
    for item in value["inputs"].values():
        exact(item, ("path", "sha256"))


def validate_contract(contract):
    exact(contract, ("schema_version", "source_kind", "checks"))
    require(
        contract["schema_version"] == "lab-instruments.waveform-check-spec.v1"
        and contract["source_kind"] in ("ad3", "sds804x"),
        "unsupported native waveform spec",
    )
    checks = contract["checks"]
    require(isinstance(checks, list) and 1 <= len(checks) <= 8, "expected 1..8 waveform checks")
    names = set()
    for check in checks:
        exact(check, ("id", "channel", "window", "expect"))
        name = check["id"]
        require(
            type(name) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name)
            and name not in names,
            "invalid/duplicate waveform check id",
        )
        names.add(name)
        integer(check["channel"], 1, 2 if contract["source_kind"] == "ad3" else 4)
        window = check["window"]
        exact(window, ("start", "end_exclusive"))
        integer(window["start"], 0, 16383)
        integer(window["end_exclusive"], window["start"] + 1, 16384)
        require(
            isinstance(check["expect"], dict)
            and bool(check["expect"])
            and set(check["expect"]) <= set(METRICS),
            "invalid waveform expectations",
        )
        for metric, bounds in check["expect"].items():
            exact(bounds, ("minimum", "maximum"))
            number(bounds["minimum"], 0 if metric in METRICS[3:] else -1e100)
            number(bounds["maximum"], bounds["minimum"])


def validate_report(report, contract, blobs, sources, raw_sources):
    exact(
        report,
        (
            "schema_version",
            "runner_version",
            "scope",
            "spec",
            "capture",
            "source_kind",
            "source",
            "input_files",
            "ok",
            "status",
            "complete",
            "checks",
            "summary",
            *NATIVE_FLAGS,
        ),
    )
    require(
        report["schema_version"] == "lab-instruments.waveform-check-report.v1"
        and report["runner_version"] in ("0.9.0", "0.10.0", "0.11.0")
        and report["complete"] is True
        and report["scope"] == "host_only_saved_waveform_evaluation",
        "unsupported native report",
    )
    same({key: report[key] for key in NATIVE_FLAGS}, NATIVE_FLAGS)
    validate_contract(contract)
    same(report["source_kind"], contract["source_kind"])
    for role in ("spec", "capture"):
        reference(report[role], blobs[role])
    inventory = [dict(name="capture", **{k: blobs["capture"][k] for k in ("sha256", "size_bytes")})]
    inventory += [
        dict(name=name, **{k: blob[k] for k in ("sha256", "size_bytes")})
        for name, blob in sources.items()
    ]
    # Preserve native read order; no recorded name is ever used to open a file.
    same(report["input_files"], inventory, "native source inventory differs")
    require(
        len(inventory) <= 1615 and sum(i["size_bytes"] for i in inventory) <= MAX_SOURCES,
        "waveform source budget exceeded",
        "LIMIT_EXCEEDED",
    )
    capture = decode(unpack(blobs["capture"], LIMITS["capture"]))
    source = report["source"]
    require(
        source["evidence_origin"] in ("test_double", "physical_instrument", "scpi_tcp_session"),
        "unsupported waveform origin",
    )
    same(source["source_cleanup"], capture["cleanup"], "source cleanup differs")
    same(source["evidence_origin"], capture["evidence_origin"], "source origin differs")
    if report["source_kind"] == "ad3":
        require(
            not sources
            and capture["instrument"] == "scope"
            and capture["schema_version"] == "lab-instruments.capture.v1"
            and capture["ok"] is True
            and capture["status"] == "captured",
            "invalid AD3 capture",
        )
        same(
            source,
            {
                "model": capture["model"],
                "serial": capture["serial"],
                "source_cleanup": capture["cleanup"],
                "evidence_origin": capture["evidence_origin"],
                "time_basis": "sample_index_over_reported_rate_no_verified_utc_origin",
            },
        )
        payload = base64.b64decode(capture["payload"]["raw_base64"], validate=True)
        raw_ref = {
            "sha256": digest(payload),
            "size_bytes": len(payload),
            "encoding": "f64le_channel_major",
        }
        same(capture["payload"]["sha256"], digest(payload))
        same(capture["payload"]["length"], len(payload))
        same(capture["payload"]["encoding"], "f64le_channel_major")
        integer(capture["plan"]["samples"], 1, 16384)
        same(len(payload), len(capture["plan"]["channels"]) * capture["plan"]["samples"] * 8)
        require(
            capture["cleanup"]["input_stopped"] is True
            and capture["cleanup"]["owned_handle_closed"] is True
            and capture["cleanup"]["errors"] == [],
            "incomplete AD3 source cleanup",
        )
    else:
        require(bool(sources), "missing SDS original source files")
        require(
            capture["schema_version"] == "lab-instruments.scope-result.v1"
            and capture["ok"] is True
            and capture["status"] == "completed"
            and capture["cleanup"]["complete"] is True
            and capture["cleanup"]["errors"] == []
            and capture["cleanup"]["socket_closed"] is True
            and capture["cleanup"]["stopped_confirmed"] is True,
            "incomplete SDS source",
        )
        required = {"plan.json", "transcript.jsonl"}
        for item in capture["waveforms"]:
            for reference_item in item["files"].values():
                name = reference_item["name"]
                same(
                    {k: sources[name][k] for k in ("sha256", "size_bytes")},
                    {k: reference_item[k] for k in ("sha256", "size_bytes")},
                )
                required.add(name)
        same(
            {k: sources["transcript.jsonl"][k] for k in ("sha256", "size_bytes")},
            capture["transcript"],
        )
        same(sources["plan.json"]["sha256"], capture["plan_sha256"])
        same(decode(raw_sources["plan.json"]), capture["plan"])
        lines = raw_sources["transcript.jsonl"].splitlines()
        require(1 <= len(lines) <= 800, "SDS transaction budget exceeded", "LIMIT_EXCEEDED")
        for index, line in enumerate(lines):
            event = decode(line)
            require(event["complete"] is True, "incomplete SDS wire record")
            for direction in ("tx", "rx"):
                name = f"wire-{index:04d}-{direction}.bin"
                same(event[direction], name)
                same(
                    (sources[name]["sha256"], sources[name]["size_bytes"]),
                    (event[direction + "_sha256"], event[direction + "_bytes"]),
                )
                required.add(name)
        require(set(sources) == required, "missing or extra SDS original source files")
        same(
            source,
            {
                "identity": capture["identity"],
                "source_cleanup": capture["cleanup"],
                "source_freshness": capture["freshness"],
                "evidence_origin": capture["evidence_origin"],
                "time_basis": "descriptor_relative_no_verified_utc_origin",
            },
        )
    checks = report["checks"]
    require(
        isinstance(checks, list) and len(checks) == len(contract["checks"]), "check count differs"
    )
    for check, selected in zip(checks, contract["checks"], strict=True):
        same({k: check[k] for k in selected}, selected, "native check selection differs")
        channels = capture["plan"]["channels"]
        count = capture["plan"]["samples" if report["source_kind"] == "ad3" else "points"]
        meta = (
            None
            if report["source_kind"] == "ad3" or check["channel"] not in channels
            else next(
                item["metadata"]
                for item in capture["waveforms"]
                if item["channel"] == check["channel"]
            )
        )
        reason = (
            "channel_not_captured"
            if check["channel"] not in channels
            else "window_exceeds_capture"
            if check["window"]["end_exclusive"] > count
            else "requires_dc_coupling"
            if meta is not None and meta["coupling_code"] != 0
            else None
        )
        if check["status"] == "invalid_evidence":
            exact(check, (*selected, "status", "ok", "reason", "metrics", "assertions"))
            require(reason is not None, "invalid evidence without a source/window/coupling failure")
            same(check["reason"], reason)
            same((check["ok"], check["metrics"], check["assertions"]), (False, None, []))
            continue
        exact(
            check,
            (
                *selected,
                "status",
                "ok",
                "metrics",
                "assertions",
                "raw_span",
                "source_samples",
                "first_time_s",
                "last_time_s",
            ),
        )
        require(reason is None, "voltage assertions on invalid source/window/coupling")
        exact(check["metrics"], METRICS)
        for metric, value in check["metrics"].items():
            number(value, 0 if metric in METRICS[3:] else -1e100)
        assertions = [
            {
                "metric": metric,
                "expected": bounds,
                "actual": check["metrics"][metric],
                "ok": bounds["minimum"] <= check["metrics"][metric] <= bounds["maximum"],
            }
            for metric, bounds in sorted(selected["expect"].items())
        ]
        same(check["assertions"], assertions, "waveform assertion differs from recorded metrics")
        passed = all(a["ok"] for a in assertions)
        same((check["ok"], check["status"]), (passed, "passed" if passed else "failed"))
        samples = check["source_samples"]
        require(samples["coupling"] == "DC", "passing/failed voltage check requires DC")
        if report["source_kind"] == "ad3":
            same(samples["raw"], raw_ref)
            stride, offset = (
                8,
                capture["plan"]["channels"].index(check["channel"])
                * capture["plan"]["samples"]
                * 8,
            )
            same(samples["conversion"], "sdk_voltage_samples")
            same(
                samples["interval_s"],
                1 / number(capture["settings"]["sample_rate_hz"], 1, 125_000_000),
            )
            same(samples["first_time_s"], 0.0)
        else:
            stride, offset = 2, 0
            for role, suffix in (("raw", "words.bin"), ("preamble", "preamble.bin")):
                expected_name = f"c{check['channel']}-{suffix}"
                item = samples[role]
                same(item["name"], expected_name)
                same(
                    {k: item[k] for k in ("sha256", "size_bytes")},
                    {k: sources[expected_name][k] for k in ("sha256", "size_bytes")},
                )
            same(samples["conversion"], "en11g_probe_aware_word_conversion")
            same(samples["raw"]["encoding"], "s16le_left_aligned_adc_words")
            same(samples["descriptor"], meta)
            same(samples["interval_s"], meta["sample_interval_s"])
            same(samples["first_time_s"], meta["trigger_delay_s"] - meta["timebase_s"] * 5)
        same((samples["stride"], samples["offset"]), (stride, offset))
        window = check["window"]
        same(
            check["raw_span"],
            {
                "start": offset + stride * window["start"],
                "end_exclusive": offset + stride * window["end_exclusive"],
            },
        )
        require(
            check["raw_span"]["end_exclusive"] <= samples["raw"]["size_bytes"],
            "raw window exceeds retained bytes",
        )
        interval = number(samples["interval_s"], 1e-15, 1e100)
        first = number(samples["first_time_s"])
        same(
            (check["first_time_s"], check["last_time_s"]),
            (first + window["start"] * interval, first + (window["end_exclusive"] - 1) * interval),
        )
    summary = {
        "checks": len(checks),
        **{
            s: sum(c["status"] == s for c in checks)
            for s in ("passed", "failed", "invalid_evidence")
        },
    }
    same(report["summary"], summary)
    passed = summary["passed"] == len(checks)
    same((report["ok"], report["status"]), (passed, "passed" if passed else "failed"))


def junit_bytes(report, sha):
    counts = dict(
        tests=len(report["checks"]),
        failures=report["summary"]["failed"],
        errors=report["summary"]["invalid_evidence"],
        skipped=0,
    )
    root = ET.Element(
        "testsuite", name="lab-instruments.waveform", **{k: str(v) for k, v in counts.items()}
    )
    props = ET.SubElement(root, "properties")
    for key, value in sorted(
        {
            **NATIVE_FLAGS,
            "report_sha256": sha,
            "spec_sha256": report["spec"]["sha256"],
            "capture_sha256": report["capture"]["sha256"],
        }.items()
    ):
        ET.SubElement(
            props, "property", name=key, value=str(value).lower() if type(value) is bool else value
        )
    for check in report["checks"]:
        case = ET.SubElement(
            root, "testcase", name=check["id"], classname="lab_instruments.waveform"
        )
        if not check["ok"]:
            ET.SubElement(
                case,
                "error" if check["status"] == "invalid_evidence" else "failure",
                message=check["status"],
            ).text = canonical(check).decode("ascii")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n", counts


def build(manifest_blob, blobs, sources, version):
    require(
        version in ("0.10.0", "0.11.0", "0.12.0", "0.13.0", "0.14.0", "0.15.0"),
        "unsupported HIL waveform producer",
    )
    manifest = decode(unpack(manifest_blob, MAX_SPEC))
    validate_manifest(manifest)
    exact(blobs, LIMITS)
    require(
        isinstance(sources, dict) and set(sources) == {i["name"] for i in manifest["source_files"]},
        "source inventory differs",
    )
    sources = {i["name"]: sources[i["name"]] for i in manifest["source_files"]}
    require(
        sum(integer(b["size_bytes"], 0, 1048576) for b in sources.values())
        + integer(blobs["capture"]["size_bytes"], 1, 1048576)
        <= MAX_SOURCES,
        "waveform source budget exceeded",
        "LIMIT_EXCEEDED",
    )
    raw_sources = {name: unpack_source(blob) for name, blob in sources.items()}
    raw = {role: unpack(blobs[role], limit) for role, limit in LIMITS.items()}
    for role, item in manifest["inputs"].items():
        same(item["sha256"], blobs[role]["sha256"])
    for item in manifest["source_files"]:
        same(item["sha256"], sources[item["name"]]["sha256"])
    report, contract, response = (decode(raw[r]) for r in ("report", "spec", "native_result"))
    validate_report(report, contract, blobs, sources, raw_sources)
    exact(
        response,
        (
            "schema_version",
            "ok",
            "data",
            "hardware_access",
            "executables_started",
            "authorization_granted",
            "physical_device_verified",
            "outputs_commanded",
        ),
    )
    require(
        response["schema_version"] == "lab-instruments.result.v1", "unsupported native CLI result"
    )
    for key in (
        "hardware_access",
        "executables_started",
        "authorization_granted",
        "physical_device_verified",
        "outputs_commanded",
    ):
        require(response[key] is False, "native CLI upgrades a physical/authorization claim")
    same(response["ok"], report["ok"])
    same(manifest["native_exit_code"], 0 if report["ok"] else 3)
    exact(response["data"], ("verification", "junit", "output"))
    verified = response["data"]["verification"]
    verifier_version = verified.get("verifier_version")
    require(
        verifier_version == "0.11.0"
        or verifier_version == "0.10.0"
        and report["runner_version"] in ("0.9.0", "0.10.0")
        or verifier_version == "0.9.0"
        and report["runner_version"] == "0.9.0",
        "unsupported native waveform producer/verifier pair",
    )
    bindings = {}
    for role in ("spec", "capture"):
        supplied = reference(verified["bindings"][role]["supplied"], blobs[role])
        bindings[role] = dict(
            recorded=report[role],
            supplied=supplied,
            path_label_differs=report[role]["path"] != supplied["path"],
        )
    same(
        verified,
        {
            "schema_version": "lab-instruments.waveform-check-verification.v1",
            "ok": True,
            "status": "verified",
            "report": reference(verified["report"], blobs["report"]),
            "bindings": bindings,
            "producer_runner_version": report["runner_version"],
            "verifier_version": verifier_version,
            "verdict": {k: report[k] for k in ("ok", "status", "summary")},
            "scope": "host_only_saved_waveform_verification",
            **NATIVE_FLAGS,
        },
        "native waveform verification record differs",
    )
    xml, counts = junit_bytes(report, blobs["report"]["sha256"])
    same(response["data"]["junit"], counts)
    reference(response["data"]["output"], blobs["junit"])
    require(raw["junit"] == xml, "native waveform JUnit bytes differ", "EVIDENCE_MISMATCH")
    return {
        "schema_version": PREFIX + "report.v1",
        "producer_version": version,
        "scope": "host_only_saved_waveform_import",
        **FLAGS,
        "ok": report["ok"],
        "status": report["status"],
        "summary": report["summary"],
        "source_kind": report["source_kind"],
        "source": report["source"],
        "checks": report["checks"],
        "native_exit_code": manifest["native_exit_code"],
        "native_recomputation_recorded": True,
        "validation_kind": "recorded_native_verification_and_explicit_input_integrity",
        "junit": counts,
        "import_spec": manifest_blob,
        "inputs": blobs,
        "source_files": sources,
    }


def load(path, sha):
    raw, ref = read(path, MAX_BUNDLE, sha)
    value = decode(raw)
    expected = build(
        value["import_spec"], value["inputs"], value["source_files"], value["producer_version"]
    )
    same(value, expected, "waveform bundle differs from embedded evidence")
    return value, ref


def import_evidence(path, sha, output):
    output = destination(output)
    raw, ref = read(path, MAX_SPEC, sha)
    manifest = decode(raw)
    validate_manifest(manifest)
    paths = {os.path.normcase(ref["path"]).casefold()}
    manifest_stat = Path(ref["path"]).stat()
    identities = {(manifest_stat.st_dev, manifest_stat.st_ino)}
    sources, blobs = {}, {}
    size = 0
    for role, item, maximum in [
        *((r, manifest["inputs"][r], n) for r, n in LIMITS.items()),
        *((i["name"], i, 1048576) for i in manifest["source_files"]),
    ]:
        target = portable(Path(ref["path"]).parent, item["path"])
        target = local(target)
        key = os.path.normcase(str(target)).casefold()
        require(key not in paths, "same waveform input path selected twice")
        paths.add(key)
        info = target.stat()
        identity = (info.st_dev, info.st_ino)
        require(identity not in identities, "same waveform input file selected twice")
        identities.add(identity)
        if role == "capture" or role not in LIMITS:
            maximum = min(maximum, MAX_SOURCES - size)
            require(maximum >= 0, "waveform source budget exceeded", "LIMIT_EXCEEDED")
        payload, bound = read(target, maximum, item["sha256"])
        (blobs if role in LIMITS else sources)[role] = snapshot(payload, bound)
        if role == "capture" or role not in LIMITS:
            size += len(payload)
    value = build(snapshot(raw, ref), blobs, sources, __version__)
    encoded = canonical(value)
    with output.open("xb") as stream:
        stream.write(encoded)
    return value, {"path": str(output), "sha256": digest(encoded), "size_bytes": len(encoded)}


def summary(value, ref):
    return {
        "input": ref,
        **{
            k: value[k]
            for k in (
                "status",
                "summary",
                "source_kind",
                "source",
                "checks",
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
