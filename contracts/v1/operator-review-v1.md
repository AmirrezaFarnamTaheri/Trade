# Protected operator review v1

This channel records and revokes exact operator intent. It does not submit an
order, reserve money, arm a workload or issue a trading capability. Its native
service/helper implementation has local build and regression evidence; this
version has not been installed or qualified under the ordinary ACER logon.

## Entry points and authorization

The fixed local message pipe is `\\.\pipe\TradingGYM.Operate.v1`. The service
creates it with the selected operator logon's narrow DACL, rejects remote clients,
and verifies the connected Windows user and logon by impersonation before any
journal access. Caller-supplied JSON never names the principal. The listener is
separate from STOP and the elevated administrator pipe. A busy custody owner
returns DEFERRED rather than waiting behind an account HTTP request. Recovery and
drill startup do not expose this listener. Journal errors stop the service.

`gym-review.exe` accepts one bounded binary request on stdin, authenticates the
SCM-pinned service process before/after the exchange and emits only a bounded
hex receipt envelope. It requires query permissions, not process termination or
SCM modification. The installer grants this helper operator execution permission;
credential provisioning, capital-limit changes and account-read helpers remain
administrator-only. Worker denial and these helper permissions need a new
installed-host drill for this binary set.

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

Receipts report STATUS, APPROVAL_RECORDED, REVOKED, MISSING, DEFERRED or REFUSED,
with the current runtime/limit/generation context and, when present, the exact
historical ticket. Consumers validate action, correlation, identity, ticket and
revocation version. Historical APPROVAL_RECORDED can be expired or invalidated by
a restart, changed limit or key rotation. It never implies current authority.

A timeout, disconnect or malformed receipt is **unacknowledged**, not a rollback.
The change may already have committed. Inspect the same client identity before
any manual retry; no layer automatically resubmits. Every Python/helper report
states `funded_authority=false` and `order_submitted=false`.

## Wire and verification

Unsigned integers use big endian. Request/reply sizes are 400/432 bytes; the
ticket occupies 352 bytes. Request magic is `TGREVW01`, action is at byte 8,
client ID length at 9, correlation at 16..32, expected revoke sequence at 32..40,
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

Still required: installed ordinary-operator and worker-denial tests, atomic
approval consumption by real order intents, independently established account and
instrument/rule/cost identities, method certification, money-limit enforcement,
arming and real transport/reconciliation. No real credential or loss budget was
configured, and no exchange request is made by this workflow.
