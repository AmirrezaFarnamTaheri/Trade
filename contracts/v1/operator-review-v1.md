# Protected operator review v1

This channel records, prepares and revokes exact operator intent. It does not submit an
order, reserve money, arm a workload or issue a trading capability. Its native
service/helper implementation has local build/regression evidence and passed
the installed ordinary ACER test on 2026-11-05; see
[the retained host result](../../executor/docs/service-publication.md#qualification).

## Entry points and authorization

The fixed local message pipe is `\\.\pipe\TradingGYM.Operate.v1`. The service
creates it with the selected operator logon's narrow DACL, rejects remote clients,
and verifies the connected Windows user and logon by impersonation before any
journal access. Caller-supplied JSON never names the principal. The listener is
separate from STOP and the elevated administrator pipe. A busy custody owner
returns DEFERRED rather than waiting behind an account HTTP request. Recovery
startup does not expose this listener. The isolation drill exposes it for denial
probes but refuses every review operation. Journal errors stop the service.

`gym-review.exe` accepts one bounded binary request on stdin, authenticates the
protected SCM identity and the connected pipe's kernel-reported server PID
before/after the exchange and emits only a bounded hex receipt envelope. It
requires SCM query permissions, not process-object access, termination or
SCM modification. The installer grants this helper operator execution permission;
credential provisioning, capital-limit changes and account-read helpers remain
administrator-only. The actual R0 worker was denied all seven protected targets
in the installed test; policy/deployment changes require a fresh check.

`gymctl operator-review INPUT.json` and the Operate page's **Protected operator
intent** panel use the same Python adapter. The panel requires explicit input and
button presses; it does not read, approve, poll or retry automatically. DEMO
disables the API and controls. `/api/operator-reviews` requires the per-run token
on reads and writes, plus an exact same-origin header on POST. The API allows one
active request, returns 409 while busy and rejects input above 16 KiB. This is a
separate API, not a research action or model/MCP tool.

## JSON requests

Only these fields are accepted:

| Action | Fields besides `action` |
| --- | --- |
| `status` | None |
| `inspect` | `client_id` |
| `approve` | `ticket` |
| `prepare` | `client_id`, `expected_sequence` |
| `revoke` | `client_id`, `expected_sequence` |

An approval ticket contains `client_id`, `account`, `base`, `quote`, `side`,
`base_decimals`, `price_decimals`, `quote_decimals`, `base_epoch`, `quote_epoch`,
`runtime_epoch`, `ceiling_sequence`, `expires_at_ms`, `quantity`, `worst_price`,
`max_quote_debit`, `min_quote_credit`, `preview_hash`, `rules_hash` and
`credential_generation`. Unknown fields, duplicate JSON keys, nonfinite values
and numeric amounts are refused.

Money is nonnegative plain decimal **text**, with no more fractional digits than
its declared precision; it must fit unsigned 64-bit quanta. No rounding occurs
on input. Runtime epoch, ceiling sequence, expiry milliseconds and expected
sequence are unsigned decimal **strings**, preserving integers above JavaScript's
exact-number range. Precision and asset unit epochs are bounded JSON integers.
Asset codes are uppercase ASCII letters/digits; client/account identifiers permit
ASCII letters/digits and `_.-`. Digests are nonzero lowercase hex: 32 bytes for
preview/rules, 16 for credential generation. These caller-supplied evidence
digests and account labels are bindings, not verified venue facts.

The service requires the current runtime epoch, credential generation and
installation-limit sequence; matching quote currency, unit epoch and precision;
the configured operator; and expiry after the actual review clock but at most
30 seconds ahead. A buy is refused while paused, exit-only or halted. All new
approvals are refused while halted. Buy maximum quote debit must cover gross
quantity times price rounded **up** to quote quanta and remain within the stored
capital limit. A sell declares zero quote debit and a positive minimum quote
credit no larger than gross proceeds rounded down. This validates an envelope;
it does not prove holdings, fees, available cash, liquidity or executable rules.

## Durability and uncertainty

The existing protected `Vault/exec_ledger.db` appends hash-verified,
FULL-synchronous approval/revocation records, retaining exact ticket bytes,
actual OS principal/logon, service clock and correlation ID. Request IDs and
client identities cannot be approved twice. Revocation requires the recorded
operator and exact current review sequence; it appends history and retains the
original ticket. It remains available after expiry, limit changes and clock
regression. Journal sequence, not wall-clock monotonicity, orders revocations.

`prepare` consumes the referenced review exactly once for durable preparation.
The service supplies its actual principal/logon, runtime, key generation, clock
and mode; the caller supplies only the identity and expected sequence. Current
limit/unit, expiry and mode checks run again. The clock cannot precede the review,
and both principal and logon must still match. A single journal event commits
the consumed state and its immutable ticket reference together. Restart or a lost
receipt cannot permit another preparation. No separate order, money reservation,
balance observation or transport attempt is created. Legacy simulation methods
cannot reuse the reviewed identity. Revocation is still allowed using the
preparation's new sequence, including after expiry or clock regression.

Receipts report STATUS, APPROVAL_RECORDED, PREPARED, REVOKED, MISSING, DEFERRED or REFUSED,
with the current runtime/limit/generation context and, when present, the exact
historical ticket. Consumers validate action, correlation, identity, ticket and
revocation version. Historical APPROVAL_RECORDED can be expired or invalidated by
a restart, changed limit or key rotation. PREPARED has the same limitation; it is
a preparation receipt, not an executable order intent or reservation. Neither
state implies current authority.

A timeout, disconnect or malformed receipt is **unacknowledged**, not a rollback.
The change may already have committed. Inspect the same client identity before
any manual retry; no layer automatically resubmits. Every Python/helper report
states `funded_authority=false` and `order_submitted=false`.

## Wire and verification

Unsigned integers use big endian. Request/reply sizes are 400/432 bytes; the
ticket occupies 352 bytes. Request magic is `TGREVW01`, action is at byte 8,
client ID length at 9, correlation at 16..32, expected version at 32..40,
and ticket/client ID at 48. Reply magic is `TGREPLY1`, state/mode/ticket flag at
8/9/10, correlation at 16..32, current epoch at 32, record sequence at 40, record
clock at 48, current ceiling sequence at 56, current credential generation at
64..80, and ticket at 80. Unused bytes must be zero. Rust encode/decode and Python
ticket encoding are the executable field-layout definitions.

The shared two-line `fixtures/operator-review-v1.hex` is **synthetic test data**:
an approval request and receipt. Python and Rust independently verify these
bytes. Regression tests cover precision/overflow/rounding, padding, identity and
action substitution, journal restart/revocation, token/origin checks, busy/size
refusal, helper output bounds, DEMO and UI duplicate submission/error handling.
Preparation is command 5 and PREPARED is reply state 7. Older builds reject these
and journal tag 12; preserve history and use a compatible build rather than
deleting records or assuming a rollback can interpret new events.

Still required: atomic admission/reservation of real order intents, independently established account and
instrument/rule/cost identities, method certification, money-limit enforcement,
arming and real transport/reconciliation. No real credential or loss budget was
configured, and no exchange request is made by this workflow.

## Native reservation mechanics

The offline native journal now exposes reserve_prepared_intent(context, balance)
to join an already prepared review, its exact canonical ticket, a fresh local
attempt and its hold in **one** FULL-synchronous event. Replay validates the same
transition. The service pipe, helper, GUI and MCP do not expose this method:
caller-supplied balances are not authenticated account observations.

Admission rechecks the review sequence, actor/logon, runtime, credential
generation, current installation limit, expiry, stop mode and request identity.
Buys hold the maximum reviewed quote debit; sells hold reviewed base quantity.
Quote holds across accounts share the installation hold ceiling, with checked
overflow. Existing active untyped holds and incompatible base units/epochs are
refused; snapshot accounts/assets, monotone sequences and consistent shared-cash
anchors are enforced by the existing reservation book. The reviewed price's
explicit decimal scales are retained and never converted to legacy simulation
price units.

Revocation removes consent without releasing a hold. Local denial before sending
can release it; unknown or unsettled outcomes retain it across restart. This is
offline journal mechanics, not a funded permit, a session/loss/exposure cap, venue
settlement proof or live transport integration.

Journal tag **13** contains the preparation context with tag 13 replacing tag 12,
the exact 352-byte ticket, then available balance quanta and observation sequence
as two big-endian u64 values. Its account/asset derive from the exact ticket.
Older binaries refuse this event. Preserve history and use a compatible build;
do not downgrade or delete records to reopen it.
