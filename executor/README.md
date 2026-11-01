# TradingGYM B1 Executor (unified, read-only work in progress)

**NOT release-ready, NOT funded, NOT emergency-stop protection.**

- `exec-core`: pure, disarmed/monotone stop-state reducer.
- `exec-store`: single-writer SQLite WAL event ledger with FULL
  synchronous commits, immutable guards and exact stored-byte hash verification.
- `exec-ipc`: bounded, versioned T0 stop-only wire codec.
- `exec-svc`: Windows SCM no-op host with strict LocalService
  restricted-token identity, safe disabled installer and hosted Windows
  SCM/NTFS/hostile-local-user tests. The independent stop-pipe code is a
  **library only**; the host does not activate it.
- `gym-core`: public observatory and pure sanitized *read-only*
  account/manual-order projection. The Journal defaults to NOT_CONFIGURED;
  no authenticated venue observation is enabled by this change.

All existing tests run through GitHub Actions; Rust uses
`cargo test --locked --workspace --all-targets` on Linux/Windows,
plus Windows disposable SCM integration and the Python suite.

**See [B1 progress](docs/b1-progress.md) for passing evidence and outstanding
T2 credential, operator stop channel, real Wallex account reader and journal
end-to-end gates.** No venue-write API, trade key, funded authority, emergency
exit guarantee or reliable external coverage exists in this branch.

All B1 changes are reviewed together in
[unified draft PR #10](https://github.com/AmirrezaFarnamTaheri/Trade/pull/10),
not merged into master separately.
