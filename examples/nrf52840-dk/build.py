"""Build two code-only DK UART fixtures; never discover or operate hardware."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
INPUTS = ("Cargo.toml", "Cargo.lock", "build.rs", "memory.x", "src/main.rs", "build.py")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def call(arguments, **options):
    return subprocess.run(arguments, check=True, capture_output=True, timeout=120, **options)


def decode_hex(path: Path) -> dict:
    """Verify records, reject overlap/non-Code-Flash and return the exact image."""
    memory = {}
    base = 0
    ended = False
    entry = None
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith(":") or ended:
            raise ValueError("unexpected Intel HEX record")
        record = bytes.fromhex(line[1:])
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
            raise ValueError("bad Intel HEX record length/checksum")
        length, offset, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
        data = record[4:-1]
        if kind == 0:
            for index, value in enumerate(data):
                address = base + offset + index
                if not 0 <= address < 4096 or address in memory:
                    raise ValueError("image overlaps or escapes the first Code Flash page")
                memory[address] = value
        elif kind == 1 and length == 0 and offset == 0:
            ended = True
        elif kind == 4 and length == 2 and offset == 0:
            base = int.from_bytes(data, "big") << 16
        elif kind in {3, 5} and length == 4 and offset == 0 and entry is None:
            entry = (
                (int.from_bytes(data[:2], "big") << 4) + int.from_bytes(data[2:], "big")
                if kind == 3
                else int.from_bytes(data, "big")
            )
        else:
            raise ValueError("unsupported Intel HEX record")
    if not ended or min(memory, default=-1) != 0:
        raise ValueError("missing HEX EOF or vector table")
    addresses = sorted(memory)
    if addresses != list(range(addresses[-1] + 1)):
        raise ValueError("firmware must be one contiguous region")
    image = bytes(memory[index] for index in addresses)
    stack, reset = int.from_bytes(image[:4], "little"), int.from_bytes(image[4:8], "little")
    if stack != 0x20040000 or not reset & 1 or not 256 <= reset - 1 < len(image):
        raise ValueError("unexpected vector table")
    if entry is not None and entry != reset:
        raise ValueError("HEX entry differs from the reset vector")
    return {
        "start": 0,
        "end_exclusive": len(image),
        "decoded_bytes": len(image),
        "decoded_sha256": sha(image),
        "initial_sp": stack,
        "reset_vector": reset,
        "uicr_bytes": 0,
        "erase_start": 0,
        "erase_end_exclusive": 4096,
    }


def build(output: Path, target_dir: Path) -> dict:
    # Both paths are new: preserve existing builds and keep Cargo output outside source.
    output.mkdir(parents=True, exist_ok=False)
    target_dir.mkdir(parents=True, exist_ok=False)
    files = [
        {"path": name, "sha256": sha((SOURCE / name).read_bytes().replace(b"\r\n", b"\n"))}
        for name in INPUTS
    ]
    sysroot = Path(call(["rustc", "--print", "sysroot"]).stdout.decode().strip())
    compiler = call(["rustc", "-vV"]).stdout.decode()
    host = next(
        line.removeprefix("host: ") for line in compiler.splitlines() if line.startswith("host: ")
    )
    objcopy = sysroot / "lib/rustlib" / host / "bin/llvm-objcopy.exe"
    if not objcopy.is_file():
        raise ValueError("installed LLVM tools required")
    variants = []
    for variant in ("A", "B"):
        identity = sha(json.dumps({"inputs": files, "variant": variant}, sort_keys=True).encode())
        environment = dict(os.environ, HIL_DK_BUILD_ID=identity, HIL_DK_VARIANT=variant)
        # Override ambient host Rust flags for the embedded target, without persistent edits.
        environment.pop("RUSTFLAGS", None)
        environment["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(
            ["-C", "link-arg=-Tmemory.x", "-C", "link-arg=--nmagic"]
        )
        environment["CARGO_TARGET_DIR"] = str(target_dir)
        compiled = call(
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--offline",
                "--target",
                "thumbv7em-none-eabihf",
            ],
            cwd=SOURCE,
            env=environment,
        )
        (output / f"build-{variant}.stderr.log").write_bytes(compiled.stderr)
        elf = output / f"firmware-{variant}.elf"
        elf.write_bytes((target_dir / "thumbv7em-none-eabihf/release/hil-nrf52840-dk").read_bytes())
        hex_path = output / f"firmware-{variant}.hex"
        call([str(objcopy), "-O", "ihex", str(elf), str(hex_path)])
        audit = decode_hex(hex_path)
        variants.append(
            {
                "variant": variant,
                "build_id": identity,
                "build_line": f"HIL_NRF52840_DK_BUILD v1 {variant} {identity}",
                "firmware": {"path": str(hex_path), "sha256": sha(hex_path.read_bytes())},
                "elf": {"path": str(elf), "sha256": sha(elf.read_bytes())},
                "image": audit,
            }
        )
    if variants[0]["firmware"]["sha256"] == variants[1]["firmware"]["sha256"]:
        raise ValueError("A and B must differ")
    manifest = {
        "schema_version": "embedded-hil-runner.dk-fixtures.v1",
        "hardware_access": False,
        "target": "nRF52840_xxAA",
        "source_files": files,
        "build_identity_is_binary_attestation": False,
        "compiler": compiler,
        "ready_line": "HIL_NRF52840_DK_READY v1",
        "heartbeat_line": "HIL_NRF52840_DK_HEARTBEAT",
        "variants": variants,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target-dir", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output.resolve(), arguments.target_dir.resolve()), indent=2))
