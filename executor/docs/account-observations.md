# Protected account observations

The service's existing administrator-only account GET path now records successful
balance, fee, known-client-order and explicit open-order/history page observations
in the protected custody ledger before replying.
The account helper, Python adapter, CLI and GUI retain their existing read-only
contracts and now expose optional receipt references through the
[v2 account delivery contract](../../contracts/v2/account-read-v2.md). No caller-supplied JSON, balance, unit precision or permission flag can
enter this service path. Order-detail identity must match the requested client
ID. Page identities come from the service's validated request; original response
digests remain bound to the received bytes. Page rows are bounded/sanitized and
persist under separate kind/page/per-page identities. Complete pagination echoes
must match; missing/partial echoes stay unverified. Pages provide no native
completeness, absence, atomicity or settlement proof.

The field mapping follows the [Wallex reference](https://api-docs.wallex.ir/):
`result.balances.<asset>.value/locked` and per-market
`makerFeeRate/takerFeeRate`. The current official developer site was also checked;
its balance page could not be retrieved during this implementation. No current
authenticated venue response was obtained, and this is not live schema acceptance.

## Parsing and persistence

Only a confirmed `success: true` object is normalized. Balance/fee money must be a plain,
nonnegative decimal string of at most 256 characters; numeric JSON, exponents,
signs, missing fields and malformed fractions are refused. Fee rates must be
strictly below one. Asset/market identities use bounded ASCII alphanumerics;
case-normalized collisions and duplicate JSON fields at every nesting level
are refused. The parser retains its recursion limit, a 1 MiB input bound and
a maximum of 1,024 collection rows.

Stored data contains only the required balance/fee fields. Account-level fee
metadata and other unknown fields are omitted. An empty collection stays empty;
it never supplies a zero fee, zero balance or proof that an account/order is
absent. Value and locked amounts are not interpreted as spendable money.

Known orders retain only bounded client ID, symbol, side, raw status, original
and executed quantity and optional reported fills. Unknown statuses stay raw;
they are never promoted to lifecycle or settlement truth. Order/fill amounts
are plain decimal strings of at most 80 characters and 24 fractional digits.
Fixed-point digit arithmetic checks execution against original quantity and
nonempty fill totals against execution without binary rounding. A missing or
empty fill list does not establish fee or fill coverage. Up to 256 fills retain
exact quantity/price/fee, fee asset and a bounded epoch or ISO-text timestamp;
the Python projection additionally validates ISO calendar values. Unknown
fields and the top-level fee with no explicit currency are omitted.

Each receipt binds the active custody credential generation, service runtime
epoch, request correlation, service request/receive clocks and original response
digest. The digest uses the existing ledger primitive:
`SHA256(32 zero bytes || u64_be(raw length) || raw response bytes)`. It is not an
independent signature. Raw venue bytes are not stored in the receipt. Transport
checks reject credential echoes in both raw bytes and decoded JSON field names,
strings and numbers, so JSON escaping cannot bypass the check.

The existing FULL-synchronous, hash-chained ledger commits the receipt before
delivery. An uncertain commit stops the privileged listener and service; it is
not converted into a successful read. Ordinary transport/schema failures return
no observation. No fallback credential or earlier response is substituted.

## Replay and freshness

Journal event tag **14** has the existing `TGOR1` prefix, name `main`, then:

| Field | Bytes |
| --- | --- |
| Kind (1 balances, 2 fees, 3 known client order) | 1 |
| Credential generation | 16 |
| Runtime epoch, started-at milliseconds, received-at milliseconds | 24 |
| Request correlation | 16 |
| Response digest | 32 |
| Canonical sanitized JSON | Remaining bytes |

Replay rejects unknown kinds, trailing/noncanonical bytes, retained private
fields, unknown or superseded credential generations, repeated request IDs and
regressed chronology, even when the outer hash chain is valid. Replay never
performs HTTP. A freshness query must match the journal's current credential
generation and supplied current runtime; the local clock cannot precede receipt.
Age includes the request duration. A request taking 12 seconds or more is refused;
freshness bounds must be explicitly supplied within 1..30,000 milliseconds.
Known-order cache entries are keyed by client ID, so reading a second order
does not replace the first. Each update remains in the hash-chained history.
Page entries separately retain request page and page size through restart,
under observation kinds 4 (open orders) and 5 (history). Changing the requested
page size does not reuse a previous page observation. Older readers that do
not understand these kinds refuse replay; rollback must keep a compatible reader.
Missing IDs produce no observation and never prove absence. Cancel acknowledgments,
later partial fills and venue status changes remain separate from settlement.

These are the latest *successful* observations, not a certificate that a later
read succeeded or that all exposure is known. No admission path consumes this
cache yet. Key rotation and a new service runtime invalidate freshness without
deleting history. Permission status remains UNVERIFIED.

Older binaries refuse tag 14. Once receipts exist, rollback must retain a reader
that understands this tag; deleting or rewriting custody history is not a
migration. Publication itself does not append account observations.

## Remaining execution requirements

The current binary bundle was installed and passed ordinary ACER operator review,
preparation/replay refusal/revocation, seven actual worker denials and four STOP
acknowledgements in 10–85 ms on the latest bundle. Receipt:
`.pi/qualification/20261106T0954273200041`. The service was stopped/disabled afterward. No
authenticated account read was made; this host test does not qualify venue
response schemas or the new receipt header against a real account.

This closes protected capture/normalization of balances, fees and known orders.
It does not establish key permissions, account ownership beyond the provisioned
key, instrument/rule/unit epochs, complete paginated external exposure, cost
basis, settlement, admission, arming or real submit/cancel transport. It does not
reserve money or grant funded authority. Those requirements remain explicit in
the [implementation plan](../../gym-core/docs/implementation-plan.md).
