from __future__ import annotations

import io
import json
import tarfile
import zipfile

import pytest

from scripts import release

VERSION = "0.2.0"
REVISION = "a" * 40


def archives(directory, *, wheel_mutation=None, source_mutation=None, version=VERSION):
    """Small independent package fixture; never extract or import its contents."""
    metadata = f"embedded_hil_runner-{version}.dist-info/"
    wheel = {
        metadata + "METADATA": (
            f"Name: embedded-hil-runner\nVersion: {version}\nRequires-Python: >=3.11\n"
        ).encode(),
        metadata + "entry_points.txt": b"[console_scripts]\nhil-runner = hil_runner.cli:main\n",
        "hil_runner/managed.py": b"# synthetic source\n",
        "hil_runner/schemas/managed-plan.schema.json": b"{}\n",
    }
    source = {
        "pyproject.toml": f'[project]\nname="embedded-hil-runner"\nversion="{version}"\n'.encode(),
        "README.md": b"fixture\n",
        "LICENSE": b"fixture\n",
        "src/hil_runner/managed.py": wheel["hil_runner/managed.py"],
        "schemas/managed-plan.schema.json": b"{}\n",
    }
    if tuple(map(int, version.split("."))) >= (0, 10, 0):
        for name in (
            "waveform.py",
            "schemas/waveform-spec.schema.json",
            "schemas/waveform-report.schema.json",
        ):
            wheel["hil_runner/" + name] = b"# fixture\n" if name.endswith(".py") else b"{}\n"
            source[("" if name.startswith("schemas/") else "src/hil_runner/") + name] = wheel[
                "hil_runner/" + name
            ]
    if tuple(map(int, version.split("."))) >= (0, 11, 0):
        for name in (
            "load.py",
            "load_protocol.py",
            "schemas/load-spec.schema.json",
            "schemas/load-report.schema.json",
        ):
            wheel["hil_runner/" + name] = b"# fixture\n" if name.endswith(".py") else b"{}\n"
            source[("" if name.startswith("schemas/") else "src/hil_runner/") + name] = wheel[
                "hil_runner/" + name
            ]
    if wheel_mutation:
        wheel_mutation(wheel)
    if source_mutation:
        source_mutation(source)
    wheel_name, source_name = release.names(version)
    with zipfile.ZipFile(directory / wheel_name, "w") as archive:
        for name, data in wheel.items():
            item = zipfile.ZipInfo("placeholder")
            item.filename = name  # Preserve intentionally unsafe raw names on Windows too.
            archive.writestr(item, data)
    with tarfile.open(directory / source_name, "w:gz") as archive:
        for name, data in source.items():
            item = tarfile.TarInfo(f"embedded_hil_runner-{version}/" + name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))


def test_verified_release_binds_source_without_claiming_authenticity(tmp_path):
    archives(tmp_path)
    release.create_manifest(tmp_path, VERSION, REVISION)
    report = release.verify(tmp_path, REVISION)
    assert report["ok"] and report["source_revision"] == REVISION
    assert not report["executables_started"] and not report["hardware_access"]
    assert not report["publisher_authenticity_verified"]
    with pytest.raises(ValueError, match="Source revision differs"):
        release.verify(tmp_path, "b" * 40)


def test_waveform_release_binds_runtime_and_schemas(tmp_path):
    archives(tmp_path, version="0.10.0")
    release.create_manifest(tmp_path, "0.10.0", REVISION)
    assert release.verify(tmp_path, REVISION)["ok"]


@pytest.mark.parametrize(
    "name",
    ["waveform.py", "schemas/waveform-spec.schema.json", "schemas/waveform-report.schema.json"],
)
def test_waveform_release_requires_new_runtime_members(tmp_path, name):
    archives(
        tmp_path, version="0.10.0", wheel_mutation=lambda wheel: wheel.pop("hil_runner/" + name)
    )
    with pytest.raises(ValueError, match="Missing waveform runtime files"):
        release.create_manifest(tmp_path, "0.10.0", REVISION)


@pytest.mark.parametrize("name", [*release.names(VERSION), "release-manifest.json", "SHA256SUMS"])
def test_changed_release_asset_is_rejected(tmp_path, name):
    archives(tmp_path)
    release.create_manifest(tmp_path, VERSION, REVISION)
    path = tmp_path / name
    # Valid JSON drift must be detected even though it parses successfully.
    if name == "release-manifest.json":
        value = json.loads(path.read_bytes())
        value["hardware_access"] = True
        path.write_text(json.dumps(value))
    else:
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        release.verify(tmp_path, REVISION)


@pytest.mark.parametrize("name", ["../escape.py", "/absolute.py", "C:/escape.py", "a\\b.py"])
def test_unsafe_wheel_path_is_rejected_before_extraction(tmp_path, name):
    archives(tmp_path, wheel_mutation=lambda wheel: wheel.update({name: b"bad"}))
    with pytest.raises(ValueError, match="Unsafe archive member"):
        release.create_manifest(tmp_path, VERSION, REVISION)
    assert not (tmp_path / "release-manifest.json").exists()


def test_matching_outer_hashes_do_not_hide_wheel_source_drift(tmp_path):
    archives(
        tmp_path,
        source_mutation=lambda source: source.update(
            {"src/hil_runner/managed.py": b"different source\n"}
        ),
    )
    with pytest.raises(ValueError, match="Wheel/source mismatch"):
        release.create_manifest(tmp_path, VERSION, REVISION)


def test_runtime_dependency_is_rejected(tmp_path):
    def dependency(wheel):
        wheel["embedded_hil_runner-0.2.0.dist-info/METADATA"] += b"Requires-Dist: requests\n"

    archives(tmp_path, wheel_mutation=dependency)
    with pytest.raises(ValueError, match="Runtime dependencies"):
        release.create_manifest(tmp_path, VERSION, REVISION)


def test_unexpected_file_does_not_silently_enter_release(tmp_path):
    archives(tmp_path)
    release.create_manifest(tmp_path, VERSION, REVISION)
    (tmp_path / "extra.exe").write_bytes(b"unreviewed")
    with pytest.raises(ValueError, match="Unexpected/missing"):
        release.verify(tmp_path)
