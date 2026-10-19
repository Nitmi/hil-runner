# Managed flash and runtime acceptance

This Windows workflow coordinates one native `flash session serve` and its
runtime acceptance children while holding cooperative debug/serial ownership.
The native debugger performs all target operations and serial observations.
HIL Runner has no arbitrary-command, erase, recover or automatic-retry endpoint.

## Prepare the run

Save an exact board-registry debug + serial selection, a Toolkit component lock,
a native bounded flash scope, and a native runtime contract template. The scope
must bind the same debugger executable, probe, target and firmware directory.
This stage snapshots self-contained BIN or HEX files. ELF and ESP-IDF image sets
are not supported by managed execution yet.

The runtime template requires exact serial port/USB identity, zero transmitted
bytes, READY, a complete HEARTBEAT line/count, and native cleanup. Each submitted
build changes only `firmware.sha256` and `serial.build_id_line`. Native inspection
validates the full contract before execution. The HEARTBEAT assertion counts
matching complete lines; it does not establish monotonic sequence numbers.

Write a spec using `schemas/managed-spec.schema.json`, for example:

```json
{
  "schema_version": "embedded-hil-runner.managed-spec.v1",
  "selection": "selection.json",
  "component_lock": "component-lock.json",
  "native_scope": "flash-scope.json",
  "native_confirm_digest": "<digest-returned-by-native-scope-plan>",
  "runtime_template": "runtime-template.json",
  "replay_fixture": null,
  "limits": {
    "duration_seconds": 300,
    "idle_timeout_seconds": 60,
    "native_timeout_seconds": 30,
    "startup_timeout_seconds": 10,
    "shutdown_timeout_seconds": 5
  }
}
```

Paths in the author spec resolve relative to its file. `managed plan` hashes the
saved inputs and all locked components without starting executables or accessing
hardware. It writes a new plan; it does not grant authorization or extend the
native scope. Use one local lease root for all cooperating clients.

```powershell
hil-runner managed plan spec.json --output managed-plan.json --json
hil-runner managed serve managed-plan.json `
  --plan-sha256 <plan-file-sha256> `
  --confirm <once-approved-native-scope-digest> `
  --allow-runtime-reset --output-dir <new-directory-inside-native-firmware-root>
```

Approve the whole bounded run once, including native flashing and one **additional
runtime reset-capture per build**. Runtime acceptance opens the serial observer,
resets/captures/restores the target through the native debugger, then checks its
READY/BUILD/HEARTBEAT evidence. `--allow-runtime-reset` records that startup scope;
it is not a per-build prompt. Plan hashes and input checks are machine checks.
Existing native authorization limits, write/erase windows, UICR exclusions and
the permanent `.active` one-use marker remain enforced by the debugger.

Keep a parent process connected to stdin/stdout. After `managed.ready`, submit
one JSON object per line using absolute paths and current hashes:

```json
{"id":"A","operation":"build","firmware":"D:\\build\\A.hex","firmware_sha256":"<sha256>","runtime_contract":"D:\\build\\runtime-A.json","runtime_sha256":"<sha256>"}
{"id":"done","operation":"close"}
```

Wait for `managed.build` before submitting the next build. The runner makes
private firmware/contract snapshots, uses those for native execution, and binds
the returned evidence to their hashes. Different firmware hashes cannot reuse
one reported BUILD line. Input drift, failed acceptance, malformed requests,
deadline expiry or incomplete cleanup ends the run, with no hardware retry or
recovery. Count exhaustion closes automatically; EOF and idle expiry close the
native owner before releasing leases. A new run needs a fresh native scope.

## Local DK qualification

On 2026-10-19, one physical A/B run passed on the nRF52840 DK onboard target
with external SWD disconnected. The installed 0.2.0 wheel and candidate debugger
0.2.5 used J-Link `1366:1061:001050275757`, target `nRF52840_xxAA`, and COM11
at 115200, DTR=true, RTS=false, zero transmit. Both 638-byte Code Flash images
verified, with the same first 4 KiB erase window and no UICR image bytes.

One native owner handled both builds without per-build confirmation or retry.
Each native runtime acceptance observed READY and the corresponding BUILD line;
independent Base64-byte reconstruction found 29 complete heartbeats after READY
for each build. Native heartbeat totals were 31, including two startup lines
before READY: native totals alone do not establish the post-READY count. The
client and all nine managed child processes exited normally, the native quota
reached zero and cooperative leases were released after process exit.

The subsequent debugger 0.2.5 candidate at `80db27e` tightens native acceptance:
BUILD and heartbeat counts come only after the last complete READY. Earlier
startup/boot counts remain visible in `assertions.readiness_window` but cannot
satisfy acceptance; forbidden lines still cover the full capture. Replaying the
unchanged A/B receive bytes through that predicate gives 29 qualifying
heartbeats and two exclusions each. This is an offline re-evaluation, not a
second physical run with the new executable. Distinguish local candidates by
source revision and archive/executable hashes, not their shared 0.2.5 version.

See the [fixture and fixed A/B client](../examples/nrf52840-dk/README.md).
This qualifies this Windows/DK fixture; it does not establish post-disconnect
CPU state, other boards, generic serial firmware or remote CI provenance.

## Ownership, deadlines and evidence

Windows children start suspended, enter a kill-on-close Job, and resume only
after assignment. Descendants inherit containment. The runner waits for every
managed process tree to stop before releasing leases. Owner death closes Job
handles; surviving children are terminated by Windows. This stops host processes
and does not prove that a physical target resumed or a serial control line stayed
unchanged. A subsequent owner must check target state through native tools.

Runtime dependencies: none; Python 3.11+. Windows managed execution is the local
verified platform. Official debugger 0.2.5 is the qualified runtime version: 0.2.4
can hang after polling a Windows monitor exit and then waiting on its notification
again. Its official Windows ZIP SHA-256 is
`835bb47a5b1c536395a7ca1382873fea460f5c035069b6be9b3c928ee06fa17c`,
with executable SHA-256
`e83f4483f07d63630cb90dd964b6eab1b619d4de8b1ba1c7e69f9a677119cb2d`.
The runner's deadline contains the old failure, but cannot turn it into a
successful acceptance. Other native versions need qualification.

Inputs are rehashed before each executable start. Native stdout/stderr, requests,
native transcript, flash/runtime evidence and private snapshots remain in the new
run directory. Final `managed-result.json` reports completion, remaining native
quota, per-process cleanup and lease closure. A force-terminated child makes the
run fail even when the process tree stopped. A native transcript is compared with
captured bytes, including newlines. Capture sizes, queues, requests and process
waits are bounded.

`authorization_granted` and top-level `target_cleanup_verified` remain false:
ownership is not authorization and host containment is not target verification.
Successful build results point to complete native target cleanup evidence. These
are separate claims. `hardware_access_possible` becomes true after dispatch,
including Replay: Replay only substitutes the debug backend, and a real baud
executable could still open a real serial port.

For host-only native integration tests, explicitly supply a pinned debugger,
its version/hash and Replay fixture:

```powershell
$env:HIL_NATIVE_DEBUGGER_TEST_EXE = '<qualified-native-debugger.exe>'
$env:HIL_NATIVE_DEBUGGER_TEST_SHA256 = '<sha256>'
$env:HIL_NATIVE_DEBUGGER_TEST_VERSION = '0.2.5'
$env:HIL_NATIVE_REPLAY_FIXTURE = '<embedded-debugger-repo>\examples\replay\stm32g4.json'
uv run --locked pytest tests/test_native_managed.py
```

Tests compile a std-only Rust baud fixture with synthetic COM999/FFFF:0001
identities and no hardware API. `rustc` is a test dependency only. No implicit
fallback to a real serial executable or probe is allowed. The integration covers
A/B under one native grant, wrong BUILD or insufficient post-READY heartbeats
blocking B, hung descendants, ownership
conflicts, EOF and abrupt owner death. The limited physical qualification is
recorded above; these automated integrations remain host-only.
