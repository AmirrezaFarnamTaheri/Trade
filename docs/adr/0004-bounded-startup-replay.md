# ADR 0004: Bounded executor startup

Status: Implemented in source; protected-host qualification pending (finding A-5)

## Context

At open, the recovery journal replays the whole ledger from sequence 0 and hash-checks every row inside the
privileged thread, while the main thread waits five seconds for it to report ready. Open cost grows with the
ledger, so a long enough ledger makes the service fail to start with an error that looks like a pipe fault.

## Proposal

- Write a **verified checkpoint** event every N records: the sequence, the head hash and a digest of the derived
  state (credential metadata, ceiling, approvals, reservations, account-observation keys).
- At open, verify the chain hash up to the newest checkpoint quickly (hashes only, no decoding), restore the
  derived state from the checkpoint, and decode only the suffix. Run full decode-and-compare in the background
  and stop the service (ADR 0002) if it disagrees with the checkpoint.
- Report startup progress to the service manager (`SERVICE_START_PENDING` with a wait hint) instead of a fixed
  five-second wait.
- Keep the in-memory request-id sets bounded by moving old ids behind the checkpoint, where a lookup falls back
  to the ledger.

## Validation required before acceptance

- A synthetic ledger of 10^6 rows starts within a stated bound.
- A checkpoint whose derived-state digest is wrong stops the service.
- The ledger anchors kept beside the backups (R-3) still verify across a checkpoint.

## Implementation status (2026-11-16)

- Measured (`exec-store/tests/startup_scale.rs`): 200,000 ledger rows of 300 bytes open, verify and fully replay in
  0.31 s in the shipped release build (3.95 s in a debug build). Journal decode adds to this, and the vault opens
  two journals, so the fixed window was the real risk only for long ledgers.
- Done: the service now waits up to two minutes for the privileged thread, reporting START_PENDING with an
  advancing checkpoint every second, instead of failing after five seconds.
- Canonical checkpoint events bind committed state, its digest and the previous ledger tip. The journal writes
  one every 1,024 records and restores its state plus the suffix; every historical byte remains hash-checked.
  State larger than the 1 MiB event limit uses ordered, hash-bound pages followed by a commit manifest. A crash
  before that manifest leaves inert pages, so no partial checkpoint can become state authority. Legacy canonical
  checkpoint encodings remain readable.
- A separate SQLite connection independently decodes the full prefix, checks every checkpoint against its own
  projection, and atomically rebuilds the durable identity index. It never trusts a checkpoint merely because
  the supplied digest and event chain agree. The journal exposes Pending/Verified/Failed status; mutations wait
  for verification and refuse after failure. The native service watchdog and arm preflight must use this status.
- Recent request/generation caches hold at most 1,024 combined identities and clear at checkpoints. Old duplicate
  requests and credential generations are found through the indexed ledger projection, rebuilt from authoritative
  bytes on every open. Checkpoints do not carry the accumulated identity history. Live intents/approvals remain
  proportional to their retained state; this is not a bound on a million simultaneously active orders.
- A local release qualification with 1,000,000 valid records and 999,998 distinct balance-request IDs opened,
  hash-verified and restored in 1.699 s; independent full decode/index publication completed in 19.403 s from open.
  The registered bounds are 30 s and 120 s. A separate 2,401-active-intent paged-state fixture opened in 34.678 ms
  and completed full replay in 187.366 ms. Backup anchors before/on/after a checkpoint verify, and altered anchors fail.
- Snapshots above 64 MiB deliberately retain verified full replay; the memory budget needs qualification before
  raising that ceiling. Full chain hashing still grows with history. These measurements use a warm OS file cache
  on the local Windows host and do not qualify a protected service installation, cold disk, VM or second host.

Reproduction commands, workload sizes and adversarial checks are recorded in
[the qualification receipt](../../evidence/archive/executor/2026-11-16-executor-checkpoint-verification.md).
