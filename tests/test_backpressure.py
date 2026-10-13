from __future__ import annotations

import json
import subprocess
from contextlib import suppress

from hil_runner.common import digest

from .conftest import cli


def test_unconsumed_stdout_cannot_hold_lease_past_deadline(saved, tmp_path, live):
    path = saved()
    namespace = tmp_path / "shared-leases"
    process = subprocess.Popen(
        cli(
            "lease",
            "serve",
            path,
            "--selection-sha256",
            digest(path.read_bytes()),
            "--lease-root",
            namespace,
            "--duration-seconds",
            2,
            "--idle-timeout-seconds",
            1,
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        opened = json.loads(process.stdout.readline())
        assert opened["ok"]
        # Stop consuming stdout, fill the bounded response queue with invalid requests.
        process.stdin.write(b"{}\n" * 256)
        process.stdin.flush()
        assert process.wait(timeout=5) == 4
        assert process.stderr.read() == b""
        fresh = live(path)
        fresh.close(fresh.line()["data"]["lease_id"])
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            with suppress(OSError):
                stream.close()
