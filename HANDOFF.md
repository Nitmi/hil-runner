# HIL Runner handoff

Read this file and AGENTS.md before a new task. The active workspace HANDOFF.md
and desktop development plan track cross-repository progress.

Current local0.18 on feat/gpiote-simulation-evidence adds explicit GPIOTE
input/IRQ evidence from the exact36-file sim-runner0.13 wheel. Older profiles
accept0.13 only through their explicit inventory gates; regenerate their plans.
Native Sim policy remains authoritative. Preserve CONFIG/current-state, GPIO
inputs, events, guest ISR, failed nominal faults and unknowns without inference.
Whole-suite preflight, fail-stop, zero retries and process ownership stay intact.
The installed matrix mixes GPIOTE, EGU and RTC, with timeout and wrong BUILD.
Evidence root D:/Code/tmp/hil-trace-gpiote-0180-20261103; current phase is local
qualification, not publication or Toolkit/station adoption. No physical fallback.
Normalize only proven worktree CRLF drift before packaging, retaining unchanged
raw fixtures. Shared Renode history must stay inaccessible during parallel runs;
the previously fixed per-run absolute history paths must remain unchanged.

Pre-commit checks: Python3.11/3.13 each495 passed/one existing symlink skip;
seven native debugger Replay cases ran. Ruff/format/offline lock and isolated
installed HIL smoke pass. A project-version mechanical edit accidentally changed
the Ruff lock entry; offline lock correctly rejected the mismatched wheel.
Restore only Ruff0.17, never skip wheel filename checking or upgrade dependencies
to conceal this error. Original hil-lock exit2 remains in evidence. Trace smoke
controller requires an explicit sibling-script path under Python -I; a wrapper
import failure occurred before any Trace check and did not repeat HIL311 smoke.

Current local0.17 on feat/egu-simulation-evidence adds EGU integration;
the local0.16 RTC notes below remain history. Read the EGU section in
docs/simulation.md before changing this path.

- EGU v1 requires the exact34-file sim-runner0.12 wheel. Legacy profiles also
  accept0.12 with regenerated plans; never reuse a mismatched runner inventory.
- Preserve native policy, false PPI/physical/model qualifications, failed fault
  outcomes and unknowns. Fault request uses stimulus_index=4, not virtual time.
  Nine tasks include a sentinel channel;18 PRE/POST observations bound raw bytes.
- Whole-suite preflight, one execution per case, fail-stop, Windows Job ownership
  and cleanup remain intact. The joint harness mixes EGU, RTC and watchdog.
- Python3.11/3.13 full suites and static checks pass; final installed qualification
  is tracked in D:/Code/tmp/hil-trace-egu-0170-20261103. Do not claim local candidate
  hashes are attestation, publish, or switch Toolkit/station locks in this stage.
- Final installed qualification: each Python has7 suites/72 CLI checks/9 native
  attempts; zero retries, complete Job/capture cleanup.14 EGU sources preserve
  216 model spans,84 guest samples and4 fault markers.16 saved instrument-domain
  compatibility cases pass. HIL each472 tests/one existing platform skip; Trace
  each639/two skips; updated Sim each456/no skips.
- Parallel runs exposed Renode's shared AntShell history. Sim0.12 candidate
  d42d0f2 fixes this with absolute per-run history; both final matrices pass while
  the shared file is exclusively locked. Earlier17 attempts and two failed
  relative-path controls remain history. No failure or INPUT_CHANGED is hidden.
- Installed Python3.13 warm normal-pair inspect median169.79ms/Python peak
  17149135B; one warmup/seven timings/separate allocation capture, no process or
  network starts. Not RSS, cold IO, startup or SLA.413 protected files and raw
  persistent PATH remain unchanged; the19B generated runtime extra was preserved
  in evidence and removed from the pinned runtime inventory.

Current local0.16 on feat/rtc-simulation-evidence adds RTC evidence integration.
Read docs/simulation.md#rtc-evidence-in-local-0160 before changing this path.
This supersedes the local0.15 watchdog status below, which remains history.

- Explicit RTC plan/report v1 requires sim-runner0.11 and its exact32-file
  runtime inventory; older inventories stay accepted only for their profiles.
  Regenerate legacy plans for the chosen wheel. Schema includes exact32 count.
- Native inspect owns RTC policy. Copy bounded counter/event/IRQ evidence,
  native failures/errors and nulls; no second policy engine. Observed stop/mask
  faults still fail nominal regression. Whole-suite preflight, zero retries,
  fail-stop, Windows Job ownership and capture cleanup remain intact.
- Python3.11/3.13 each451 passed/one existing symlink skip; all seven exact
  debugger Replay tests run. Ruff/format/offline lock/diff and two installed
  package smokes pass. Current HIL0.16 producers retain all four saved instrument
  domains;16 installed HIL-to-Trace compatibility cases pass.
- Installed RTC integration has7 suites/72 CLI checks/9 native attempts per
  Python: normal pair, stop/mask/wrong BUILD/timeout, RTC/SPI/watchdog mixed and
  whole-suite preflight rejection. Total18 actual attempts, zero retries, complete
  Job/capture cleanup.14 RTC sources bind48 model spans/68 guest samples/4 fault
  markers; four normal UART captures match prior native RTC bytes exactly.
- Python3.13 warm normal-pair inspect median220.60ms/Python peak17117376B;
  one warmup, seven timings, separate allocation capture. Not startup, cold IO,
  RSS or SLA.286 protected files and persistent raw PATH remain unchanged.
- Evidence root D:/Code/tmp/hil-trace-rtc-0160-20261030. Source-bound final build
  receipts/candidates and sealed audit are tracked there and in desktop/global
  handoff; do not rerun successful native phases or mutate published Toolkit0.38.
- The numbers above describe the initial installed qualification. Final source
  binding rejected CRLF worktree bytes against LF Git blobs (uv.lock first).
  Restore only proven CRLF-to-LF differences to Git bytes before building. Keep
  initial captures; final LF wheels receive separate cold/matrix qualification
  with their own paths/receipts. Do not call them identical wheels until checked.
- Pitfalls: initial old SPI/I2C admission tests omitted0.11 and one sample-count
  map omitted32; fixed at the inventory boundary, no runtime bypass. Native
  READY/BUILD mismatch parses no guest samples, so independent audit expects68,
  not88; raw reports retained, no emulator rerun. New helper copies must use
  UTF-8 explicitly and discover assets versus dist paths before invoking them.
  Failed development checks and host wrapper errors stay in qualification notes.
- No public write, hardware, physical fallback, station/lock/PATH/plugin change.
  Next prepare the sim0.11/HIL0.16/Trace0.16 release batch from qualified commits;
  publication and Toolkit adoption remain separate authorization/scope steps.

Current local0.15 on feat/watchdog-simulation-evidence adds explicit watchdog
integration for sim-runner0.10. The0.14 SPI notes below are published history.
Read docs/simulation.md#watchdog-evidence-in-local-0150 before editing this path.

- Watchdog plan/report v1 requires the exact30-file inventory. Older version/
  profile pairs remain accepted. Copy bounded native declarations, clock, errors,
  fault request and unknown/null effects after native inspect; do not implement
  a second firmware-policy engine. Fault observed does not mean regression passed.
- Python3.11/3.13 each432 passed/one existing symlink skip, with all seven exact
  debugger Replay tests enabled. Ruff/format/offline lock/diff pass. Each joint
  cold install verifies65 non-RECORD payloads;15 schemas and saved instrument
  smokes pass. Shared load/thermal protocols remain identical to Trace0.15.
- Each installed Python:7 suites/72 CLI/9 actual native simulations, zero retries.
  Normal pair and watchdog+SPI+GPIO pass. Feed-timer-stop, watchdog-stop, wrong
  BUILD and timeout fail-stop; whole-suite preflight rejects before any backend.
  Cleanup and artifact binding pass.14 watchdog sources retain48 model spans,
  two reset/callback pairs and148 sample spans; four normal UARTs match sim0.10.
- HIL0.15 -> Trace0.15 compatibility covers16 saved instrument cases, including
  failures and unknown cleanup. Trace full/sample/empty/Markdown preserve native
  failures/nulls and reject rehashed contradictions. No physical hardware/SDK.
- InstalledPy3.13 warm one+seven medians: normal two-case inspect231.98ms,
  feed-stop139.94ms, timeout180.69ms; Python allocation peaks16.9-17.1MB.
  No process/network is allowed during measurement. Not RSS/startup/cold-I/O/SLA.
- Pitfalls retained in raw logs: initial Trace long lines and test render alias
  fixed; malformed sample spans require a dict guard before .get. The final Trace
  wheel was rebuilt/reinstalled before the joint matrix; superseded initial
  smoke evidence remains distinct. An offline performance helper was invoked
  before its second-Python input existed; it failed without starting a backend,
  then ran after matrix completion. Never rerun native cases for helper errors.
- Evidence D:/Code/tmp/hil-trace-watchdog-0150-20261030;299 protected files and raw
  persistent PATH values/types unchanged. Local candidates are not release
  attestations. Current Toolkit/plugin0.37, station/locks/PATH remain unchanged.
  Next prepare sim0.10/HIL0.15/Trace0.15 release materials; no publish authorized.
  Physical timing/reset/low-power and complete model coverage stay false.

Current local0.14 on feat/spi-simulation-evidence adds explicit sim-runner0.9
SPI0/LM74 integration. The0.13 notes below are historical and published.
Read docs/simulation.md#spi-evidence-in-local-0140 before changing this path.

- SPI uses an independent schema/profile and the exact28-file wheel inventory.
  Keep all older inventories/profile pairs, including regenerated I2C/GPIO on0.9.
  Copy bounded native assertions/errors/fault request/clock; native inspect owns
  Q4/frame/readiness policy. Fail/unknown stops later cases with no retry/fallback.
- Python3.11/3.13 each415 passed/one existing symlink skip; seven exact native
  debugger Replay tests enabled. Ruff/format/uv lock/diff checks pass. Two cold
  installed pairs each verify65 non-RECORD payload files; all15 schemas and old
  instrument/waveform/load/thermal smokes pass. Shared protocol files match Trace.
- Both installed matrices each7 suites/72 CLI/9 actual native attempts, zero
  retries: normal pair, frozen/slip/wrong BUILD/timeout fail-stop, mixed SPI+I2C+
  GPIO, and whole-suite preflight rejection before any backend. Complete process
  cleanup, original artifacts and expected negative exits verified. Four normal
  UARTs match native0.9;14 SPI sources retain48 model spans plus2 slip spans.
- Current0.14 HIL->Trace compatibility checks16 saved instrument-domain cases.
  Trace full/sample/empty/Markdown preserve failure/nulls and reject rehashed
  contradictions. No hardware, lab SDK or native instrument evaluator runs.
- InstalledPy3.13 warm one+seven medians: normal two-case inspect159.10ms,
  frozen119.96ms, timeout118.10ms; Python allocation peaks~16.9-17.1MB.
  Trace normal import7.46ms/387211B, inspect4.03ms/292667B. Not RSS/startup/
  cold-I/O/SLA; measuring blocked process/network and original-source view opens.
- Development pitfalls: tests are a package, so helper imports are relative;
  inventory admission must also extend the exact28-file JSON-schema branch.
  Parent -I source selection does not propagate to child CLI tests. Compatibility
  bundle identity is producer_version, not runner_version; thermal scenario is
  cleanup-unknown. Original failed checks retained. Helper resumes reuse only
  matching saved argv/exit/raw hashes, never repeat a completed native attempt.
- Evidence D:\Code\tmp\hil-trace-spi-0140-20261030. Independent audit273 protected
  files unchanged. New candidates remain local/unsigned/unpublished; current
  Toolkit0.36.1, Codex plugin, workstation locks and PATH stay unchanged.
  Next prepare sim0.9/HIL0.14/Trace0.14 publication and Toolkit static integration;
  do not rerun completed matrices or treat local evidence as release attestation.

Current local0.13 on feat/sensor-simulation-evidence adds explicit sim-runner0.8
sensor plan/report integration. The0.12 notes below are historical; it is already
published. Read docs/simulation.md#sensor-evidence for the new local candidate.

- Exact0.8 inventory is26 files, including sensor.py and TMP103 model; retain all
  older wheel/profile inventories. Native run/inspect owns acceptance policy.
  HIL copies bounded native assertions, errors, fault request and clock without
  reevaluating temperature/readiness. Fail/unknown still stops subsequent cases.
- Py3.11/3.13 each400 passed/one symlink skip, seven exact native Replay tests
  enabled; bare-pytest sensor/release22 passed each. Shared load/thermal protocol
  bytes stay identical with Trace. Extend explicit producer schemas/lists to0.13
  while keeping old pairs; the new version must not break old instrument bundles.
- Both installed-wheel smokes pass15 schemas and old instrument/waveform/load/
  thermal checks; Trace cold smoke138 CLI/24 package files. Each pair independently
  matches65 non-RECORD payload files to selected wheels. Two seven-suite matrices
  contain18 actual native simulation attempts in total, zero retries: normal pair,
  frozen/offset/wrong BUILD/timeout fail-stop, sensor+GPIO+WASM qualified success,
  and preflight rejection before any backend. Four normal UARTs match the accepted
  native0.8 fixture. Fourteen sensor sources retain48 exact stdout spans/nulls.
- Development wrapper faults: direct -I Trace helper needs its trusted neighboring
  script directory; HIL and Trace inspect need distinct capture names; capture
  outcome lives in capture_outcomes, not simulation_sources. A valid timeout may
  have no uart.bin: preserve no bytes/null assertions, never invent a file/pass.
  The harness snapshots journals and reuses only matching completed argv/actual
  exit/capture; it never retries failed/uncertain children or successful runs.
  Original failures and resumed Py3.11 evidence remain; Py3.13 starts clean.
- InstalledPy3.13 warm medians (one warmup/seven samples): normal two-case HIL
  inspect215.23ms, Trace import30.04ms, inspect/sample/empty19.28/18.51/19.89ms;
  frozen HIL196.37ms/import18.86ms, timeout169.36/16.78ms. Python allocation peaks
  HIL~17.1MB, Trace import~8.7MB, views~67.1MB from existing read(limit+1) buffer.
  Not RSS/startup/cold-I/O/SLA; filters validate whole input first. Measurement
  blocks subprocess/network and allows view reads of only the saved timeline.
- Evidence root D:\Code\tmp\hil-trace-sensor-0130-20261029. Independent audit
  verifies304 protected files unchanged, saved bytes, exact negative exits and
  cleanup. No physical access or formal Toolkit/station/plugin/lock changes.
  The new0.13 candidate is local, unsigned and unpublished. Next prepare the
  sim0.8/HIL0.13/Trace0.13 publication and Toolkit integration, keeping formal
  simulation pins unchanged until formal sources/cold installs are qualified.

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
