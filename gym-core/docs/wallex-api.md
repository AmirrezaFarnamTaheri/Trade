# Wallex adapter contracts

This describes the application's implemented adapter boundary. The full official API, endpoint by endpoint,
is summarized in the [local Wallex reference](wallex-reference.md). Endpoint existence,
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

## Official reference cross-check

Checked on 2026-11-08 against [developers.wallex.ir](https://developers.wallex.ir/docs/) (all 120 pages,
plus its basic-services, spot, margin, trade-credit and OTC Swagger files) and the older
[api-docs.wallex.ir](https://api-docs.wallex.ir/). Where they differ, developers.wallex.ir is newer and wins.

| Topic | Official reference | This repository |
| --- | --- | --- |
| Market catalogue | `GET /hector/web/v1/markets`: `result.markets[]` with `is_spot`, `is_tmn_based`, `is_usdt_based`, `flags`, precisions | Same endpoint |
| Streaming | Centrifugo at `wss://api.wallex.ir/connection/websocket` (the `/ws` socket.io-style v1 is deprecated); channels `public:<SYMBOL>@trade`, `orderbook:<SYMBOL>@buyDepth` / `@sellDepth`, also `public:all@price`, `public:all@fairPrice`, `candle:<SYMBOL>@1m/1h/1d`, `private:user#<id>` | Same endpoint and trade/depth channels; the other channels are unused |
| Stream limits | 64 channels per connection; `{}` ping every 25 s, answer within 8 s or close 3012; several messages per frame; close codes 3500+ mean do not reconnect | All four handled in `services/collector.py` |
| Depth messages | Each message is a full snapshot of one side; subscribe returns no snapshot; no history, so gaps are lost; no timestamp or sequence number | Each message replaces the side; REST `/v1/depth` reseeds after (re)subscribe; receipt time is the only book clock |
| Trades | `price`, `quantity`, `sum`, `isBuyOrder`, `timestamp`; no trade ID. `isBuyOrder=true` means the resting buy was the maker, so the aggressor sold | Same reading. Collected data agrees: buyer-initiated prints sat at or above the prior ask 5,761 times against 1,014 at the bid. Identical prints are kept |
| Candles | `GET /v1/udf/history`, resolutions `1`, `15`, `60`, `240`, `480`, `720`, `1D`, `2D`, `3D` | Uses `1` and `60`. `D` answered `no_data` when probed on 2026-10-31; the documented daily code `1D` is not yet probed |
| Order placement | `POST /v1/account/orders`, at most 20 requests per 10 seconds; `client_id` letters, digits and `_` only | Not implemented here. The executor's order path must respect both: the operator-review ticket (contract v1) still accepts `-` and `.` in `client_id`, which Wallex would reject; a contract v2 must narrow it. Read paths keep accepting Wallex's own hyphenated IDs |
| Market orders | Cancelled if larger than the book or if they would move the price 2% from the last trade | Depth-walking replays reject orders whose walk passes 2% from the best level (`VENUE_PRICE_GUARD`); the book-size rule cannot be applied because only the top levels are collected |
| Price limits and hours | No band, reference price, daily open or market hours published | Band rules use the first observed mid of the Tehran day, labeled as an estimate; closures are inferred from data |
| Fees | `GET /v1/account/fee`: `result.<SYMBOL>.makerFeeRate`, `takerFeeRate`, `recent_days_sum` | Parsed per symbol; rates stay uncertified observations |
| Open orders and history | `GET /v1/account/openOrders` and `GET /v1/account/orders`, both with `page` / `per_page` (history at most 100, filters `market`, `type`, `side`, `from`, `to`); result is a map of order arrays | Both read with `page` / `per_page`; pages never prove completeness |
| Order detail | `GET /v1/account/orders/{client_id}`, with `fills[]` carrying `fee`, `feeAsset`, `isBuyer`, maker/taker coefficients | Used for known-client-order reads |
| Order types | `LIMIT`, `MARKET`, `STOP_LIMIT`, `STOP_MARKET` | Paper replays model market and resting limit orders only |
| Margin | `/margin-trade/v1/...` public markets, loan, dry-run, positions; a position lives at most 21 days and pays an extension fee every 4 hours | Public markets, loan and dry-run only; `max_age` and extension fees come from each market's returned terms |
| API keys | `x-api-key`; up to 90 days, not renewable; at most three keys; each trade-credit sub-account needs its own key; withdrawal permission requires the IP allowlist | `gymctl key set <role> --expires YYYY-MM-DD` records the expiry; `gymctl key show` warns 14 days ahead |
| Rate limits | None published beyond HTTP 429 | Collector paces REST at 4 requests per second and halves the rate on 429 |
