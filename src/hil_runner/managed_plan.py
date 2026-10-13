from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path

from . import __version__
from .common import HilError, decode, digest, invalid
from .lease import bounds
from .selection import SHA, exact, selection_plan, text

PLAN_SCHEMA = "embedded-hil-runner.managed-plan.v1"
SPEC_SCHEMA = "embedded-hil-runner.managed-spec.v1"
KNOWN_COMPONENTS = {"baud", "blea", "embedded-debugger", "board-registry", "firmware-inspect"}


def canonical(path: Path, *, strict=True) -> Path:
    value = str(path.resolve(strict=strict))
    if value.startswith("\\\\?\\") and not value.startswith("\\\\?\\UNC\\"):
        value = value[4:]
    return Path(value)


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise invalid("bound inputs must be regular, non-symlink files")
    import hashlib

    hasher = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > 256 * 1024 * 1024:
                raise invalid("bound file exceeds 256 MiB")
            hasher.update(chunk)
    return hasher.hexdigest()


def snapshot(
    path: Path, limit: int = 64 * 1024, expected: str | None = None
) -> tuple[dict, object]:
    path = path.resolve(strict=True)
    if not path.is_file():
        raise invalid("input must be a regular file")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise invalid("JSON input exceeds its byte limit")
    sha = digest(payload)
    if expected is not None and sha != expected:
        raise HilError("INPUT_DRIFT", "bound input SHA-256 changed")
    return {"path": str(path), "sha256": sha}, decode(payload)


def resolve(value, parent: Path) -> Path:
    path = Path(text(value, "input path", maximum=4096))
    return (path if path.is_absolute() else parent / path).resolve(strict=True)


def component_lock(path: Path) -> tuple[dict, dict]:
    reference, value = snapshot(path)
    value = exact(value, {"schema_version", "components"}, "component lock")
    records = value["components"]
    if (
        value["schema_version"]
        not in {
            "embedded-agent-toolkit.component-lock.v1",
            "embedded-agent-toolkit.component-lock.v2",
        }
        or not isinstance(records, dict)
        or not {"baud", "blea", "embedded-debugger"} <= set(records) <= KNOWN_COMPONENTS
        or (value["schema_version"].endswith(".v1") and len(records) != 3)
    ):
        raise invalid("unsupported component lock schema or inventory")
    selected = {}
    for name, row in records.items():
        row = exact(row, {"path", "version", "sha256"}, "component")
        executable = Path(text(row["path"], "component path", maximum=4096))
        if not executable.is_absolute() or executable.is_symlink():
            raise invalid("component path must be an absolute regular file")
        sha = text(row["sha256"], "component SHA-256")
        if not SHA.fullmatch(sha) or file_hash(executable) != sha:
            raise HilError("INPUT_DRIFT", "component executable differs from its lock")
        text(row["version"], "component version", maximum=128)
        selected[name] = {**row, "path": str(executable.resolve(strict=True))}
    return reference, selected


def runtime_policy(value, native: dict, selection: dict) -> dict:
    value = exact(
        value,
        {
            "schema_version",
            "name",
            "board",
            "target",
            "debug",
            "firmware",
            "flash",
            "serial",
            "visual",
            "abort_conditions",
            "cleanup",
        },
        "runtime template",
    )
    bindings = {row["transport"]: row["observed_identity"] for row in selection["bindings"]}
    if set(bindings) != {"debug", "serial"}:
        raise invalid("managed execution requires exactly debug and serial bindings")
    if (
        value["schema_version"] != "1.0"
        or value["target"] != native["target"]
        or value["debug"]
        != {"probe": native["probe"], "operation": "snapshot.reset-capture", "automatic_retries": 0}
        or bindings["debug"]["probe_selector"] != native["probe"]
    ):
        raise invalid("runtime debug selection differs from native flash scope")
    serial = value["serial"]
    if not isinstance(serial, dict):
        raise invalid("runtime serial policy must be an object")
    observed = bindings["serial"]
    for key, field in (
        ("port", "port"),
        ("usb_vid", "usb_vendor_id"),
        ("usb_pid", "usb_product_id"),
        ("usb_serial", "usb_serial_number"),
    ):
        if key not in observed or serial.get(field) != observed[key]:
            raise invalid("runtime serial policy differs from exact observed identity")
    if "pnp_interface" in observed and serial.get("usb_interface") != observed["pnp_interface"]:
        raise invalid("runtime interface differs from observed identity")
    if (
        serial.get("exact_port_identity_required") is not True
        or type(serial.get("transmit_bytes")) is not int
        or serial["transmit_bytes"] != 0
        or serial.get("data_bits") != 8
        or serial.get("parity") != "none"
        or serial.get("stop_bits") != 1
        or serial.get("flow_control") != "none"
        or type(serial.get("dtr")) is not bool
        or type(serial.get("rts")) is not bool
    ):
        raise invalid("runtime requires exact identity and zero-transmit 8N1 serial policy")
    for name in ("ready_line", "heartbeat_line"):
        text(serial.get(name), name, maximum=512)
    if (
        type(serial.get("observe_duration_seconds")) is not int
        or not 1 <= serial["observe_duration_seconds"] <= 60
        or type(serial.get("minimum_complete_heartbeats")) is not int
        or not 1 <= serial["minimum_complete_heartbeats"] <= 100
    ):
        raise invalid("runtime observation/count bounds are invalid")
    if value["cleanup"] != {
        "close_serial_session": True,
        "disconnect_debug_session": True,
        "do_not_retry_state_changing_failures": True,
    }:
        raise invalid("native runtime cleanup policy must remain enabled")
    if value["flash"] != {
        "exact_probe_selector_required": True,
        "exact_confirmation_digest_required": True,
        "automatic_retries": 0,
    }:
        raise invalid("native guarded flash policy must remain enabled")
    return copy.deepcopy(value)


def compile_plan(spec_path: Path, output: Path | None, lease_root: Path) -> dict:
    if output is not None and (output.exists() or output.is_symlink()):
        raise invalid("managed plan output already exists")
    spec_ref, spec = snapshot(spec_path)
    spec = exact(
        spec,
        {
            "schema_version",
            "selection",
            "component_lock",
            "native_scope",
            "native_confirm_digest",
            "runtime_template",
            "replay_fixture",
            "limits",
        },
        "spec",
    )
    if spec["schema_version"] != SPEC_SCHEMA:
        raise invalid("unsupported managed spec schema")
    parent = Path(spec_ref["path"]).parent
    selected_path = resolve(spec["selection"], parent)
    ownership = selection_plan(selected_path, lease_root)
    selection_ref, selection = snapshot(selected_path, 256 * 1024, ownership["selection"]["sha256"])
    lock_ref, components = component_lock(resolve(spec["component_lock"], parent))
    version = components["embedded-debugger"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or tuple(map(int, version.split("."))) < (
        0,
        2,
        5,
    ):
        raise invalid("managed execution needs embedded-debugger 0.2.5+ bounded monitor cleanup")
    native_ref, native = snapshot(resolve(spec["native_scope"], parent), 16 * 1024)
    if (
        not isinstance(native, dict)
        or native.get("schema_version") != "embedded-debugger.flash-session.v1"
        or native.get("backend") not in {"replay", "probe-rs"}
        or native.get("executor_sha256") != components["embedded-debugger"]["sha256"]
        or not Path(native.get("scope_path", "")).samefile(native_ref["path"])
    ):
        raise invalid("native scope does not bind the selected executor and original path")
    text(native.get("probe"), "native probe")
    text(native.get("target"), "native target")
    try:
        expiry = datetime.fromisoformat(native["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("timezone missing")
    except (KeyError, AttributeError, ValueError, TypeError) as error:
        raise invalid("native expiry must be an ISO-8601 timestamp with timezone") from error
    firmware_dir = canonical(Path(native.get("firmware_directory", "")))
    if not firmware_dir.is_dir():
        raise invalid("native firmware directory must exist")
    if native.get("firmware_format") not in {"bin", "hex"}:
        raise invalid("managed input snapshots currently support self-contained BIN and HEX only")
    confirm = text(spec["native_confirm_digest"], "native confirmation digest")
    if not SHA.fullmatch(confirm):
        raise invalid("native confirmation digest must be lowercase SHA-256")
    runtime_ref, template = snapshot(resolve(spec["runtime_template"], parent))
    template = runtime_policy(template, native, selection)
    limits = exact(
        spec["limits"],
        {
            "duration_seconds",
            "idle_timeout_seconds",
            "native_timeout_seconds",
            "startup_timeout_seconds",
            "shutdown_timeout_seconds",
        },
        "limits",
    )
    bounds(limits["duration_seconds"], limits["idle_timeout_seconds"])
    for key in ("native_timeout_seconds", "startup_timeout_seconds", "shutdown_timeout_seconds"):
        if type(limits[key]) is not int or not 1 <= limits[key] <= (
            120 if key == "native_timeout_seconds" else 10
        ):
            raise invalid("managed process timeout is outside its finite bound")
    if (
        type(native.get("duration_seconds")) is not int
        or limits["duration_seconds"] > native["duration_seconds"]
        or type(native.get("max_flashes")) is not int
        or not 1 <= native["max_flashes"] <= 100
    ):
        raise invalid("managed duration/count must fit the native scope")
    if limits["native_timeout_seconds"] < template["serial"]["observe_duration_seconds"] + 10:
        raise invalid("native timeout must include observation and its exit grace")
    refs = {
        "spec": spec_ref,
        "selection": selection_ref,
        "component_lock": lock_ref,
        "native_scope": native_ref,
        "runtime_template": runtime_ref,
    }
    if native["backend"] == "replay":
        if spec["replay_fixture"] is None:
            raise invalid("Replay requires a pinned fixture")
        refs["replay_fixture"], _ = snapshot(
            resolve(spec["replay_fixture"], parent), 4 * 1024 * 1024
        )
    elif spec["replay_fixture"] is not None:
        raise invalid("live managed execution cannot use a Replay fixture")
    body = {
        "schema_version": PLAN_SCHEMA,
        "runner_version": __version__,
        "inputs": refs,
        "ownership": ownership,
        "components": components,
        "native_scope": native,
        "native_confirm_digest": confirm,
        "runtime_template": template,
        "limits": limits,
        "authorization_granted": False,
        "execution_platform": "windows",
        "effects": [
            "native_bounded_flash",
            "native_runtime_reset_capture_per_build",
            "zero_transmit_serial_observation",
            "host_process_tree_management",
        ],
    }
    payload = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()
    if len(payload) > 256 * 1024:
        raise invalid("managed plan exceeds 256 KiB")
    if output is None:
        return {"body": body}
    with output.open("xb") as stream:
        stream.write(payload)
    return {"path": str(output.resolve()), "sha256": digest(payload), "body": body}


def read_plan(path: Path, expected: str) -> dict:
    if not SHA.fullmatch(expected):
        raise invalid("managed plan SHA-256 must be lowercase hexadecimal")
    _, body = snapshot(path, 256 * 1024, expected)
    if (
        not isinstance(body, dict)
        or body.get("schema_version") != PLAN_SCHEMA
        or body.get("runner_version") != __version__
    ):
        raise invalid("managed plan schema/version differs from the executor")
    current(body)
    fresh = compile_plan(
        Path(body["inputs"]["spec"]["path"]), None, Path(body["ownership"]["lease_root"])
    )["body"]
    if fresh != body:
        raise invalid("managed plan differs from its bound spec; regenerate it")
    return body


def current(body: dict) -> None:
    for ref in body["inputs"].values():
        if file_hash(Path(ref["path"])) != ref["sha256"]:
            raise HilError("INPUT_DRIFT", "managed source input changed")
    for row in body["components"].values():
        if file_hash(Path(row["path"])) != row["sha256"]:
            raise HilError("INPUT_DRIFT", "managed component executable changed")


def build_inputs(body: dict, value: dict) -> tuple[dict, dict]:
    value = exact(
        value,
        {"id", "operation", "firmware", "firmware_sha256", "runtime_contract", "runtime_sha256"},
        "build request",
    )
    if value["operation"] != "build":
        raise invalid("only build and close requests are supported")
    request_id = text(value["id"], "request id", maximum=64)
    if not request_id.isascii():
        raise invalid("request id must be ASCII")
    for key in ("firmware_sha256", "runtime_sha256"):
        if not isinstance(value[key], str) or not SHA.fullmatch(value[key]):
            raise invalid("build hashes must be lowercase SHA-256")
    firmware = canonical(Path(text(value["firmware"], "firmware path", maximum=4096)))
    if not firmware.is_relative_to(canonical(Path(body["native_scope"]["firmware_directory"]))):
        raise invalid("firmware must remain in the native scope directory")
    if file_hash(firmware) != value["firmware_sha256"]:
        raise HilError("INPUT_DRIFT", "submitted firmware SHA-256 changed")
    runtime_ref, contract = snapshot(
        Path(value["runtime_contract"]), 64 * 1024, value["runtime_sha256"]
    )
    normalized, expected = copy.deepcopy(contract), copy.deepcopy(body["runtime_template"])
    if not isinstance(normalized, dict) or not isinstance(normalized.get("serial"), dict):
        raise invalid("invalid runtime contract")
    text(normalized["serial"].get("build_id_line"), "required build identity", maximum=512)
    if normalized.get("firmware") != {"sha256": value["firmware_sha256"]}:
        raise invalid("runtime metadata must bind the submitted firmware SHA-256")
    for item in (normalized, expected):
        item["firmware"] = {}
        item["serial"]["build_id_line"] = None
    if normalized != expected:
        raise invalid("runtime policy drift: only firmware SHA-256 and BUILD line may change")
    return {
        "id": request_id,
        "firmware": {"path": str(firmware), "sha256": value["firmware_sha256"]},
        "runtime_contract": runtime_ref,
    }, contract
