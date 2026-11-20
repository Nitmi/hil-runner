# Fixed ECB simulation suites

HIL Runner 0.21.0 accepts the exact Sim Runner 0.16.0 wheel inventory
(42 runtime files) for `nrf52840-ecb-v1`. Older selected profiles remain supported;
unselected future versions or extra wheel files are rejected. Compile/preflight
does not grant authorization or start a simulator. Execution keeps fail-stop,
zero retry, bounded output, owned child processes and observed cleanup.

The native profile uses the four public NIST SP 800-38A F.1.1 AES128 known-answer
blocks twice. Two fixed model perturbations start at stimulus index 4:
`plaintext-stuck` and `context-redirect`. HIL copies native nominal verdicts,
effect observations, errors, samples and 16 snapshots of 32 fields. An observed
fault remains a failed nominal regression; absent native assertions stay null.
The separate Trace adapter checks byte representations without rerunning AES or
the native firmware policy. Preserve raw sources when archiving a suite.

The selected Renode 1.17 ECB START callback is synchronous and ignores the written
bit. STOP and ERROR are not implemented. No decrypt, other cipher modes,
physical timing, interrupt/PPI routing, side-channel resistance, cryptographic
security or physical crypto hardware qualification is established. Use only
public fixture keys, never application secrets.

The development-only `scripts/accept_ecb_simulation.py` checks an installed
normal suite, two fail-stop fault suites and whole-suite preflight refusal.
Each native case requests 40 virtual ms; capture and host time/memory bounds
remain those of the hash-bound native plan. Evidence copying and inspection
scale with bounded file sizes; acceptance records warm inspection time and
Python allocation peaks separately from process startup and native wall time.
