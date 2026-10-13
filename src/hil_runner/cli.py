from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import __version__
from .common import HilError, report
from .lease import Lease, bounds
from .selection import selection_plan
from .server import OutputPump, serve


def default_root() -> Path:
    if os.name == "nt":
        parent = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    else:
        parent = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return parent / "embedded-hil-runner/leases"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Host-only cooperative HIL resource leases.")
    root.add_argument("--version", action="version", version=f"hil-runner {__version__}")
    domains = root.add_subparsers(dest="domain", required=True)
    lease = domains.add_parser("lease")
    commands = lease.add_subparsers(dest="operation", required=True)
    for name in ("plan", "serve"):
        item = commands.add_parser(name)
        item.add_argument("selection", type=Path)
        item.add_argument("--lease-root", type=Path, default=default_root())
        item.add_argument("--json", action="store_true", help="serve always uses JSONL")
        if name == "serve":
            item.add_argument("--selection-sha256", required=True)
            item.add_argument("--duration-seconds", type=int, default=300)
            item.add_argument("--idle-timeout-seconds", type=int, default=60)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    operation = "lease." + args.operation
    try:
        if args.operation == "serve":
            bounds(args.duration_seconds, args.idle_timeout_seconds)
        plan = selection_plan(
            args.selection,
            args.lease_root,
            args.selection_sha256 if args.operation == "serve" else None,
        )
        if args.operation == "plan":
            value = report(operation, data=plan)
            if args.json:
                print(json.dumps(value, indent=2, sort_keys=True))
            else:
                print("\n".join(plan["resources"]))
            return 0
        output = OutputPump()
        code = serve(
            Lease(plan, duration=args.duration_seconds, idle=args.idle_timeout_seconds),
            0,
            output.emit,
        )
        return code if output.finish() else 4
    except HilError as error:
        value = report(operation, error=error)
        code = 2
    except (OSError, ValueError, RuntimeError) as error:
        value = report(operation, error=HilError("HOST_IO_ERROR", str(error)))
        code = 4
    print(json.dumps(value, separators=(",", ":")))
    return code
