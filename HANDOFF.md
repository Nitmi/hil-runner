# HIL Runner handoff

Read this file and AGENTS.md before a new task. The active workspace HANDOFF.md
and desktop development plan track cross-repository progress.

Published 0.11.0 is28bd2275. Current local0.12.0 is on
feat/offline-thermal-evidence; older unpublished notes below are historical.
Read docs/thermal.md before thermal import changes.

- Independent thermal import/inspect binds five primary native inputs plus the
  complete ordered original source inventory (including empty ancillary files).
  It performs no camera/helper/SDK access or temperature conversion. The shared
  stdlib thermal_protocol.py and load_protocol.py must stay byte-identical in
  Trace; neither runtime depends on the other or on lab. Trace does not rebuild
  native XML, while HIL import/inspect compare canonical native JUnit bytes.
- Preserve source failure, unscored partial frame rows, native errors and unknown
  cleanup. A passing/empty Trace page never alters global failure/JUnit counts.
  Raw Y16/control/telemetry, mask/FFC/gain/trend context and ROI spans remain bound.
  All actual-device/scene/calibration/accuracy/clock/junction claims stay false.
  Native verification is historical/unsigned; input hashes do not authenticate it.
- Native fsum/division can place a mean one adjacent binary float outside equal
  min/max. Only this recorded-statistic consistency relation permits one ULP;
  user temperature bounds/comparisons never widen. Actual400-pixel native frames
  exposed this; do not add a broad epsilon or change native measurement output.
- Never save a thermal bundle inside its selected source capture directory: that
  would add an uninventoried file. Reject it before reading remaining inputs.
  Reject duplicate file identities/paths, links, missing/extra source artifacts,
  version/verifier mismatches and coherently rebound inconsistent records.
- 0.12 retains old digital/waveform/load artifacts and also handles lab0.11
  verification matrices. Joint wheel acceptance used26 cases per Python:
  eleven thermal, fourteen actual historical cases rechecked by native0.11
  (legacy producer0.8 unchanged), plus current native0.11 SDS many-file output.
  Each retained global verdict survived HIL import/inspect and four Trace views.
- Python3.11/3.13 full regression each383 passed/one symlink skip, with all seven
  exact-hash native Replay cases enabled. Final thermal/release focused tests use
  the bare pytest launcher too (54 passed each). No real board/SDK/simulator used.
  Independent HIL cold smoke checks15 schemas/eleven thermal cases; Trace checks
  138 commands/24 package files. Qualified cold installs are distinct from one
  interrupted first Trace3.11 cold run retained in the execution directory.
- One outer600-second cold-smoke timeout occurred in existing digital reporting;
  exact host cause is unconfirmed. No owned process remained; one diagnostic of
  that installed report completed in0.357s. A new isolated cold run fully passed.
  Keep the first failed directory; do not raise product timeouts or call it pass.
  Joint harness initially assumed selected_checks for every domain; digital uses
  selected_count. Reuse only recorded matching argv/exit/output hashes when
  resuming completed offline checks, never fabricate exit codes or rerun hardware.
- Helpers initially confused runner_version vs producer_version in old schemas,
  a relative test-module import, and function-local importlib shadowing the outer
  import. Fix those authoring errors, not runtime gates or input evidence. The
  final code and native source fixtures passed all relevant checks.
- Local performance on installedPy3.13 (one warmup/seven samples):3 buffers/two
  checks,2,174,853B bundle: import63.61ms, inspect43.39ms, Trace passing/empty43.35/
  44.22ms;8 buffers/eight checks,5,723,556B:121.92/106.78/103.20/103.55ms. Import
  Python peaks6.61/17.36MB; whole-bundle reads peak33.56MB due to the bounded
  read(maximum+1) buffer even for small files. Not RSS/cold-I/O/startup/SLA.
  Network/process starts were blocked during measurement. Fixture source cap16MiB,
  bundle32MiB,101 original files/106 selected reads; full validation precedes pages.
  Execution evidence: D:\Code\tmp\hil-trace-thermal-0120-20261028.

The published0.11 load domain preserves seven explicit native inputs and complete failed
source/cleanup context. It never executes lab, hardware or a SCPI replay. Its
consistency kernel is vendored byte-identically in Trace; synchronize changes,
keep independent stdlib runtimes, and verify both installed wheels.

New pitfalls: raw query cache keys include the expected command; transaction
indices must match the transcript command-start index, not just a valid range.
Number bounds precede float finiteness checks to reject enormous integers without
overflow. Keep global Markdown verdict/JUnit outside truncated source previews.
Preserve native fixtures with -text; stage before sdist and compare Git bytes.
Load source files are eight bounded reads including the manifest, at most
4,440,064 bytes; 16 MiB bundle/JSON32. Trace must validate all evidence before
filters; neither a passing page nor an unknown cleanup may upgrade the source.
Use real installed lab 0.10 digital/waveform outputs for combination checks;
accepting only the new load format would strand older command domains.

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
  Keep the native digital verification schema separate from waveform 0.9.
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
- Hash-bound waveform fixtures use `-text` in .gitattributes. Native CRLF in
  JSON/SCPI/CSV must survive Git and source archives unchanged. Schemas and docs
  use LF. A clean Git status alone does not prove worktree bytes equal blobs;
  source-bound release construction must compare every archived tracked file.

## Release-preparation digital compatibility correction

Before publishing local 0.10.0, the actual lab 0.9 installed digital chain was
reproduced failing with `unsupported native report`. A waveform-only cold test
had missed that the new lab generates 0.9 logic reports too. Digital import now
explicitly supports verifier 0.8 -> producers 0.7/0.8 and verifier 0.9 -> producers
0.7/0.8/0.9. Never accept producer0.9/verifier0.8 or an unknown verifier. Canonical
JUnit properties use the recorded, checked verifier, with the full byte/details
comparison retained. No decoder, hardware, authorization or XML check was removed.

Native fixtures in examples/instrument-09 contain actual installed lab0.9
passed/failed/invalid/mixed output plus an unchanged producer0.8 report reverified
by lab0.9. Preserve them as bytes via local attributes. Installed smoke tests all
five alongside old native0.8 and waveform cases. New release plans must use the
replacement candidate commit/assets; the earlier d25b747c candidate stays frozen.
Version0.10 is still unpublished, so no existing tag or release is modified.
