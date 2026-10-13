# Host lease protocol v1

`lease plan` emits one result document. `lease serve` emits one result per line;
stdout contains no banners. Version output is a separate `--version` mode.
Every result uses `embedded-hil-runner.result.v1`, and preserves these fields:

```json
{
  "scope":"host_only_cooperative_leasing",
  "hardware_access":false,
  "component_processes_started":false,
  "authorization_granted":false,
  "target_cleanup_verified":false
}
```

Serve acquires every resource before publishing a successful `lease.open`.
`data` binds canonical root, selection path/hash, resources, board label,
PID, unique lease ID, UTC start observation, fixed duration and remaining idle
or duration budget. Remaining milliseconds are an observation, not a promise
the lease still exists when a client receives the message. Holding the lease
cannot establish the selected board is physically connected.

Requests contain exactly `id`, `operation`, `lease_id`. IDs are strings of
1–64 printable ASCII characters; operations are `lease.status` or `lease.close`.
Unexpected fields, IDs, operations and stale lease IDs produce `lease.error`.
They do not restart the service, switch identities or renew the deadline.
Only successfully validated status requests renew idle time. Maximum duration
is immutable; there is no indefinite renew/reclaim command or scope expansion.

Limits: duration 1–3600 seconds, idle 1–duration seconds, 256 requests, 4096
bytes per request, 16-entry reader/writer queues and 32 JSON nesting levels.
Oversized input or the request limit
closes the lease with a nonzero result. Duplicate keys, non-finite JSON numbers,
unbounded/deep input and selection authorization claims are rejected. The raw
stdin reader avoids buffered Python stdin locks during timed interpreter exit.
OS syscall/process scheduling delays can postpone terminal evidence; the timer
does not interrupt a blocked native operation because none is started here.
An unconsumed stdout pipe cannot block the owner: output backpressure or writer
failure releases the lease and exits 4. Final output drains for at most one
second after releasing handles; a blocked pipe may lose terminal evidence.
Enqueueing a response waits at most 50 ms to let an active writer drain.

`lease.close` emits its correlated terminal response then exits. EOF, expiration
and interruption emit `lease.closed` with a terminal reason. SIGKILL/forced
termination or lost stdout may provide no terminal evidence. The OS closes
the lease process's handles, but no hardware cleanup should be inferred.

| Exit | Meaning |
| --- | --- |
| 0 | Plan or graceful host lease lifecycle completed |
| 2 | Input/protocol error or request-size/count limit |
| 3 | Immediate resource conflict; no ownership acquired |
| 4 | Host I/O or handle cleanup error |
| 130 | Keyboard interruption after host cleanup |

After a conflict, the failed process releases any earlier acquired handles.
Persistent `.lock` files are safe to reuse and are never deleted by the CLI.
Only regular single-link files are accepted. Descriptors are not inherited by
subprocesses. The OS lock is authoritative; no timestamp/PID metadata is used
to decide that a resource can be reclaimed. Selection path canonicalization
and resource case normalization make equivalent spellings use the same locks.

This is a cooperative host protocol, not a hardware authorization protocol.
The caller must use exact native components, fresh identity checks and agreed
effects, and stop on indeterminate mutations. End native sessions and validate
their cleanup before closing the host lease. A future executor may manage that
ordering; this version cannot enforce it for external clients.
