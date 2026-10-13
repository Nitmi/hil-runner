from __future__ import annotations

import os
import re
from pathlib import Path

from .common import MAX_SELECTION_BYTES, decode, digest, invalid

ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEX = re.compile(r"[0-9a-fA-F]{4}\Z")
IDENTITIES = {
    "debug": {"probe_selector", "vendor_id", "product_id", "serial_number", "target"},
    "serial": {"port", "usb_vid", "usb_pid", "usb_serial", "pnp_interface"},
    "ble": {"identifier", "local_name", "service_uuid", "manufacturer_id"},
}


def exact(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise invalid(f"{label} requires exactly: {', '.join(sorted(keys))}")
    return value


def text(value: object, label: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != value.strip()
        or not value.isprintable()
        or any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise invalid(f"{label} must be a bounded printable non-empty string")
    return value


def identifier(value: object, label: str) -> str:
    result = text(value, label)
    if not ID.fullmatch(result):
        raise invalid(f"{label} must be a lowercase identifier")
    return result


def source(value: object, label: str, *, point_in_time: bool = False) -> None:
    keys = {"path", "sha256"} | ({"point_in_time"} if point_in_time else set())
    value = exact(value, keys, label)
    text(value["path"], label + ".path", maximum=4096)
    if not isinstance(value["sha256"], str) or not SHA.fullmatch(value["sha256"]):
        raise invalid(label + ".sha256 must be lowercase SHA-256")
    if point_in_time and value["point_in_time"] is not True:
        raise invalid(label + ".point_in_time must equal true")


def identity(value: object, transport: str) -> dict:
    if not isinstance(value, dict) or not value or not set(value) <= IDENTITIES[transport]:
        raise invalid(f"invalid {transport} identity fields")
    for key, item in value.items():
        text(item, f"{transport}.{key}")
    return value


def usb(vid: str, pid: str, serial: str) -> str:
    if not HEX.fullmatch(vid) or not HEX.fullmatch(pid):
        raise invalid("USB VID/PID must be four hexadecimal digits")
    # Conservative case folding may over-lock unusual case-distinct serials.
    return f"usb:{vid.upper()}:{pid.upper()}:{serial.upper()}"


def resource_keys(transport: str, observed: dict) -> set[str]:
    if transport == "debug":
        selector = observed.get("probe_selector", "")
        parts = selector.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            raise invalid("debug leases require an exact VID:PID:serial probe_selector")
        vid, pid, serial = parts
        for key, expected in (("vendor_id", vid), ("product_id", pid), ("serial_number", serial)):
            if key in observed and observed[key].upper() != expected.upper():
                raise invalid("probe_selector conflicts with observed probe fields")
        return {usb(vid, pid, serial)}
    if transport == "serial":
        port = observed.get("port")
        if not port:
            raise invalid("serial leases require an exact observed port")
        if re.fullmatch(r"COM[1-9][0-9]{0,4}", port, re.IGNORECASE):
            port_key = port.upper()
        elif os.name != "nt" and port.startswith("/"):
            # Canonicalize existing Unix aliases; this never opens the serial port.
            port_key = str(Path(port).resolve())
        else:
            raise invalid("unsupported serial port identity")
        result = {"serial-port:" + port_key}
        fields = {"usb_vid", "usb_pid", "usb_serial"}
        if fields & set(observed):
            if not fields <= set(observed):
                raise invalid("USB serial identities require VID, PID and serial together")
            result.add(usb(observed["usb_vid"], observed["usb_pid"], observed["usb_serial"]))
        return result
    address = observed.get("identifier", "")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", address) and not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", address
    ):
        raise invalid("BLE leases require an exact MAC address or UUID identifier")
    return {"ble:" + address.upper()}


def selection_plan(path: Path, lease_root: Path, expected: str | None = None) -> dict:
    if expected is not None and not SHA.fullmatch(expected):
        raise invalid("selection SHA-256 must be 64 lowercase hexadecimal characters")
    resolved = path.resolve(strict=True)
    with resolved.open("rb") as stream:
        payload = stream.read(MAX_SELECTION_BYTES + 1)
    if len(payload) > MAX_SELECTION_BYTES:
        raise invalid("selection exceeds 256 KiB")
    selection_hash = digest(payload)
    if expected is not None and selection_hash != expected:
        raise invalid("selection SHA-256 differs from the planned snapshot")
    value = exact(
        decode(payload),
        {
            "schema_version",
            "ok",
            "status",
            "board_id",
            "required_transports",
            "bindings",
            "inputs",
            "authorization",
            "hardware_access",
            "executables_started",
        },
        "selection",
    )
    if (
        value["schema_version"] != "embedded-board-registry.selection.v1"
        or value["ok"] is not True
        or value["status"] != "selected"
        or value["hardware_access"] is not False
        or value["executables_started"] is not False
    ):
        raise invalid("selection must be a successful non-executing board-registry selection")
    board_id = identifier(value["board_id"], "board_id")
    auth = exact(value["authorization"], {"granted", "allowed_operations"}, "authorization")
    if auth["granted"] is not False or auth["allowed_operations"] != []:
        raise invalid("selection cannot grant authorization")
    inputs = exact(value["inputs"], {"registry", "observations"}, "inputs")
    for key, item in inputs.items():
        source(item, "inputs." + key)
    required = value["required_transports"]
    if (
        not isinstance(required, list)
        or not 1 <= len(required) <= 3
        or any(not isinstance(item, str) or item not in IDENTITIES for item in required)
        or required != sorted(set(required))
    ):
        raise invalid("required_transports must be a sorted unique subset of ble/debug/serial")
    bindings = value["bindings"]
    if not isinstance(bindings, list) or len(bindings) != len(required):
        raise invalid("bindings must exactly cover required_transports in order")
    keys: set[str] = set()
    for transport, item in zip(required, bindings, strict=True):
        binding = exact(
            item,
            {
                "transport",
                "selector_id",
                "observation_id",
                "selector_identity",
                "observed_identity",
                "source",
            },
            "binding",
        )
        if binding["transport"] != transport:
            raise invalid("binding transport order differs from required_transports")
        identifier(binding["selector_id"], "selector_id")
        identifier(binding["observation_id"], "observation_id")
        wanted = identity(binding["selector_identity"], transport)
        observed = identity(binding["observed_identity"], transport)
        if any(observed.get(key) != item for key, item in wanted.items()):
            raise invalid("selector_identity must match observed_identity exactly")
        source(binding["source"], "binding.source", point_in_time=True)
        keys.update(resource_keys(transport, observed))
    namespace = lease_root.expanduser().resolve()
    if str(namespace).startswith(("\\\\", "//")):
        raise invalid("network lease roots are unsupported; use a shared local directory")
    return {
        "board_id": board_id,
        "selection": {"path": str(resolved), "sha256": selection_hash},
        "lease_root": str(namespace),
        "resources": sorted(keys),
        "upstream_files_revalidated": False,
        "hardware_identity_verified": False,
        "effects": [],
    }
