# HIL Runner handoff

Read this file and AGENTS.md before a new task. The active workspace HANDOFF.md
and desktop development plan track cross-repository progress.

The local 0.9.0 instrument domain imports recorded lab-instruments 0.8.0 native
verification/JUnit and explicit original inputs. It has no executor, device path
or runtime dependency. `native_recomputed_now=false`: consistency checking is
different from fresh native signal decoding, signatures or physical acceptance.
See docs/instrument.md for flags, bounds, exit codes and cost. Preserve failures
and invalid evidence; inspect success is not test success.

Pitfalls resolved during this change:

- A local `result` variable in cli.main shadows the existing managed.result
  function for every branch. Use a domain-specific variable, and regression-test
  managed preparation and explicit native Replay, not just the new command.
- Bumping __version__ also affects managed/simulation plan schemas. Keep the
  schema producer declaration consistent; do not weaken input drift checks.
- A native CLI response is itself selected by manifest hash. Explicitly selecting
  a new hash for formatting-only JSON is valid; original report/spec/capture
  bytes remain bound inside that response and cannot be reformatted silently.
- New isolated editable installs need hatchling's optional `editables` helper.
  Use ordinary built wheels for installed-code tests here; no system install or
  source dependency change is required. Preserve failed setup logs separately.
- Run multi-process/native Replay tests serially across Python versions. Replay
  requires an exact executable hash, fixture hash and synthetic serial program;
  never use real hardware as a fallback to complete a skipped test.
- Stage new files before sdist builds. Check installed smoke before commit, then
  rebuild the clean commit with the same SOURCE_DATE_EPOCH and compare bytes.

Import performs six bounded file reads (at most 3,358,720 bytes) and duplicates
data as parsed JSON/base64. Cost scales with source bytes/native records; the
8 MiB artifact limit is not a process RSS guarantee. Include wall-time and Python
allocation measurements in production acceptance, with warm/cold conditions
identified. Never infer native decoder performance from this importer's timing.

## Local 0.10.0 saved waveform import

The separate `waveform import/inspect` domain consumes lab-instruments 0.9.0
AD3/SDS804X native verification and canonical JUnit. It has no lab dependency,
voltage conversion, binary descriptor decoder, SDK, hardware or subprocess path.
Keep all measurement/authorization flags false and native recomputation recorded.
No publication or station activation is implied by a local candidate.

- A manifest explicitly selects five primary inputs plus ordered SDS sources.
  Never follow report/capture/SDK path labels. Capture plus ancillary sources
  are limited to 8 MiB/1,615 files, each 1 MiB; manifest 512 KiB and artifact
  20 MiB. Runtime validates all bytes on inspect without reopening original paths.
- SDS successful write transactions can have zero-byte RX files. Preserve their
  exact empty bytes/hash; allow zero only in ancillary snapshots. Missing is not
  empty. Native inventory order differs from canonical JSON object key order;
  reconstruct it from the explicit manifest rather than dictionary insertion.
- Keep raw WORD/preamble/CSV/wire files, source cleanup/freshness, RMS/AC RMS
  meanings and false clipping/bandwidth/calibration/UTC/alignment claims intact.
  Check recorded comparisons/spans/metadata, not a second voltage implementation.
- Reject duplicate selected file identities as well as case-folded paths.
  Each selected file is read once; use bounded aggregate checks before decoding.
- Existing digital instrument artifacts from 0.9.0 remain accepted. Their new
  HIL producer may be 0.10.0; unknown-producer negative tests must use 99.0.0.
  Keep their pinned native 0.8 logic verifier separate from waveform 0.9.
- New synthetic SDS originals increase source inventory: release parsing caps
  sdist at 512 files while retaining 8 MiB total/per-file archive bounds. New
  waveform runtime and both schemas are mandatory in release verification.
- Tests use native-generated synthetic saved fixtures. Run full unit tests,
  targeted release tests, qualified native Replay and installed smoke on both
  Python 3.11/3.13. Source tests need process-local `PYTHONPATH=src` when the
  shared dev environment contains old ordinary wheels; cold smoke uses `-I`.
  Do not edit a system environment or fall back to live hardware.
- Measure full import and whole-bundle views, including SDS many-file costs.
  A passing-only/empty view still validates all evidence; allocations are not RSS.
