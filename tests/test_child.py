from __future__ import annotations

import json
import os
import sys
from unittest import mock

import pytest

from hil_runner.child import Child
from hil_runner.common import HilError

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows managed process containment")


def test_child_assigned_before_running_and_raw_capture_preserved(tmp_path):
    child = Child(
        [sys.executable, "-c", 'import os;os.write(1,b"{\\"ok\\":true}\\n")'], tmp_path, "child"
    )
    try:
        assert child.response(5, lambda: None) == {"ok": True}
        assert child.wait(5, lambda: None) == 0
    finally:
        cleanup = child.stop(2)
    assert cleanup["process_tree_stopped"] and cleanup["capture_complete"]
    assert not cleanup["forced_termination"]
    assert (tmp_path / "child.stdout.jsonl").read_bytes() == b'{"ok":true}\n'


def test_control_pretty_json_and_nonzero_exit(tmp_path):
    child = Child(
        [
            sys.executable,
            "-c",
            'import json,sys;print(json.dumps({"ok":False},indent=2));sys.exit(6)',
        ],
        tmp_path,
        "control",
        jsonl=False,
    )
    try:
        code, raw = child.control(5, lambda: None)
        assert code == 6 and json.loads(raw) == {"ok": False}
    finally:
        cleanup = child.stop(2)
    assert cleanup["process_tree_stopped"] and not cleanup["forced_termination"]


def test_job_failure_never_resumes_child(tmp_path):
    marker = tmp_path / "executed"
    code = f'from pathlib import Path;Path({str(marker)!r}).write_text("executed")'
    with (
        mock.patch(
            "hil_runner.winjob.Job.assign_and_resume",
            side_effect=HilError("HOST_IO_ERROR", "fixture"),
        ),
        pytest.raises(HilError),
    ):
        Child([sys.executable, "-c", code], tmp_path, "denied")
    assert not marker.exists()


def test_kill_whole_job_after_root_exit_with_descendant_alive(tmp_path):
    code = (
        "import subprocess,sys,json;"
        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
        'print(json.dumps({"pid":p.pid}),flush=True)'
    )
    child = Child([sys.executable, "-c", code], tmp_path, "tree")
    child.response(5, lambda: None)
    cleanup = child.stop(3)
    assert cleanup["forced_termination"] and cleanup["process_tree_stopped"]


def test_response_timeout_stops_child(tmp_path):
    child = Child([sys.executable, "-c", "import time;time.sleep(60)"], tmp_path, "silent")
    try:
        with pytest.raises(HilError, match="deadline"):
            child.response(0.2, lambda: None)
    finally:
        cleanup = child.stop(2)
    assert cleanup["process_tree_stopped"] and cleanup["forced_termination"]
