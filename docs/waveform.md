# Saved analog waveform evidence

Local 0.10.0 imports lab-instruments 0.9.0 `waveform junit` records. It opens
only explicitly selected local saved files, and never connects to instruments,
loads a vendor SDK, controls an output or runs a decoder. Existing `instrument`
digital checks, managed execution and simulation domains remain independent.

First run native `waveform check`, then `waveform junit` against the original
hash-bound report/spec/capture. Preserve their stdout and exit code. Both return
3 for complete failing checks; invalid evidence remains a JUnit error.
Create an import manifest with exactly:

```json
{
  "schema_version": "embedded-hil-runner.waveform-spec.v1",
  "native_exit_code": 0,
  "inputs": {
    "report": {"path": "report.json", "sha256": "<hash>"},
    "spec": {"path": "spec.json", "sha256": "<hash>"},
    "capture": {"path": "capture.json", "sha256": "<hash>"},
    "native_result": {"path": "native-result.json", "sha256": "<hash>"},
    "junit": {"path": "junit.xml", "sha256": "<hash>"}
  },
  "source_files": []
}
```

For AD3, `source_files` is empty: channel-major f64 bytes are embedded in the
capture. For SDS804X, explicitly list every ancillary native `input_files`
entry, in recorded order, as `{name,path,sha256}`. The primary capture is already
selected above; do not list it twice. Include plan, transcript, wire tx/rx,
channel preambles, WORD data and CSV. Native zero-byte wire responses are valid
and preserved. Paths are portable relative to the manifest, without traversal;
source names follow native fixed patterns. No path inside a recorded report is
followed. A hash is an integrity binding, not an authorization prompt.

```powershell
python -I -B -m hil_runner waveform import import.json --sha256 <hash> --output new-bundle.json --json
python -I -B -m hil_runner waveform inspect new-bundle.json --sha256 <hash> --json
```

Import checks explicit bytes, native input inventory, report/spec/verification
bindings, metric-bound comparisons, recorded source metadata and canonical native
JUnit bytes. It preserves all six metrics, sample windows, raw byte spans,
source cleanup/freshness and conversion metadata. It does not recalculate voltage
samples, parse binary descriptors or replay SCPI. `native_recomputation_recorded`
is true and `native_recomputed_now` is false. Unsigned native stdout is a recorded
claim; neither a hash nor consistent XML authenticates a historical execution.

The self-contained artifact can be inspected after originals are unavailable.
Import returns 0 for passed checks, 3 for complete failed checks and 2 for input,
consistency or output errors. Inspect returns 0 for valid processing even if the
stored test failed. Always read `verdict_ok`, `summary` and JUnit errors/failures.
Existing destinations are rejected before input reads. Import never repairs or
retries acquisition. Included examples are synthetic, not physical qualification.

There are at most eight checks and 16,384 samples per window. V1 accepts DC
coupling only; missing channels, oversized windows and AC/GND coupling retain
`invalid_evidence`. RMS includes DC; AC RMS removes only the population mean.
Calibration, bandwidth, clipping absence, clock alignment, DUT identity, UTC
sample origin and authorization remain unverified/false. Sample-relative times
must not be merged into a host-clock timeline as synchronized observations.

Bounds: manifest 512 KiB, report/capture/XML 1 MiB each, native stdout 128 KiB,
native spec 64 KiB; up to 1,615 native capture/source files, 1 MiB each and 8 MiB
in aggregate. Including the primary report/spec/response/XML and import manifest,
there are at most 1,620 distinct selected files and 11,206,656 bytes. Each file
is read once per import. Duplicate paths/file identities, links and reparse
points fail. Self-contained output is separately capped at 20 MiB, so excess
path/metadata/base64 overhead can still make otherwise bounded inputs fail.
JSON depth is 32. All embedded source bytes are rechecked on inspect; source
paths are not reopened (`source_files_rechecked=false`). Cost scales with the
whole source set, not the number of displayed checks. JSON/base64 copies and
XML construction add allocations; these limits are not RSS guarantees.
