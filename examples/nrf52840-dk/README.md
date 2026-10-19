# nRF52840 DK A/B managed-execution fixture

Host-only build preparation for a DK **onboard** nRF52840, using its J-Link and
application UART on P0.06. Disconnect external SWD wiring before a physical test.
This example does not discover, attach, flash, reset or open a serial port.

```powershell
python examples/nrf52840-dk/build.py --output D:\new-run\firmware --target-dir D:\new-run\cargo
```

The existing Rust `thumbv7em-none-eabihf` target and `llvm-tools` are required.
Cargo is offline/locked, and both destinations must be new. The build produces
distinct A/B ELF and HEX files, input hashes, a compiler record, and a manifest.
It rejects noncontiguous images, invalid vectors, overlap, checksum errors and
any image byte outside Code Flash `0x00000000..0x00000FFF`. Expected erase impact
is exactly that 4 KiB page. No UICR section or NVMC operation is present.

Firmware emits exact complete lines at 115200 8N1, no flow control:

- `HIL_NRF52840_DK_READY v1`
- `HIL_NRF52840_DK_BUILD v1 A|B <source-input-and-variant-sha256>`
- `HIL_NRF52840_DK_HEARTBEAT` periodically

The build line correlates source inputs/variant; it is not cryptographic binary
attestation. Bind the independent HEX SHA-256 through the native flash scope and
managed runtime metadata. There are no receive commands, radio or actuator
outputs. The fixture uses the qualified embedded-debugger smoke UART setup.
At boot it writes the volatile development register APPROTECT.DISABLE
(`0x40000558 = 0x5A`) so compatible development-provisioned nRF52840 revisions
retain debug access; it never provisions UICR or guarantees an unknown chip's
protection state. Stop on protected/indeterminate access; do not recover as part
of this test.

DK USB Serial Port 0 requires DTR=true; RTS stays false and the host transmits
zero bytes. Resolve the current COM port/USB identity before authoring contracts.
Do not put `MI_00` in a native runtime contract if baud reports `interface=null`;
preserve the independent Windows PnP mapping as supplementary evidence and bind
the exact COM port plus VID/PID/serial in the native guard.

A real run needs its own reviewed native bounded scope, exact target/identities,
and task authorization including the per-build extra runtime reset-capture.
Prepare all inputs first; approve the scope once, never separately for A and B.
This build example alone is not physical acceptance or authorization.

`accept.py` is the fixed A/B client for a fully prepared run directory. It uses
the installed HIL Runner, checks Windows COM11/MI_00, submits B only after A's
completed runtime acceptance, and records bounded process cleanup. It requires
the managed plan hash plus the user's one-time native scope confirmation:

```powershell
python examples/nrf52840-dk/accept.py --root D:\prepared-run --plan-sha256 <hash> --check
python examples/nrf52840-dk/accept.py --root D:\prepared-run --plan-sha256 <hash> --confirm <approved-scope>
```

`--check` starts no process and makes no hardware access. Physical execution
creates a client one-use marker in addition to the native scope marker. Failed
or uncertain attempts must not be retried by deleting either marker.
