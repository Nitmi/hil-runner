from __future__ import annotations

import runpy
from pathlib import Path

import pytest

DECODE = runpy.run_path(str(Path(__file__).parents[1] / "examples/nrf52840-dk/build.py"))[
    "decode_hex"
]
CHECK = runpy.run_path(str(Path(__file__).parents[1] / "examples/nrf52840-dk/accept.py"))[
    "check_message"
]


def record(kind, address=0, data=b""):
    payload = bytes([len(data)]) + address.to_bytes(2, "big") + bytes([kind]) + data
    return ":" + (payload + bytes([-sum(payload) & 255])).hex().upper()


def valid_image():
    return (0x20040000).to_bytes(4, "little") + (0x101).to_bytes(4, "little") + bytes(249)


def save(path, records):
    path.write_text("\n".join(records) + "\n", encoding="ascii")
    return path


def test_valid_dk_image_binds_vectors_and_one_page(tmp_path):
    image = valid_image()
    records = [record(0, start, image[start : start + 16]) for start in range(0, len(image), 16)]
    audit = DECODE(
        save(tmp_path / "firmware.hex", [*records, record(3, data=b"\0\0\x01\x01"), record(1)])
    )
    assert audit["decoded_bytes"] == len(image)
    assert audit["uicr_bytes"] == 0 and audit["erase_end_exclusive"] == 4096


@pytest.mark.parametrize(
    "records",
    [
        [record(4, data=b"\x10\x00"), record(0, 0x1208, b"\x5a\0\0\0"), record(1)],
        [record(0, 4095, b"AB"), record(1)],
        [record(0, 0, b"AB"), record(0, 1, b"CD"), record(1)],
        [record(0, 0, b"AB")],
        [":0100000001FF", record(1)],  # Deliberately incorrect checksum.
        [record(0, 0, bytes(16)), record(1)],
    ],
)
def test_unsafe_or_invalid_image_rejected_before_hardware(tmp_path, records):
    with pytest.raises(ValueError):
        DECODE(save(tmp_path / "firmware.hex", records))


@pytest.mark.parametrize(
    "mutation", [{"ok": False}, {"ok": 1}, {"operation": "managed.closed"}, {"request_id": "B"}]
)
def test_failed_or_mismatched_a_result_cannot_advance_to_b(mutation):
    message = {
        "schema_version": "embedded-hil-runner.managed-result.v1",
        "ok": True,
        "operation": "managed.build",
        "request_id": "A",
    }
    CHECK(message, "managed.build", "A")
    message.update(mutation)
    with pytest.raises(ValueError):
        CHECK(message, "managed.build", "A")
