# Repository guidance

- Keep component hardware operations in baud, BLEA and embedded-debugger.
- Preserve the 0.1 host-only cooperative lease interface. Managed execution may
  launch only fixed, hash-bound embedded-debugger flash-session and runtime
  commands. The separate simulation domain may launch only the fixed, hash-bound
  sim-runner 0.2.0, 0.3.0 or 0.4.0 wheel through an isolated Python bootstrap. It never participates
  in hardware leases or falls back to real boards. Never add arbitrary commands
  or automatic recovery/retries. Keep simulated and physical evidence distinct.
- Keep native confirmation, one-use scope markers, firmware windows, runtime
  assertions and target cleanup in the native debugger. A managed plan grants
  no authorization. Declare runtime reset-capture as an additional effect.
- Keep ownership until all managed processes are observed stopped. Start Windows
  children suspended, assign a kill-on-close Job before resuming, and retain
  partial evidence on timeouts and process failures. Do not infer target cleanup
  from killing host processes.
- Bind leases to saved, exact identities. A lease is ownership coordination,
  never hardware identity verification or authorization.
- Use nonblocking OS locks, roll back partial acquisition and retain lock files.
  Never reclaim ownership by deleting a lock file or trusting a PID/TTL record.
- Test real separate processes, conflicts, EOF, deadlines and forced termination.
- Keep JSON bounded, stdout protocol-only and dependencies minimal.
- Run tests, lint, formatting, package smoke and git diff --check before commit.
