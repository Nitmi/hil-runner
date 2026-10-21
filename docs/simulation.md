# Simulation suites

HIL Runner 0.3.0 adds an optional simulation domain independent of hardware
leases and managed flash sessions. It coordinates fixed sim-runner 0.2.0
`inspect-plan`, `run` and `inspect-report` commands. sim-runner remains responsible
for model/runtime identity, firmware assertions, emulator deadlines and cleanup.
No commands, arbitrary argv, Python scripts, shell, physical board selection,
recovery/retries or authorization grants are accepted in a simulation spec.

Prepare native Renode or QEMU plans with sim-runner. Select a trusted Python
3.11+ interpreter and the hash-bound `embedded-sim-runner` 0.2.0 wheel. All inputs
below are local regular files. Agent-generated hashes bind inputs and require
no manual per-run confirmation. Paths in a spec may be absolute or relative
to its own directory. Cases have unique portable IDs and run in declared order.

```json
{
  "schema_version": "embedded-hil-runner.simulation-spec.v1",
  "python": {"path": "D:/work/venv/Scripts/python.exe", "sha256": "<interpreter-sha256>"},
  "sim_runner_wheel": {"path": "D:/work/embedded_sim_runner-0.2.0-py3-none-any.whl", "sha256": "<wheel-sha256>"},
  "cases": [
    {"id": "build-a", "plan": {"path": "native-a.json", "sha256": "<native-plan-sha256>"}},
    {"id": "build-b", "plan": {"path": "native-b.json", "sha256": "<native-plan-sha256>"}}
  ],
  "timeout_seconds": 180
}
```

```powershell
hil-runner simulation plan suite.json --output suite-plan.json --json
hil-runner simulation run suite-plan.json --sha256 <suite-plan-sha256> --output-dir 'D:/work/new suite' --json
hil-runner simulation inspect 'D:/work/new suite/report.json' --sha256 <report-sha256> --json
embedded-trace correlate 'D:/work/new suite/trace-input.json' --output timeline.json --json
embedded-trace report timeline.json --sha256 <timeline-sha256> --output report.md --json
```

Planning reads/binds inputs without starting a process. It does not fully
validate native runtime/firmware/model state: `native_validation_performed=false`
is explicit. Run requires a new output directory and checks every native plan
through sim-runner before starting the first emulator. A failed preflight leaves
all cases `not_run`. Then each case runs exactly once, its stdout verdict must
match the saved native report, and native report inspection must succeed.
Any failed/indeterminate case stops the suite; later cases remain `not_run`.
Exit 0 is a passing suite, exit 1 a saved failed suite, exit 2 an invalid request
or a host error that prevented normal result generation. Always retain output.

The wheel is never imported in HIL's process or installed into system Python.
Its 13 audited package filenames are checked, hash-bound and staged into a private
directory; unexpected packages, paths, links or runtime dependencies are rejected.
The fixed child command is isolated Python `-I -S -B`, loading only this staged
package ahead of the interpreter's standard library. No PYTHONPATH, user/site
startup hooks or `.pth` files are used. The interpreter executable is hash-bound;
its complete standard library/native DLL distribution is trusted host software,
not independently pinned here. This is not a security sandbox for hostile wheels,
firmware or native runtimes. Select the verified local/release artifacts.

Execution is Windows-only, using existing suspended-start/kill-on-close Jobs.
The suite's fixed Python children and descendant emulators remain owned until
observed stopped. Per-call deadline is 1..600 s, defaulted explicitly in the spec;
include runtime inventory hashing overhead as well as native execution time.
Child stdout/stderr caps are 16/1 MiB. Native sim-runner retains its own CPU/model,
output, host-time and memory budgets. A Job kill proves host process exit, not
physical target cleanup. Startup uncertainty keeps cleanup unverified.

The suite accepts 1..8 cases. It saves the selected spec/plan, staged package,
native plans, raw CLI output and a calls journal, native reports/inputs/UART and
partial files. It does not overwrite an existing run. `simulation inspect` checks
saved artifact bytes, case/native verdict bindings and stop order without
launching processes or reopening the original interpreter/runtime paths. This
is local integrity verification, not authenticity or independent CPU execution.

`trace-input.json` names completed, natively inspected reports, including failed
captures. An indeterminate attempt with no valid report cannot become a fabricated
Trace source; its partial evidence and `execution_attempted` state remain in the
suite report. Trace 0.3.0 reads these files offline, preserves recorded failures,
labels UART as simulation and uses host run windows. Its import/report exit zero
must not override HIL/native failure. Gate CI on `simulation run` and upload all
evidence/report artifacts even when that command fails. No physical acceptance
or hardware authorization can follow from a simulated pass.
