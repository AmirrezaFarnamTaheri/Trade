# Executor checkpoint verification

Date: 2026-11-16. Local source verification, with execution disarmed and the protected installation unchanged.

The journal verifies every stored hash-chain byte at open, restores the newest canonical checkpoint and suffix,
then independently decodes the full prefix on another SQLite connection. A valid digest is insufficient: the
checkpoint's canonical state must equal the independently derived state. Mutation waits for that audit, and an
audit failure prevents further writes. The native watchdog and arm preflight consume the audit status separately.

Request/generation history moves into a durable indexed projection rebuilt transactionally from the verified
prefix. Recent caches cap at 1,024 combined IDs. A new checkpoint carries no accumulated identity sets; older
canonical checkpoints retain their original representation. Large snapshots use pages and a final manifest;
incomplete pages after a crash carry no authority. State above 64 MiB retains verified full replay as an explicit
memory limit. Retained intent/approval state still grows with its cardinality.

## Release qualification

Host/toolchain: local Windows, x86_64-pc-windows-msvc, rustc 1.96.0 (ac68faa20), optimized release build with
overflow checks enabled. Fixtures were just written, so the OS file cache was warm. Fixture construction is
excluded from the startup timings.

| Workload | Stored bytes and cardinality | Open, full hash scan and restore | Open through independent full decode/index publication | Bound |
| --- | --- | --- | --- | --- |
| 1,000,000 records | 1 credential, 999,998 changing balance observations with unique request IDs, 1 checkpoint; 1 current balance resource; 175,893,778 payload bytes, min 61/max 1,065/mean 175.893778 bytes per event; SQLite 303,747,072 bytes including identity projection | 1.6988705 s | 19.4026999 s | 30 s / 120 s |
| 2,401 active intents | Independent pending intents with long valid names; snapshot exceeds one event and uses committed pages; SQLite 4,452,352 bytes | 34.6776 ms | 187.3659 ms | Ordinary replay assertions; no extrapolated million-active-order claim |

Run from the repository root:

```powershell
rtk proxy cargo test --offline --release -p exec-svc --lib one_million_row -- --ignored --nocapture
rtk proxy cargo test --offline --release -p exec-svc --test offline_order_recovery chunked_checkpoint -- --nocapture
```

The million-row case is deliberately ignored by the ordinary fast suite and was explicitly run successfully.
Its request IDs are distinct and each observation changes the current balance value; it is not a million no-op
events. It proves historical request-index behavior, not a million simultaneous active orders or venue behavior.

## Correctness checks

- A canonical, hash-valid checkpoint with a recomputed digest but forged account state fails independent replay;
  the journal reports Failed and refuses mutation.
- Unknown hash-valid prefix bytes hidden behind a later checkpoint fail the independent decoder.
- Old request IDs and superseded credential generations remain duplicate-protected after cache eviction and restart.
- Legacy checkpoint canonical encoding and old inflight/cancel recovery rules remain valid.
- Paged snapshots reject changed content, order, ordinal, base anchor and missing pages. Partial pages after a crash
  do not create intents and do not prevent a subsequent valid journal operation.
- Anchors before, on and after a checkpoint verify against the complete chain; substituted or future anchors fail.
- Full native workspace/all-targets tests passed: 204 ordinary tests, one explicit scale test excluded from that
  ordinary count and separately passed above. Clippy with warnings denied and cargo formatting checks passed.

No protected service installation, cold-disk/VM/second-host timing, hosted CI or venue qualification was performed.
The owner canceled off-machine backups. The source verification does not approve publication, arming or funding.
