# ADR 0007: Wire the funded path end to end, behind an owner arm button

Status: Accepted (owner decision 2026-11-14: "wire the funded executor but keep it blocked by a button").
Source wiring and local fault checks are implemented; the protected installation remains unchanged and disarmed.

## Context

ADR 0006 built the arm record, kill rules and verified-available as pure, tested rules, deliberately unwired.
The owner now wants the path connected so that arming is one explicit approval away, with everything below it
fail-closed. Six external audit reports (2026-11-14) reviewed the same modules and agreed on the order of work.

## Decision

1. **Authority lattice.** Every component carries a maximum authority and may never mint a higher one:
   `OBSERVE < ANALYZE < PROPOSE < PAPER_DECIDE < PAPER_EXECUTE < PROTECTED_REVIEW < FUNDED_ADMISSION < FUNDED_EXECUTE`.
   Models and research tools top out at PROPOSE. The browser workspace tops out at PAPER_EXECUTE plus editing the
   arm-policy file; approval itself stays on the privileged pipe with an elevated operator, never a loopback route.
2. **Owner policy is a file the owner edits, bound by hash.** `arm-policy.json` in the data root, validated by
   `gym.services.arm_preflight.validate_policy`, editable from the workspace (`arm-policy-read`/`arm-policy-save`
   research actions) and the CLI. The arm record binds its SHA-256, so editing the file invalidates any approval.
3. **Starting limits** (owner asked for reasonable values; each is changeable in the file, inside the bounds the
   validator already enforces):

   | Limit | Value | Why |
   | --- | --- | --- |
   | Markets | BTCUSDT only | The only market with a passing screen (T6) and a forward journal |
   | Loss cap | 50 USDT | Pocket money; the probe answers "do real fills match the simulator", not "is this profitable" |
   | Kill loss | 20 USDT | Kills well before the cap, leaving room for the exit itself |
   | Per-order notional | 10 USDT | Small enough that one bad order is noise; above the venue's ~0.4 USDT BTCUSDT minimum |
   | Orders per day | 10 | A probe cadence, not a trading cadence |
   | Open orders | 2 | One working entry plus one working exit |
   | Stale data | 120 s | Twice the collector heartbeat; no fresh verified balance and quote means no new order |
   | Arm expiry | 7 days | Re-approval weekly; any restart disarms regardless (new runtime epoch) |

4. **Wiring order**, each step its own PR, the service disarmed throughout:
   a. Mount `TGREVW02` on the operate pipe (v1 permits `.` and `-` in client IDs, which the venue rejects).
   b. Cut `ReservationBook` over to `ActiveHoldBook` (ADR 0003) so external credits cannot wedge reservations.
   c. Ledger checkpoint events with verified state digests, and tip caching, so startup replay is bounded
      (today it is a full scan, and the in-memory journal clones its maps on every append).
   d. Privileged arm request + approval on the privileged pipe, binding the policy hash; an `Armed` mode in the
      stop gate that any fault, restart, kill rule or expiry collapses back to `Disarmed`.
   e. `verified_available` in admission under [ADR 0008](0008-balance-observation-ordering.md): two fresh native
      service receipts, own-activity fencing and conservative spendable amounts; stale/disagreeing journals disarm.
   f. End-to-end tests: starts disarmed, stays disarmed on every injected fault, and the kill table fires on
      each input (expiry, epoch change, privileged fault, reconciliation mismatch, loss, staleness, open orders).
5. **What arming still requires after the wiring exists:** every preflight item green (policy, service, trade key,
   fresh feed, fresh backup, no failing health check, clean reconciliation), and the one-click approval by the
   elevated operator. Nothing in this ADR funds anything by itself.

## Consequences

- The workspace can prepare everything; it cannot arm. A compromised browser session can at worst write a
  stricter-or-different policy file, which un-arms the system rather than widening it.
- The 2027-02-08 checkpoint still governs: no funded probe without prospective paper evidence, whatever is wired.

## Source progress (2026-11-16)

| Step | State |
| --- | --- |
| a: review v2 | Source listener, helper, Python relay and operator protocol self-check require v2; historical v1 fixtures remain. Matching protected publication and host qualification pending. |
| b: active holds | New reviewed/execution holds use ActiveHoldBook; old aggregate events replay with their original semantics. Mixing outstanding old/new models is refused. |
| c: checkpoints | Full-prefix independent decode/state comparison, bounded indexed identity caches, tip/suffix projection and paged checkpoints. One-million-row request history opens in 1.70 s and completes audit in 19.40 s; a separate 2,401-live-intent fixture passes. States above 64 MiB retain verified replay. See checkpoint evidence. |
| d: privileged arm | Elevated `gym-arm`, actual user/logon checks, policy/evidence hashes, revision CAS, synced approval receipt, expiring effect lease and native safety worker. Native local backup bundle; no off-machine schedule. Source only; installed host unqualified. |
| e: verified available admission | Native single-flight reads dual-commit both copies. Actual fees/book, receipt fences, holds, net own cash debits and installation limits bound one prepared LIMIT order. Separate elevated `gym-submit`; terminal fills and later balance pairs close/release atomically. Local order never claims exchange snapshot order. |
| f: end-to-end arm fault tests | Local producer/controller/admission/attempt/journal composition covers stale/unequal reads, partial copies, own activity, policy/credential/runtime changes, STOP, write failure, expiry, uncertain sends, non-retry, settlement and every kill input. Synthetic local checks do not qualify an installed funded path. |

The owner canceled off-machine backup/second-host restoration. That does not make
the arm preflight's missing backup or any other missing evidence pass. Keep each
native step separate for owner review; none of this source is a deployment approval.
See [native order lifecycle](../../executor/docs/native-order-lifecycle.md) and the
[review branch record](../../evidence/archive/executor/2026-11-16-review-branches.md). No real order, owner approval evidence
or funded permission was manufactured. The service still requires the prospective checkpoint.
