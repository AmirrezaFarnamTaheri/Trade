# Wallex adapter contracts

This describes the application's implemented adapter boundary. Endpoint existence,
public catalogue eligibility and a successful read do not establish account
permissions or execution qualification.

## Public observations

`adapters/wallex.py` pins REST to `https://api.wallex.ir` and streaming to
`wss://api.wallex.ir/connection/websocket`. Public collection uses no credential.

| Request | Consumer |
| --- | --- |
| GET /hector/web/v1/markets | Instrument catalogue, observation selection and explicit exclusions |
| GET /v1/depth?symbol= | Initial/reconnected book snapshots and stale-side recovery |
| GET /v1/trades?symbol= | Recent prints; receipt clocks remain distinct from venue-event clocks |
| GET /v1/udf/history | Explicit bounded candle retrieval and point-in-time crosschecks |
| Public orderbook:SYMBOL@buyDepth, orderbook:SYMBOL@sellDepth, public:SYMBOL@trade | Streaming depth and trade observations |

The collector selects the eligible TMN/USDT spot universe by default, includes
explicit catalogue/exclusion reasons, shards below the 64-channel connection
limit, honors REST backoff and records source failures. The native decision-bar
catalogue and provider-fetch resolutions are separate. Only supported fetch
codes are sent; unavailable history is not synthesized or replaced with a current
download. See [coverage contracts](research-workspace.md) and
[storage](storage.md) for publication and receipt clocks.

## Margin research

`adapters/wallex_margin.py` permits only the fixed public markets read and loan /
dry-run calculators under `/margin-trade/v1/public/`. Inputs, response bytes,
redirects and encodings are bounded/validated. It has no position-write path.

Use each observed market's risk coefficient grid, collateral and loan currency,
liquidation threshold, maximum age and fee fields. Do not infer one global
leverage setting or equate credit ratio with the trader's unborrowed capital.
See [margin contracts](wallex-margin.md) for exact fields, costs and paper behavior.

## Protected account observation and execution

The read-only account boundary permits balances, fees, client-ID order status,
open-order and order-history reads. Account identity, response identity, pagination,
observed fills/fees and settlement completeness remain separate checks. Failure
or an empty page does not prove that an order is absent or a balance is spendable.
See [account contract](../../contracts/account-read-v2.md) and
[service observations](../../executor/docs/account-observations.md).

Funded submission, cancellation, borrowing, sub-account transfers and protective
venue orders require the separately implemented and qualified protected transport.
They are unavailable in the current application. Exact intent must be durable
before first send, unresolved sends must survive restart, and unknown orders must
retain reservations until reconciliation. Withdrawals and account-money movement
are outside ordinary strategy authority. Current gates are in
[acceptance status](acceptance-status.md) and the
[implementation plan](implementation-plan.md).
