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
