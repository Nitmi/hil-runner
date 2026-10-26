# Saved load evidence

`load import` preserves a completed lab-instruments 0.10.0 saved-load JUnit
verification, its exit code and seven explicit original files. It uses only the
standard library, reads each file once and opens no device, SDK or child process.
The live lab load runner remains the owner of SCPI execution and cleanup.

Create an import manifest, following `examples/load/passed/import.json`:

```json
{
  "schema_version": "embedded-hil-runner.load-spec.v1",
  "native_exit_code": 0,
  "inputs": {
    "report": {"path": "report.json", "sha256": "<64 lowercase hex digits>"},
    "spec": {"path": "spec.json", "sha256": "<digest>"},
    "capture": {"path": "capture.json", "sha256": "<digest>"},
    "native_result": {"path": "native_result.json", "sha256": "<digest>"},
    "junit": {"path": "junit.xml", "sha256": "<digest>"},
    "plan": {"path": "plan.json", "sha256": "<digest>"},
    "transcript": {"path": "transcript.jsonl", "sha256": "<digest>"}
  }
}
```

Paths are portable relative paths under the manifest directory, not commands or
URLs. Select the native `load junit` stdout as `native_result`, its XML as
`junit`, the check report/spec as `report/spec`, and the original saved
`load-result.json` as `capture`. Explicitly select its plan and transcript too.
Native recorded path strings are labels and are never followed. Different
recorded/supplied labels are preserved by the native verification bindings.
Do not rewrite source bytes to update paths or producer versions.

```powershell
hil-runner load import import.json --sha256 <manifest-sha256> --output bundle.json --json
hil-runner load inspect bundle.json --sha256 <bundle-sha256> --json
```

Exit 0 imports a passing verdict; exit 3 imports a complete failed/invalid
verdict and still creates the bundle. Invalid or mismatched inputs exit 2,
creating no output. Inspect exits 0 for successful processing, so read
`data.verdict_ok` and the original JUnit counts to determine test success.
An existing output is rejected before reading inputs. No automatic search,
retries, authorization changes or execution fallback is provided.

## Validation and meaning

The self-contained `embedded-hil-runner.load-report.v1` embeds original bytes,
path labels, sizes and SHA-256 for the manifest and all seven inputs. Relocation
or deletion of the originals does not invalidate an unchanged bundle. Import
and inspect compare native bindings, source plan/transcript inventory, selected
phases/windows/indices, raw query byte spans and transaction indices, recorded
numeric comparisons, overall verdict and native exit 0/3. Import and inspect
also reconstruct and compare the canonical native JUnit XML byte for byte.

This is recorded-data consistency checking, not a new lab SCPI-session replay,
physical acquisition or authentication. `native_recomputation_recorded=true`
records the selected native verification. `native_recomputed_now=false`,
`native_scpi_replay_performed=false`, `source_execution_performed=false` and
`report_authenticated=false` remain explicit. SHA-256 detects drift relative to
the chosen inputs; it cannot authenticate a coherently fabricated source set.

Before-load, loaded and observation phases remain separate. Up to 8 checks
select 1..50 phase-relative samples and the native nine min/max/mean V/I/P
metrics plus input state. V/I/P are sequential queries, not simultaneous samples.
Power uses the returned power value, not V multiplied by I. Means are arithmetic,
not time-weighted; no energy integration, physical timing or clock alignment is
inferred. Native cleanup reports describe that recorded session, never the
current instrument state or exclusive ownership of a physical instrument.

A failed acquisition, timeout or unknown OFF result makes all its checks
`invalid_evidence`. Partial measurements, error, identity and cleanup remain
unscored context. They cannot become a passing subset. `hardware_access`,
`outputs_commanded`, `executables_started`, `authorization_granted`, physical
device/DUT identity, calibration and timing verification remain false for import.
Recorded source effects remain under `source.recorded_effects` without granting
new authority. Six fixtures cover passing, failed, invalid, mixed, cleanup
failure and timeout using actual native output from localhost protocol doubles.
They do not qualify real instruments.

## Bounds and cost

Manifest: 16 KiB; report/capture/XML/transcript: 1 MiB each; spec: 64 KiB;
native stdout: 128 KiB; plan: 32 KiB. Eight reads total at most 4,440,064 bytes.
Only the failed-session transcript may be empty; missing files are rejected.
The bundle limit is 16 MiB, JSON depth 32, and all inputs remain mandatory.
Runtime validation is stricter than the published shape schemas.

Cost scales with all selected bytes and records, including JSON parsing, raw
transcript indexing, base64, canonical copies and XML comparison. Reusing query
span validation avoids decoding the same raw queries for overlapping checks.
Byte caps are not process-RSS caps. Acceptance measures complete import/inspect
and Trace views, distinguishing warm Python allocations from cold process cost.

## Compatibility

Load uses lab producer/verifier 0.10.0 and HIL producer 0.11.0 only. Other
versions are rejected until separately qualified. Existing digital and waveform
formats remain distinct: digital verifier 0.10 supports recorded producers
0.7/0.8/0.9/0.10, waveform verifier 0.10 supports 0.9/0.10. Their older supported
verifiers remain accepted with their original restricted producer matrices.
Actual lab 0.10 outputs in `examples/instrument-10` and `examples/waveform-10`
cover this compatibility, including an unchanged digital 0.8 producer reverified
by 0.10. No source version is relabeled.
