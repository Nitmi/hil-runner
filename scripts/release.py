"""Build/verify Python release assets. Never run HIL or access hardware."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

SCHEMA = "embedded-hil-runner.python-release.v1"
REPOSITORY = "Nitmi/hil-runner"
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
REVISION = re.compile(r"[a-f0-9]{40}")
MAX_FILE = 8 * 1024 * 1024


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read(path: Path, limit: int = MAX_FILE) -> bytes:
    require(path.is_file() and not path.is_symlink(), "Expected a regular file")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "Release input exceeds limit")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pairs(items: list) -> dict:
    result = {}
    for key, value in items:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def names(version: str) -> tuple[str, str]:
    return (
        f"embedded_hil_runner-{version}-py3-none-any.whl",
        f"embedded_hil_runner-{version}.tar.gz",
    )


def safe_member(name: str) -> None:
    parts = name.split("/")
    require(
        bool(name)
        and "\\" not in name
        and ":" not in name
        and not PurePosixPath(name).is_absolute()
        and all(part not in ("", ".", "..") for part in parts),
        "Unsafe archive member",
    )


def payloads(directory: Path, version: str, snapshots: dict | None = None) -> tuple[dict, dict]:
    wheel_name, source_name = names(version)
    # Hashing and parsing are bounded; neither archive is extracted or executed.
    snapshots = snapshots or {name: read(directory / name) for name in names(version)}
    wheel = {}
    with zipfile.ZipFile(io.BytesIO(snapshots[wheel_name])) as archive:
        require(len(archive.infolist()) <= 128, "Too many wheel members")
        require(sum(item.file_size for item in archive.infolist()) <= MAX_FILE, "Wheel too large")
        for item in archive.infolist():
            safe_member(item.orig_filename)
            require(item.filename == item.orig_filename, "Normalized wheel member differs")
            require(
                item.filename not in wheel and not item.is_dir(), "Duplicate/directory wheel member"
            )
            require((item.external_attr >> 16) & 0o170000 != 0o120000, "Wheel symlink")
            wheel[item.filename] = archive.read(item)
    metadata_key = f"embedded_hil_runner-{version}.dist-info/METADATA"
    metadata = email.parser.BytesParser().parsebytes(wheel[metadata_key])
    require(
        metadata["Name"] == "embedded-hil-runner" and metadata["Version"] == version,
        "Wheel identity differs",
    )
    require(metadata["Requires-Python"] == ">=3.11", "Python requirement differs")
    require(
        all(
            item.split(";", 1)[-1].strip() in ("extra == 'dev'", 'extra == "dev"')
            for item in metadata.get_all("Requires-Dist", [])
        ),
        "Runtime dependencies found",
    )
    entrypoints = wheel[f"embedded_hil_runner-{version}.dist-info/entry_points.txt"].decode()
    require("hil-runner = hil_runner.cli:main" in entrypoints, "CLI entry point differs")
    require(
        "hil_runner/managed.py" in wheel and "hil_runner/schemas/managed-plan.schema.json" in wheel,
        "Missing runtime files",
    )
    if tuple(map(int, version.split("."))) >= (0, 10, 0):
        require(
            all(
                name in wheel
                for name in (
                    "hil_runner/waveform.py",
                    "hil_runner/schemas/waveform-spec.schema.json",
                    "hil_runner/schemas/waveform-report.schema.json",
                )
            ),
            "Missing waveform runtime files",
        )
    source = {}
    prefix = f"embedded_hil_runner-{version}/"
    total = 0
    with tarfile.open(fileobj=io.BytesIO(snapshots[source_name]), mode="r:gz") as archive:
        for item in archive:
            total += item.size
            require(
                len(source) < 512 and 0 <= item.size <= MAX_FILE and total <= MAX_FILE,
                "Source archive too large",
            )
            safe_member(item.name)
            require(item.isfile() and item.name.startswith(prefix), "Invalid source member")
            relative = item.name.removeprefix(prefix)
            require(relative not in source, "Duplicate source member")
            with archive.extractfile(item) as stream:
                source[relative] = stream.read(MAX_FILE + 1)
    require(
        all(
            name in source
            for name in ("pyproject.toml", "LICENSE", "README.md", "src/hil_runner/managed.py")
        ),
        "Incomplete source archive",
    )
    require(
        tomllib.loads(source["pyproject.toml"].decode())["project"]["version"] == version,
        "Source version differs",
    )
    for name, data in wheel.items():
        if name.startswith("hil_runner/"):
            target = (
                name.replace("hil_runner/schemas/", "schemas/", 1)
                if "/schemas/" in name
                else "src/" + name
            )
            require(source.get(target) == data, f"Wheel/source mismatch: {name}")
    return wheel, source


def create_manifest(directory: Path, version: str, revision: str) -> dict:
    require(
        VERSION.fullmatch(version) is not None and REVISION.fullmatch(revision) is not None,
        "Invalid release identity",
    )
    snapshots = {name: read(directory / name) for name in names(version)}
    payloads(directory, version, snapshots)
    manifest = {
        "schema_version": SCHEMA,
        "repository": REPOSITORY,
        "version": version,
        "source_revision": revision,
        "source_ref": f"refs/tags/v{version}",
        "hardware_access": False,
        "files": [
            {"name": name, "size": len(snapshots[name]), "sha256": digest(snapshots[name])}
            for name in names(version)
        ],
    }
    with (directory / "release-manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    snapshots["release-manifest.json"] = read(directory / "release-manifest.json")
    checksums = "".join(
        f"{digest(snapshots[name])}  {name}\n"
        for name in (*names(version), "release-manifest.json")
    )
    with (directory / "SHA256SUMS").open("x", encoding="ascii", newline="\n") as stream:
        stream.write(checksums)
    return manifest


def verify(directory: Path, expected_revision: str | None = None) -> dict:
    manifest_bytes = read(directory / "release-manifest.json", 16384)
    manifest = json.loads(manifest_bytes, object_pairs_hook=pairs)
    version, revision = manifest["version"], manifest["source_revision"]
    require(
        VERSION.fullmatch(version) is not None and REVISION.fullmatch(revision) is not None,
        "Invalid identity",
    )
    require(
        manifest["schema_version"] == SCHEMA
        and manifest["repository"] == REPOSITORY
        and manifest["source_ref"] == f"refs/tags/v{version}"
        and manifest["hardware_access"] is False,
        "Manifest contract differs",
    )
    require(expected_revision is None or revision == expected_revision, "Source revision differs")
    expected_names = (*names(version), "release-manifest.json", "SHA256SUMS")
    require(
        {item.name for item in directory.iterdir()} == set(expected_names),
        "Unexpected/missing release files",
    )
    require(
        [item["name"] for item in manifest["files"]] == list(names(version)), "Archive list differs"
    )
    snapshots = {name: read(directory / name) for name in names(version)}
    for item in manifest["files"]:
        data = snapshots[item["name"]]
        require(
            item["size"] == len(data) and item["sha256"] == digest(data),
            "Archive integrity differs",
        )
    snapshots["release-manifest.json"] = manifest_bytes
    expected_sums = "".join(f"{digest(snapshots[name])}  {name}\n" for name in expected_names[:-1])
    require(
        read(directory / "SHA256SUMS", 1024) == expected_sums.encode(), "Checksum bindings differ"
    )
    wheel, source = payloads(directory, version, snapshots)
    return {
        "ok": True,
        "version": version,
        "source_revision": revision,
        "files": manifest["files"],
        "wheel_members": len(wheel),
        "source_members": len(source),
        "hardware_access": False,
        "executables_started": False,
        "publisher_authenticity_verified": False,
    }


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, timeout=30
    ).stdout


def build(root: Path, output: Path, tag: str | None = None) -> dict:
    require(not git(root, "status", "--porcelain"), "Build requires a clean committed worktree")
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    if tag is not None:
        require(tag == "v" + version, "Tag/version mismatch")
        require(
            git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}").decode().strip() == revision,
            "Tag/commit mismatch",
        )
    output.mkdir(parents=True, exist_ok=False)
    subprocess.run(
        [
            "uv",
            "build",
            "--no-build-isolation",
            "--python",
            sys.executable,
            "--out-dir",
            str(output.resolve()),
        ],
        cwd=root,
        check=True,
        stdout=sys.stderr,
        timeout=180,
    )
    ignored = output / ".gitignore"
    if ignored.exists():
        require(read(ignored) in (b"*", b"*\n"), "Unexpected generated ignore file")
        ignored.unlink()
    _, source = payloads(output, version)
    for name, data in source.items():
        if name != "PKG-INFO":
            require(
                git(root, "show", f"{revision}:{name}") == data, f"Source differs from Git: {name}"
            )
    require(
        not git(root, "status", "--porcelain")
        and git(root, "rev-parse", "HEAD").decode().strip() == revision,
        "Source changed while building",
    )
    create_manifest(output, version, revision)
    return verify(output, revision)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--output-dir", required=True, type=Path)
    builder.add_argument("--tag")
    checker = commands.add_parser("verify")
    checker.add_argument("directory", type=Path)
    checker.add_argument("--source-revision")
    args = parser.parse_args()
    try:
        report = (
            build(Path(__file__).resolve().parents[1], args.output_dir, args.tag)
            if args.operation == "build"
            else verify(args.directory, args.source_revision)
        )
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        EOFError,
        RuntimeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
        tarfile.TarError,
    ) as error:
        print(json.dumps({"ok": False, "error": str(error), "hardware_access": False}))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
