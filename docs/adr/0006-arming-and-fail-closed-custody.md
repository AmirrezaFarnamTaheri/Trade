# ADR 0006: Arming record, kill rules and fail-closed custody

Status: Wired in native source under ADR 0007/0008; local fault checks passed. Protected publication and installed-host qualification pending; execution stays DISARMED. Owner decisions OD-2, OD-5.

## Context

The owner wants the project always arm-ready with a one-click approval (OD-2), and asked for the safest handling
of privileged-thread faults and of reservation when the vault holds two journals (OD-5). At adoption these
were pure rules. ADR 0007 now connects them through a separate elevated native control channel; the browser
and the pure `exec_core::step` still cannot raise authority.

## Decision

1. **Arm record** (`exec_core::arming`). `approve(policy, preflight, approver, epoch, now)` refuses unless the
   owner policy is coherent (the same rules as `gym.services.arm_preflight.validate_policy`) and every preflight
   item passed; missing items count as failed. The record digest is SHA-256 over canonical text binding the policy
   file hash, approver, runtime epoch and window, so changing any limit changes the digest. Python computes the same
   digest (`arm_preflight.arm_record`) from the shared fixture `contracts/v1/fixtures/arm-record.json`.
2. **Kill rules are code.** `ArmRecord::check` disarms on expiry, a new runtime epoch (any restart), a privileged
   fault, a reconciliation mismatch, loss at the kill level or the cap, stale data and too many open orders.
   `admit_order` also enforces symbol, per-order notional, orders per day and open orders.
3. **Privileged fault stops the service** (unchanged behaviour, now tested): `exec_svc::supervise_privileged`
   marks the service failed on any T2 panic, error or unexpected return and stops T0 with it; restart builds a fresh
   `StopGate`, which is always `Disarmed`; `stopped_exit` reports the failing phase (`tests/privileged_fault.rs`).
4. **Verified available** (`exec_core::available::verified_available`): the pure rule now follows the
   [ADR 0008](0008-balance-observation-ordering.md) receipt contract. It requires two reads at the current
   credential/runtime/activity fence, matching durable copies, valid local clocks and at most 120-second
   age, then subtracts open holds. Disagreement disarms. Its field is `receipt_seq`, never a venue sequence.
   Native receipt production, activity events, admission, one-shot LIMIT transport and atomic settlement
   are connected in source. The matching protected binaries have not been published or qualified.

## Qualification still required

The privileged helper/listener, revisioned gate, native loss/counter measurements, dual balance receipts,
reviewed hold admission and native send/settlement path have local composition and fault tests. Owner evidence
is exact-hash-bound and cannot pass before the registered 2027-02-08 checkpoint. No actual attestation was
created. Installed-host/venue qualification and explicit owner publication approval remain separate work.
See [native order lifecycle](../../executor/docs/native-order-lifecycle.md) for the exact source boundary.
