# Repository guidance

- Keep component hardware operations in baud, BLEA and embedded-debugger.
- The first release implements host-only cooperative leases. Do not add arbitrary
  commands, hardware discovery, device operations or automatic recovery.
- Bind leases to saved, exact identities. A lease is ownership coordination,
  never hardware identity verification or authorization.
- Use nonblocking OS locks, roll back partial acquisition and retain lock files.
  Never reclaim ownership by deleting a lock file or trusting a PID/TTL record.
- Test real separate processes, conflicts, EOF, deadlines and forced termination.
- Keep JSON bounded, stdout protocol-only and dependencies minimal.
- Run tests, lint, formatting, package smoke and git diff --check before commit.
