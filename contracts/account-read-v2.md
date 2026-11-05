# Account read receipts, version 2

This is a bounded extension to the existing administrator-only protected GET
pipe. It accepts no URL, HTTP method, headers, credentials or claimed principal.
It grants no execution authority. The unchanged fixed resources remain balances,
fees, one known client order and explicit bounded open-order/history pages.

## Request and reply

The request uses the existing 128-byte canonical account request, with magic
`TGAREAD2` instead of `TGAREAD1`. All other resource, page, length, correlation
and reserved-field checks are unchanged. The service continues to accept v1
requests and returns their original 32-byte response header. A v2 client does
not silently downgrade if an older service refuses its request.

The v2 reply is a 144-byte header followed by 1..1,048,576 raw response bytes.
Every number in the header is unsigned, big endian.

| Offset | Length | Value |
| --- | --- | --- |
| 0 | 8 | `TGARESP2` |
| 8 | 16 | Exact request correlation |
| 24 | 4 | Body length |
| 28 | 1 | Receipt kind: 0 absent, 1 balances, 2 fees |
| 29 | 3 | Zero |
| 32 | 8 | Committed custody-journal sequence |
| 40 | 8 | Service runtime epoch |
| 48 | 8 | Service request time, Unix milliseconds |
| 56 | 8 | Service receive time, Unix milliseconds |
| 64 | 16 | Active credential generation |
| 80 | 32 | Original response digest |
| 112 | 32 | Committed journal event hash |

Balances and fees require their matching receipt kind. Order resources require
kind 0 and all bytes from offset 32 onward zero; they do not acquire fabricated
native receipt, pagination-completeness or settlement evidence. Present receipts
require positive sequence, runtime and request time, nonzero identities/hashes,
receive time at least request time, and duration below 12,000 milliseconds.
Truncated, unknown, miscorrelated or noncanonical headers are refused.

The service obtains sequence/hash from the actual FULL-synchronous append, not
an anticipated sequence. The helper verifies the kernel-reported pipe server
against the pinned service and checks the received body's digest:
`SHA256(32 zero bytes || u64_be(body length) || exact body bytes)`.
The Python adapter checks this digest again before accepting receipt metadata.

## Helper, journal and UI

The existing raw helper envelope gains an optional `service_receipt` object.
All its fields are strings, so JavaScript cannot round 64-bit identifiers:

`source`, `authority`, `resource`, `sequence`, `runtime_epoch`, `started_at_ms`,
`received_at_ms`, `credential_generation`, `request_id`, `response_digest`,
`event_hash`.

Source is `EXECUTOR_SERVICE_JOURNAL`, authority is `OBSERVATION_ONLY`, resource
is `BALANCES` or `FEES`. Correlation/generation use 32 lowercase hex characters;
digests use 64. Decimal integers are positive canonical u64 strings. Unknown
fields, repeated resources, mixed keys/runtimes, nonincreasing sequences,
regressed request clocks and repeated correlations are refused. Up to two
receipts accompany a collected account snapshot. Refreshing one resource
invalidates that reader's preceding receipt for that resource before the read,
including on failure. Existing helper envelopes without receipts remain
display-only observations; no receipt is invented for them.

The CLI includes accepted receipts and can save them with the account snapshot.
The journal validates them again on both write and read; manual/user transports
and non-main accounts cannot attach service receipts. The token-protected,
no-store account endpoint exposes the saved references. The EN/FA account page
shows expandable receipt details and exact per-market maker/taker fee fractions.

The browser does not contact the exchange or read the protected journal. Its
local receipt copies are not independent journal authentication, current
balances, verified key permissions, reconciled charged fees or money authority.
Amounts remain nonspendable observations. A locally altered snapshot cannot be
promoted into execution authority by carrying a plausible receipt reference.
