# Native reviewed LIMIT-order source

Status: locally tested source, **unpublished / installed host unqualified**.
Execution remains disarmed. No real order or owner attestation was produced.
The registered prospective review date is **2027-02-08**.

## Authority and evidence

`gym-review` and the browser's Operate relay only review, prepare, inspect or
revoke an exact ticket. They cannot encode a submission or arm request. Separate
administrator-only `gym-arm` and `gym-submit` helpers authenticate the fixed SCM
process. The service derives their elevated Windows user/logon and checks the
protected operator binding; no request supplies that identity or account facts.

Native facts come from fixed-origin HTTPS: books, current fees, known own orders,
the complete open-order page and two matching balance reads. Balances commit in
both journals before use. Own activity discards the pair. Missing, stale,
disagreeing, incomplete or uncertain evidence blocks and disarms. Local receipt
order cannot establish the venue's snapshot age or exclude an upstream cache.

The exact ticket binds generation, runtime, units, current installation limit,
expiry, prices, quantities and preview/rules hashes. Native admission rechecks
fees, source age and the cash envelope. The installation budget counts net own
cash debits plus outstanding quote holds and the proposed buy hold; deposits do
not replenish it. Sells use only inventory derived from own fills and hold an
outgoing-base fee allowance. Venue precision/lot acceptance remains a venue
qualification item; a supplied rules hash alone does not certify a catalogue.

## Explicit owner review

No approval file is created automatically. Beside an absolute local
`arm-policy.json`, `arm-evidence.json` must contain these exact fields:

| Field | Contract |
| --- | --- |
| `schema` | Integer 1 |
| `policy_sha256` | Exact 64-character lowercase policy hash |
| `credential_generation` | Current native generation, 32 lowercase hex characters |
| `runtime_epoch` | Current native runtime integer |
| `reviewed_at_ms`, `valid_until_ms` | Actual review/window timestamps; both review and use must be on/after the checkpoint; the window cannot exceed policy expiry |
| `trade_permission` | `owner_reviewed_trade_no_withdraw` |
| `prospective` | Object with `checkpoint: "2027-02-08"`, `decision: "proceed_with_bounded_probe"`, absolute local `artifact_path` and exact `artifact_sha256` |

The native helper displays both files and their hashes. The permission and
prospective fields are owner attestations, not venue-issued permission or a
profitability test. The service reads and hashes the actual referenced artifact
(maximum 16 MiB), rejects unknown fields, and holds read-only file leases through
approval/effect. A local journal/ciphertext backup bundle is created and verified
under protected custody before arming; there is no backup schedule or off-machine
copy. No second-host restore is required.

## Future qualified-host workflow

Only after explicit publication approval, installed-host qualification, a reviewed
positive installation budget, key permission review and the prospective checkpoint:

1. Inspect the owner files with `gym-arm inspect ABSOLUTE_ARM_POLICY_PATH` and
   obtain native runtime/generation status. Inspecting files grants no authority.
2. While disarmed, review and prepare one exact entry ticket through the existing
   operator channel. Preparation has the ticket's short expiry (at most 30 s).
3. In the elevated console, run `gym-arm approve ABSOLUTE_ARM_POLICY_PATH POLICY_SHA256 EVIDENCE_SHA256`.
   Type the displayed approval phrase. Actual native preflight must pass. The
   approval receipt syncs before the gate CAS; slow writes, a stop, changed files
   or expired evidence cannot open it.
4. Run `gym-submit submit CLIENT_ID PREPARED_SEQUENCE RUNTIME_EPOCH`. It displays
   the matching prepared ticket and requires an exact interactive confirmation.
   It binds the arm revision captured before that confirmation.
5. Inspect with `gym-submit inspect CLIENT_ID`. An unacknowledged or uncertain
   attempt is never automatically retried. An expired preparation needs a new
   reviewed identity, not reuse of a consumed identity.

Each send attempt invalidates earlier balances and disarms. A new approval needs
two new agreeing reads and clean reconciliation. This source path implements
manual LIMIT buys/sells only; it adds no automated strategy, venue cancellation,
withdrawal or certified protective exit.

## Durable results

| Result | Meaning |
| --- | --- |
| `Refused` | Native checks refused this request; inspect the existing identity before further action |
| `NotSent` | Proven unsent attempt abandoned; its hold is released and identity consumed |
| `Pending` | Outcome uncertain; hold retained, admission blocked, no retry |
| `Observed` | Matching native order evidence; settlement still required |
| `Settled` | Complete terminal fills and a later unlocked balance pair closed/released in one commit |
| `Missing` | No durable native attempt for this identity; a prepared review is still a separate record |

A halt blocks new effects; it cannot recall bytes already sent or cancel an
accepted venue order. HTTP rejection, missing order evidence or an uncertain
commit may require explicit investigation and keep the hold blocked. Local tests
and builds do not establish installed identity, live fees/fills, venue permission,
profitability or protective behavior.
