# ADR 0004: Bounded executor startup

Status: Partly implemented (finding A-5)

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

## Implementation status (2026-11-10)

- Measured (`exec-store/tests/startup_scale.rs`): 200,000 ledger rows of 300 bytes open, verify and fully replay in
  0.31 s in the shipped release build (3.95 s in a debug build). Journal decode adds to this, and the vault opens
  two journals, so the fixed window was the real risk only for long ledgers.
- Done: the service now waits up to two minutes for the privileged thread, reporting START_PENDING with an
  advancing checkpoint every second, instead of failing after five seconds.
- Still proposed: checkpoint events with a derived-state digest and suffix-only replay. Not needed at current
  volumes; revisit when the startup measurement in the service log approaches the two-minute bound.
