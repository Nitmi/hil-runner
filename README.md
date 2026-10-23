# HIL Runner

Local **0.10.0** adds [saved analog waveform import](docs/waveform.md) for
lab-instruments 0.9.0 AD3 and SDS804X checks, preserving original bytes,
voltage metrics, failed/invalid verdicts and recorded JUnit verification.

The **0.9.0** release adds [offline instrument evidence import](docs/instrument.md):
preserve a native logic verification/JUnit result and its original inputs in one
hash-bound artifact, retaining failed and invalid evidence without hardware access.

The published [0.8.0 release](https://github.com/Nitmi/hil-runner/releases/tag/v0.8.0) adds the experimental sim-runner 0.7.0 ESP-EMU WASM
profile. Qualified outcomes, string UART provenance, opaque initial state,
unmeasured clock, budget exhaustion and null observations remain explicit in
[simulation suites](docs/simulation.md).

The [0.7.0 release](https://github.com/Nitmi/hil-runner/releases/tag/v0.7.0)
adds sim-runner 0.6.0 GPIO/TIMER0 fault reports.
It preserves native fault analysis and failed verdicts, including unknown effects
after a timeout. Successful injection does not make the suite pass or allow the
next case to run.

It also supports fixed Xtensa ESP32-S3 Flash suites, native core/clock
declarations and runtime identity alongside Renode GPIO/TIMER0 samples and
model snapshots with explicit coverage/time semantics. It retains ESP-IDF Flash plans and native
`passed_with_model_limits` verdicts and diagnostics in the separate [simulation suite](docs/simulation.md)
domain: fixed hash-bound sim-runner execution, all-case preflight, sequential
fail-fast cases and an offline Trace input. It never acquires a board lease,
falls back to hardware or requests confirmation per case. Existing lease and
managed hardware interfaces retain their native authorization and cleanup rules.

HIL Runner 0.2.0 provides cooperative ownership and managed native
flash/runtime execution. `lease` retains the host-only 0.1 interface described
below. Windows `managed` holds that ownership across one native bounded flash
session and per-build native runtime acceptance. An Agent can submit successive
firmware builds under one approved scope without asking for each flash again.
See [managed workflow](docs/managed.md) for its additional reset, exact input
bindings, process containment and evidence contract.

The purpose is to keep participating clients from resetting/flashing one board
while another client is observing it. The process holds OS file locks while it
is alive; PID files, stale timestamps and lock-file deletion do not grant
ownership. Runtime dependencies: none. Python 3.11+.

## Develop and use

Install a verified GitHub Release wheel in a dedicated Python 3.11+ environment;
see [release verification and installation](docs/installation.md). The wheel does
not install native components, switch Toolkit's station lock, or authorize a
board operation.

```powershell
uv sync --locked --extra dev
uv run --locked hil-runner --version
uv run --locked hil-runner lease plan selection.json --json
uv run --locked hil-runner lease serve selection.json `
  --selection-sha256 <hash-from-plan> `
  --duration-seconds 300 --idle-timeout-seconds 60
```

Plan reads at most 256 KiB of saved `embedded-board-registry.selection.v1` JSON,
validates its structure and exact observed transport identities, and reports
the selection hash, canonical lease root and resource keys. It creates nothing,
starts no component and does not revalidate the upstream registry/discovery
files or currently connected hardware. Serve requires that hash so a changed
selection fails before any lock files are created. No user confirmation prompt
is added: hashing and lock ownership are machine checks, not authorization.

Keep serve's stdin/stdout pipes open. Its first JSON line is `lease.open` and
contains a new `lease_id`. Only these requests are accepted, one per line:

```json
{"id":"1","operation":"lease.status","lease_id":"lease_<from-open>"}
{"id":"2","operation":"lease.close","lease_id":"lease_<from-open>"}
```

Successful status extends the **idle** deadline, never the maximum duration.
Malformed or stale requests do not renew ownership. Close, EOF, idle timeout,
duration expiry or request limits release host locks and exit. The terminal
JSON reports the reason and whether host handles closed; it never claims native
processes stopped or target cleanup succeeded. Use a parent process to keep this
lease alive throughout the separately authorized native operations and cleanup.
Do not close/kill the lease before those operations have ended.

## Identity and namespace

- Exact debug probe `VID:PID:serial` maps to `usb:VID:PID:SERIAL`.
- Serial maps to the exact observed COM port (or canonical absolute Unix port)
  plus the same USB key when complete VID/PID/serial fields are present. Partial
  USB identity is rejected. Matching USB serial and debug interfaces conflict
  even if one client selects debug only and another serial only.
- BLE requires an observed MAC or UUID, not a name. It maps to `ble:IDENTIFIER`.
  Private address rotation and aliases are not inferred.
- USB and BLE hexadecimal/case variants normalize conservatively. Case folding
  unusual USB serials can over-lock distinct devices; it avoids missing a conflict.
- Logical board names, USB interface numbers and debug core/target do not split
  ownership of one physical USB device. All resources are acquired in fixed
  order with no wait/retry; partial acquisition is rolled back on any conflict.

All participants must use the **same local lease root**. Defaults are
`%LOCALAPPDATA%\embedded-hil-runner\leases` on Windows and
`${XDG_STATE_HOME:-~/.local/state}/embedded-hil-runner/leases` on Unix. Override
with `--lease-root` for an explicitly shared station namespace. Network/UNC
roots are unsupported; mounted network filesystems are also outside the tested
scope. Cross-user ACL setup and distributed device farms are not implemented.

Lock files remain after close and process death. They contain no owner record;
their existence does not mean busy. Never remove, rename, replace or hard-link
these files/root while clients run: different inodes can defeat cooperation.
Live status and periodic checks detect namespace replacement, but this is not
protection against a malicious process with access to the directory.

Native tools and clients that do not participate are not blocked by these
locks. A crashed lease process cannot clean up an independently running native
tool or prove a board safe. A new owner must perform fresh native identity,
state and cleanup checks before hardware operations. This coordination layer
does not bypass native device locks, bounded flash sessions or dangerous-action
gates. It does not add per-flash user approval.

Two disjoint transport selections may still describe one board behind separate
USB adapters. Use the same complete multi-transport selection across cooperating
clients; this stage cannot infer that physical topology from a board label.

## Protocol, testing and delivery

See [protocol](docs/protocol.md) and `schemas/result.schema.json`.

```powershell
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build --no-build-isolation
```

Tests use synthetic selections and real independent host processes; no hardware
access is required. CI is configured for Windows/Ubuntu, Python 3.11/3.13.
Managed native execution is Windows-only; Unix supports cooperative host leases.
Remote checks must pass before a release is published.
Managed tests require explicit native Replay settings and a compiled host-only
baud fixture; the ordinary suite skips those integrations. Local Replay and fake
UART results do not qualify physical boards. GitHub Releases deliver wheel and
source archives with SHA-256 and tag-bound GitHub attestations. The current
delivery does not include a standalone binary, Toolkit catalog integration,
power control, daemon/socket or remote lease broker.

OS primitives follow the Python documentation for
[Windows nonblocking region locks](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking)
and [Unix flock](https://docs.python.org/3/library/fcntl.html#fcntl.flock).
