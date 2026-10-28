"""Bounded unpacking of repository-owned synthetic test fixtures only."""

from pathlib import Path, PurePosixPath
from zipfile import ZipFile

CASES = (
    "passed",
    "failed",
    "invalid",
    "mixed",
    "invalid-pixel",
    "mask-drift",
    "ffc-change",
    "duplicate",
    "source-failed",
    "cleanup-unknown",
    "no-pixels",
)
ARCHIVE = Path(__file__).resolve().parents[1] / "examples/thermal/fixtures.zip"


def extract(root, scenario="passed"):
    assert scenario in CASES
    with ZipFile(ARCHIVE) as z:
        members = [i for i in z.infolist() if i.filename.startswith(scenario + "/")]
        assert 1 <= len(members) <= 106
        for info in members:
            name = PurePosixPath(info.filename)
            assert not name.is_absolute() and all(p not in (".", "..") for p in name.parts)
            assert not info.is_dir() and info.file_size <= 1048576
            path = root.joinpath(*name.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as stream:
                data = stream.read(1048577)
            assert len(data) == info.file_size
            path.write_bytes(data)
    return root / scenario / "import.json"
