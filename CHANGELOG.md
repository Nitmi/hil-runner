# Changelog

## 0.2.0 - 2026-10-19

- Cooperative OS file-lock leases with bounded lifetimes, conflict detection,
  rollback, namespace checks and process-exit cleanup.
- Windows managed execution holds leases across one native bounded flash scope
  and per-build runtime acceptance, without repeated per-flash user prompts.
- Exact executable/firmware/contract hashes, private snapshots, fixed native
  operations, and Job process containment; no arbitrary commands or retries.
- Runtime failure stops subsequent builds. Native debugger 0.2.5 excludes
  pre-READY heartbeats and earlier boot identities from acceptance.
- Code-only nRF52840 DK A/B fixture, saved physical qualification and host-only
  native integrations. Python wheel/source delivery with tag-bound provenance.
