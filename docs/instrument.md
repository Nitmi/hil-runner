# Offline instrument evidence

Local 0.9.0 imports a completed lab-instruments 0.8.0 `logic junit` result.
It binds the original report/spec/capture, native CLI JSON and JUnit XML into one
self-contained HIL artifact. Acquisition, decoding and assertion recomputation
remain in lab-instruments. This domain does not acquire a board lease, launch a
component, load its Python package, enumerate devices or perform measurement.
No runtime dependency or per-operation authorization is added.

## Prepare native evidence

Use lab-instruments `logic check` and `logic junit` with explicit original inputs
and hashes. Preserve the JSON stdout, exit code and new XML from the latter.
Supported report producers are 0.7.0/0.8.0, with verifier 0.8.0. Exit 0 means all
checks passed; exit 3 means a completed failing report. Native exit 2 or an absent
completed verification cannot be imported as a test result.

Prepare an `embedded-hil-runner.instrument-spec.v1` JSON with exactly:

```json
{
  "schema_version": "embedded-hil-runner.instrument-spec.v1",
  "native_exit_code": 0,
  "inputs": {
    "report": {"path": "report.json", "sha256": "<sha256>"},
    "spec": {"path": "spec.json", "sha256": "<sha256>"},
    "capture": {"path": "capture.json", "sha256": "<sha256>"},
    "native_result": {"path": "native-result.json", "sha256": "<sha256>"},
    "junit": {"path": "results.xml", "sha256": "<sha256>"}
  }
}
```

Replace each placeholder with the selected file's lowercase SHA-256. Paths are
portable relative paths inside the manifest directory; no traversal, links,
UNC/device paths or automatic discovery. Use exit 3 for a failing native run.
Examples under `examples/instrument` are explicitly generated test-double data
with redacted path labels, not records of real instruments.

```powershell
hil-runner instrument import import.json --sha256 '<import-sha256>' --output '<new-bundle.json>' --json
hil-runner instrument inspect '<bundle.json>' --sha256 '<bundle-sha256>' --json
```

Import checks all explicit input hashes/lengths, original spec/check binding,
native analysis hashes, source status/error/cleanup, recorded verification
bindings, verdict/count consistency and the canonical 0.8.0 JUnit bytes/details.
It preserves every original byte, including XML, inside the new bundle. It never
opens paths recorded inside native evidence; those remain unauthenticated labels.
The five evidence files and manifest are read once, then all validation uses
their snapshots. Output must be new, with an existing parent, and is checked
before input reads. No output is created on validation failure.

## Meaning of results

Import returns 0 for an intact passing result, 3 for an intact failing result
(bundle still written), and 2 for an input/binding/format/output error. Inspection
returns 0 when the self-contained bundle validates, including a failing result;
read `data.verdict_ok`, status and the per-check outcomes.

`failed` and `invalid_evidence` remain distinct and JUnit retains failure/error
counts, never skipped. Missing data never becomes a passing result. Successful
import is not a new instrument measurement or fresh native recomputation:
`native_recomputation_recorded=true`, `native_recomputed_now=false`,
`source_execution_performed=false` and `report_authenticated=false` are explicit.
The supplied exit code and native verification are records under normal local
host trust, not signatures or independently authenticated historical execution.
HIL validates consistency, not UART/I2C/SPI/PWM signal policy a second time.

All original physical/source declarations remain available, including test-double
origin and failed cleanup. A recorded `physical_instrument` origin does not verify
wiring, clock, calibration, target firmware or measurement authenticity. No
absolute timestamps are invented for sample-relative data. Trace's separate
`instrument` views can inspect/filter this artifact after all originals move.

## Bounds and cost

The import manifest is at most 16 KiB, assertion spec 64 KiB, native CLI JSON
128 KiB, report/capture/XML each 1 MiB, and 1–8 checks. The self-contained artifact
is capped at 8 MiB. At most 3,358,720 input bytes are read. Base64, parsed JSON and
canonical comparisons add memory beyond file size; 8 MiB is not an RSS limit.
Cost scales with explicit input bytes and native records rather than rerunning
the signal decoder. Inspect validates the entire bundle before returning a
summary. This deliberately prioritizes integrity over a cheap unvalidated preview.
