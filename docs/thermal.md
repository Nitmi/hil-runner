# Saved thermal evidence

Version 0.12 adds independent `thermal import/inspect` for lab-instruments0.11
saved thermal check/JUnit verification. No camera/helper, vendor library,
subprocess or native temperature conversion is used by this domain.

The import manifest has exactly `schema_version` set to
`embedded-hil-runner.thermal-spec.v1`, recorded `native_exit_code` (0 or 3),
`inputs` and ordered `source_files`. The five primary inputs are `report`,
`spec`, `capture`, `native_result` and `junit`; each selects one portable relative
`path` and lowercase `sha256` under the manifest directory. Select unchanged
stdout of native `thermal junit` as native_result, its XML as junit, and the
native thermal check report, spec and original thermal-result.json explicitly.

Each source_files item has exactly `name,path,sha256`. Its name is the original
artifact's top-level or `native/` relative name, as in the native check report's
`input_files` after the first `capture` entry. Preserve this order. Select every
artifact, including plan, CSV, raw Y16/warmup frames, GET payloads, native source
inventory, completion and any empty stdout/stderr. Missing and empty differ.
No saved path label is followed or guessed; input files may live at explicitly
selected relocated paths. Case-folded aliases, duplicate file identities,
links/reparse points, path traversal and existing outputs are rejected.

For example, a source entry is
`{"name":"native/frame-0000.y16","path":"capture/native/frame-0000.y16","sha256":"<hash>"}`.
Use the full native inventory, not only the selected ROI/frame's files.

```powershell
hil-runner thermal import import.json --sha256 '<manifest hash>' --output new-bundle.json --json
hil-runner thermal inspect new-bundle.json --sha256 '<bundle hash>' --json
```

Import exits 0 for a passing verdict or 3 for a complete failed/invalid verdict,
still saving the bundle. Input/consistency/output failures exit2 without an output.
Inspect exits0 for successful processing even when `data.verdict_ok=false`.
Save bundles outside the selected capture directory; writing inside it is rejected
before reading the remaining inputs, to preserve the native artifact inventory.
The bundle is self-contained; original source locations are unnecessary to inspect.

## What is checked

The `embedded-hil-runner.thermal-report.v1` embeds all selected original bytes,
sizes, hashes and path labels. Import/inspect validate native report/spec/capture
bindings, exact source inventory, recorded source/cleanup/errors/qualifications,
frame hashes/layout/timestamps/telemetry references, ROI windows/raw spans,
valid/invalid counts, recorded temperature comparisons and trend arithmetic.
The original raw buffers, radiometry settings, units and controls remain intact.
Canonical native JUnit is reconstructed and compared byte for byte, with failures
and invalid evidence kept as failure/error, never skipped. Native exit and XML
counts must match the global verdict. Unknown versions or impossible verifier
pairs fail instead of silently downgrading.

This is recorded consistency, not a fresh native TLinear conversion, pixel-mask
or temperature-statistic computation. Native verification is unsigned historical
data: `native_recomputation_recorded=true`, `native_recomputed_now=false`,
`native_temperature_conversion_performed=false`, `source_execution_performed=false`.
Hashes do not authenticate a coherent fabricated set or establish a physical camera.

Recorded means can round one binary floating-point unit outside equal min/max
after native fsum/division. Only that internal statistic consistency check permits
one adjacent float. User assertions retain the exact native inclusive comparisons;
their bounds are never expanded.

Delivered buffer windows, duplicate-counter rules, FFC/effective-gain/resolution/
valid-mask trend qualifications and sensor uptime remain separate from host/Media
Foundation time. A requested but unavailable trend is invalid evidence. Invalid
pixel budgets and partial unscored rows remain explicit. An entire failed source
keeps native errors and unknown cleanup, and none of its partial frames is scored.

All physical-device/DUT identity, calibration, radiometric accuracy, scene
parameters, junction temperature, physical clock, authorization and execution
claims remain false. Values are apparent surface temperatures, not chip junction
temperature. Comparing maximum temperatures across frames does not track one
physical point or infer heating rate, causality or cross-device alignment.

## Limits and development

Manifest <=256KiB. Five inputs: report/capture/XML <=1MiB each, spec <=64KiB,
native stdout <=128KiB. Capture plus 1..100 source artifacts share a16MiB budget;
each artifact <=1MiB, with zero bytes permitted only for ancillary sources.
At most106 explicit file reads, each once. Bundle <=32MiB, JSON depth32. Runtime
checks are stricter than shape schemas. Base64, JSON/canonical copies and full
source projection cost extra memory/time; byte limits are not RSS guarantees.
Import/inspect always process all evidence, regardless of later Trace filters.

`examples/thermal/fixtures.zip` holds11 native synthetic cases as unchanged files:
passing, failed, missing-window, mixed, invalid-pixel, mask drift, FFC change,
duplicate frames, failed source, unknown cleanup and no valid ROI pixels.
It is a development fixture archive, not a runtime auto-extraction feature.
Tests/smoke unpack bounded known entries into temporary output only. No real
temperature reference, UVC ABI or hardware behavior was qualified.

Thermal accepts lab producer/verifier0.11 and HIL producer0.12. Existing digital,
waveform and load formats stay independent. Digital verifier0.11 accepts native
producers0.7..0.11; waveform0.11 accepts0.9..0.11; load0.11 accepts0.10/0.11.
Older supported verifiers keep their original narrower matrices, including
load verifier0.10 only with producer0.10. Preserve actual versions and bytes.
