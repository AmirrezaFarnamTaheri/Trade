# ADR 0006: Arming record, kill rules and fail-closed custody

Status: Implemented as pure rules in exec-core; not wired (the service stays DISARMED). Owner decisions OD-2, OD-5.

## Context

The owner wants the project always arm-ready with a one-click approval (OD-2), and asked for the safest handling
of privileged-thread faults and of reservation when the vault holds two journals (OD-5). No arming path exists:
`exec_core::step` can only reduce authority, and `Mode` has no armed state.

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
4. **Verified available** (`exec_core::available::verified_available`): newest observation by venue sequence
   across both journals, refused when older than a bound, and refused with `disarms() == true` when two journals
   report different amounts for one sequence.

## Not done, deliberately

- Wiring: a privileged arm request on T2, an armed mode in the stop gate, the approval screen and the per-tick
  loss measurement. All of it changes the money path and needs passing automated authority, security and recovery checks.
- The review-v2 codec (`exec_ipc::review_v2`, TGREVW02) and `reserve_prepared_intent` remain **test-only**: exported
  and tested, not mounted by the service. They are mounted with the arm path, after those checks.
