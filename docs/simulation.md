# Simulation suites

## Experimental ESP-EMU WASM in 0.8.0

HIL Runner 0.8.0 also accepts the fixed sim-runner 0.7.0 wheel
and `esp32c3-wasm-flash-v1` plan. All older supported profiles remain available
with the new inventory. Node/runtime/firmware limits and assertion policy stay
in sim-runner; all cases pass native preflight before any emulator starts.

WASM successes remain `passed_with_model_limits`. Cases copy `model_limits`,
`initial_state`, `runtime_observation`, `assertions` (including null), the
unmeasured `virtual_time` and all native errors. `uart.bin` contains the ASCII
subset of WASM API strings encoded as UTF-8, not verified original UART bytes.
The requested instruction upper bound and model cycle/clock claims are not
retired instruction counts or measured timing. A guest restart request stops
execution without performing a restart; instruction-budget exhaustion fails.

The four fixed `component/` files and host `.mjs` are hash-bound in suite
evidence. No other nested native paths are accepted. Failed/unknown results
stop later cases, with partial evidence and host-process cleanup retained.
Installing this component does not activate Toolkit/station or grant hardware access.

## GPIO/TIMER0 fault evidence

With sim-runner 0.6.0, select the native `nrf52840-gpio-timer-fault-v1` plan.
Its fixed selections are `none`, `gpio-stuck-low`, `gpio-stuck-high`, `timer-stop`
and `timer-irq-mask`. A selection is an input to the model; it does not prove a
physical fault or root cause. Plan all-case preflight remains mandatory.

Cases retain `fault_scenario`, `fault_scope`, `fault_request`, `fault_evidence`
(the complete native assertions or null), `native_errors`, `virtual_time` and
`gpio_evidence`. The request records a virtual injection boundary of 22 ms;
paused observations at 20/40/60/80 ms include TIMER0 counter and interrupt enable.
These requested boundaries and guest samples are distinct from host windows,
measured timing and electrical waveforms.

Only native sim-runner evaluates the nominal regression and effect. An observed
injection with a failed nominal test remains `failed`, exits nonzero and stops
later cases. A timeout without evaluated assertions stays null/unknown, while
its raw partial artifacts remain saved. Inspection checks summaries against the
saved native report, without launching a component or rerunning policy.

Development-only `scripts/accept_fault_simulation.py` exercises installed HIL
and Trace wheels against native plans, including negatives, all-case preflight,
filtered views, mutation rejection and process cleanup. It never accesses boards.

HIL Runner 0.7.0 provides the optional simulation domain independent of hardware
leases and managed flash sessions. It coordinates fixed sim-runner 0.2.0 through 0.6.0
`inspect-plan`, `run` and `inspect-report` commands. sim-runner remains responsible
for model/runtime identity, firmware assertions, emulator deadlines and cleanup.
No commands, arbitrary argv, Python scripts, shell, physical board selection,
recovery/retries or authorization grants are accepted in a simulation spec.

Prepare native Renode or QEMU plans with sim-runner. Select a trusted Python
3.11+ interpreter and the hash-bound `embedded-sim-runner` wheel. Flash plans require
0.3.0 or newer supported wheels; GPIO/TIMER0 requires 0.4.0 through 0.6.0;
ESP32-S3 requires 0.5.0 or 0.6.0; GPIO/TIMER0 faults require 0.6.0. Renode/UART and QEMU/RAM plans retain
0.2.0 compatibility. All inputs
below are local regular files. Agent-generated hashes bind inputs and require
no manual per-run confirmation. Paths in a spec may be absolute or relative
to its own directory. Cases have unique portable IDs and run in declared order.

```json
{
  "schema_version": "embedded-hil-runner.simulation-spec.v1",
  "python": {"path": "D:/work/venv/Scripts/python.exe", "sha256": "<interpreter-sha256>"},
    "sim_runner_wheel": {"path": "D:/work/embedded_sim_runner-0.5.0-py3-none-any.whl", "sha256": "<wheel-sha256>"},
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

A native `passed_with_model_limits` is successful but qualified. The case keeps
that exact status, native `model_diagnostics`, `model_coverage_complete=false`
and `security_features_verified=false`. Remaining cases may run; any limited
success makes the successful suite `passed_with_model_limits`. Failed cases
still stop execution. Inspection rejects flattened case or suite verdicts and
changed model-limit summaries. Inspect success establishes saved consistency,
not CPU execution, report authenticity or physical coverage.

The wheel is never imported in HIL's process or installed into system Python.
Its version-specific 13 (0.2.0), 16 (0.3.0), 18 (0.4.0), 20 (0.5.0), 21 (0.6.0),
24 (0.7.0) or 26 (0.8.0) audited package filenames are checked, hash-bound and staged into a private
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
suite report. Trace 0.6.0 reads these files offline, preserves recorded failures
and `succeeded_with_model_limits` outcomes with their native diagnostics,
labels UART as simulation and uses host run windows. Its import/report exit zero
must not override HIL/native failure. Gate CI on `simulation run` and upload all
evidence/report artifacts even when that command fails. No physical acceptance
or hardware authorization can follow from a simulated pass.

For `nrf52840-gpio-timer-v1`, prepare native sim-runner 0.4.0 or 0.5.0 plans and select
that wheel. Each case retains `gpio_evidence.samples` and
`gpio_evidence.model_observations` from native assertions, including null on a
failed run without evaluated assertions. It also keeps
`model_coverage_complete=false`, `physical_timing_verified=false` and the native
GPIO / timer observation semantics. A plain native `passed` means the fixed
digital scenario passed, not full GPIO/timer/electrical coverage. Native report
inspection owns the GPIO/IRQ policy; HIL only checks the saved summary matches it.
Unexpected missing summaries or changed semantics fail. No UART line, snapshot
or timer tick becomes a physical-board claim or host timestamp.

Trace 0.6.0 preserves this context in inspect/query/Markdown, and binds paused
model observations to byte spans in raw backend stdout during offline import.
Those RunFor boundary labels, guest TIMER captures and host run windows remain
distinct. Native failed cases stop later builds even when Trace import succeeds.

For `esp32s3-idf-flash-v1`, select native sim-runner 0.5.0 plans with the separate
`espressif-qemu-xtensa` runtime; C3 RISC-V plans keep their own backend. S3 cases
retain `backend`, `backend_version`, `runtime_archive_sha256`, `virtual_time` and
`app_core_markers` from native evidence. Unmeasured device clock metadata stays
`domain=qemu_device_clock_unmeasured`, `elapsed_ns=null`, `budget_enforced=false`;
it cannot be relabelled as C3 icount time. Unevaluated core markers remain null.
HIL does not rerun CPU/core/readiness policy. Native limitations and diagnostics
remain attached to both success and failure summaries. Sequential qualified
passes can continue without another approval; a failure still stops the suite.
Parent timeouts retain S3 ROM, private Flash/eFuse and partial logs when present,
without inventing a native report or Trace source. Trace 0.6.0 keeps identity,
clock/core declarations and model limits visible even in filtered queries.

## Sensor evidence

HIL 0.13 selects only the exact 26-file sim-runner 0.8.0 wheel for native
`embedded-sim-runner.sensor-plan.v1`, profile `nrf52840-i2c-sensor-v1`.
Earlier supported profiles remain usable with their versioned inventories.
Prepare the native plan first, then use the same hash-bound suite commands above.
No new hardware permission or per-case approval is introduced.

The fixed scenario uses Renode TWI0, TMP103 register 0 at address 0x48 and a
guest TIMER0 IRQ. Native plans request 82 virtual milliseconds, including four
paused model observations. HIL retains complete `sensor_evidence`, signed-byte
samples, fault request (`none`, `temperature-stuck`, `temperature-offset`),
effect/nominal outcomes, native errors and clock declarations. Unevaluated
assertions remain null. Observing an injected effect does not turn a failed
nominal regression into a passing suite or allow the next case to run.

Native inspect owns firmware/readiness/sensor policy. HIL checks its saved
projection without implementing that policy again. Trace 0.13 imports the
native reports and preserves raw model stdout spans, including negative readings,
in full, filtered and empty views. These are model properties and guest-reported
register bytes, not calibrated temperature or an I2C electrical measurement.
`model_coverage_complete`, `physical_timing_verified`, `sensor_accuracy_verified`
and `i2c_electrical_behavior_verified` remain false. Requested virtual boundaries,
guest 250 kHz captures and host UART windows remain distinct.

Limits remain eight cases, 1..600 seconds per child call, 16 samples and four
model observations per sensor report. Offline inspection hashes all artifacts
before validating summaries; page size does not reduce verification cost.
`scripts/accept_sensor_simulation.py` is a development-only installed-wheel
acceptance harness, with sequential successes, faults, timeout, mixed profiles,
preflight rejection and coherently rehashed summary-tamper checks.
