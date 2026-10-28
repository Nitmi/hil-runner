from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import __version__, instrument, simulation, thermal, waveform
from . import load as load_evidence
from .common import HilError, report
from .lease import Lease, bounds
from .managed import execute, result
from .managed_plan import compile_plan
from .selection import selection_plan
from .server import OutputPump, serve


def default_root() -> Path:
    if os.name == "nt":
        parent = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    else:
        parent = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return parent / "embedded-hil-runner/leases"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Cooperative leases and bounded native HIL execution."
    )
    root.add_argument("--version", action="version", version=f"hil-runner {__version__}")
    domains = root.add_subparsers(dest="domain", required=True)
    for domain in ("instrument", "waveform", "load", "thermal"):
        instruments = domains.add_parser(domain, help="offline recorded native verification")
        imports = instruments.add_subparsers(dest="operation", required=True)
        for operation in ("import", "inspect"):
            item = imports.add_parser(operation)
            item.add_argument("input", type=Path)
            item.add_argument("--sha256", required=True)
            item.add_argument("--json", action="store_true")
            if operation == "import":
                item.add_argument("--output", type=Path, required=True)
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
    managed = domains.add_parser("managed", help="fixed native flash/runtime execution")
    managed_commands = managed.add_subparsers(dest="operation", required=True)
    plan = managed_commands.add_parser(
        "plan", help="prepare a hash-bound managed plan without processes"
    )
    plan.add_argument("spec", type=Path)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--lease-root", type=Path, default=default_root())
    plan.add_argument("--json", action="store_true")
    serve_parser = managed_commands.add_parser(
        "serve", help="one native scope across bounded builds"
    )
    serve_parser.add_argument("plan", type=Path)
    serve_parser.add_argument("--plan-sha256", required=True)
    serve_parser.add_argument("--confirm", required=True, help="once-approved native scope digest")
    serve_parser.add_argument("--allow-runtime-reset", action="store_true")
    serve_parser.add_argument("--output-dir", type=Path, required=True)
    sim = domains.add_parser("simulation", help="bounded fixed sim-runner suites; no hardware")
    simulations = sim.add_subparsers(dest="operation", required=True)
    prep = simulations.add_parser("plan")
    prep.add_argument("spec", type=Path)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--json", action="store_true")
    for operation in ("run", "inspect"):
        item = simulations.add_parser(operation)
        item.add_argument("input", type=Path)
        item.add_argument("--sha256", required=True)
        item.add_argument("--json", action="store_true")
        if operation == "run":
            item.add_argument("--output-dir", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.domain in ("instrument", "waveform", "load", "thermal"):
        evidence = {
            "instrument": instrument,
            "waveform": waveform,
            "load": load_evidence,
            "thermal": thermal,
        }[args.domain]
        try:
            if args.operation == "import":
                value, ref = evidence.import_evidence(args.input, args.sha256, args.output)
                data = evidence.summary(value, ref)
                data["output"] = ref
                code = 0 if value["ok"] else 3
            else:
                value, ref = evidence.load(args.input, args.sha256)
                data = evidence.summary(value, ref)
                code = 0
            instrument_result = {
                "schema_version": "embedded-hil-runner." + args.domain + "-result.v1",
                "ok": code == 0,
                "operation": args.domain + "." + args.operation,
                "scope": "host_only_saved_" + args.domain + "_import",
                **evidence.FLAGS,
                "data": data,
            }
        except (HilError, OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            code = 2
            instrument_result = {
                "schema_version": "embedded-hil-runner." + args.domain + "-result.v1",
                "ok": False,
                "operation": args.domain + "." + args.operation,
                **evidence.FLAGS,
                "errors": [
                    {"code": getattr(error, "code", "INVALID_INPUT"), "message": str(error)[:1024]}
                ],
            }
        print(evidence.canonical(instrument_result).decode("ascii"), end="")
        return code
    if args.domain == "simulation":
        try:
            if args.operation == "plan":
                plan = simulation.compile_plan(args.spec)
                reference = simulation.json_new(args.output, plan)
                value = {
                    **simulation.FLAGS,
                    "ok": True,
                    "operation": "simulation.plan",
                    "component_processes_started": False,
                    "native_validation_performed": False,
                    "plan": reference,
                }
            elif args.operation == "run":
                value = simulation.run(args.input, args.sha256, args.output_dir)
            else:
                value = simulation.inspect_report(args.input, args.sha256)
            print(json.dumps(value, ensure_ascii=True))
            return 0 if value["ok"] else 1
        except (HilError, OSError, ValueError, KeyError, TypeError) as error:
            print(
                json.dumps(
                    {
                        **simulation.FLAGS,
                        "ok": False,
                        "operation": "simulation." + args.operation,
                        "errors": [
                            {"code": getattr(error, "code", "INVALID_INPUT"), "message": str(error)}
                        ],
                    }
                )
            )
            return 2
    if args.domain == "managed":
        try:
            if args.operation == "plan":
                value = result(
                    "managed.plan", data=compile_plan(args.spec, args.output, args.lease_root)
                )
                value["scope"] = "host_only_managed_preparation"
                print(json.dumps(value, indent=2))
                return 0
            return execute(
                args.plan,
                args.plan_sha256,
                args.confirm,
                args.output_dir,
                allow_runtime_reset=args.allow_runtime_reset,
            )
        except HilError as error:
            value = result("managed." + args.operation, error=error)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            value = result("managed." + args.operation, error=HilError("HOST_IO_ERROR", str(error)))
        print(json.dumps(value))
        return 2
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
