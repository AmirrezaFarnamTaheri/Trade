# Wallex margin rules and integration

Reviewed 6 November 2026 local time. The public REST probes and CLI receipts
were recorded on 5 November UTC. This is a **paper integration**; the protected
executor remains disarmed and has no margin write transport.

## Sources and observed rules

Primary references are Wallex's [market rules](https://developers.wallex.ir/margin/activemarkets),
[preview reference](https://developers.wallex.ir/margin/dryrun), the previously
retained 114-page official documentation corpus, and the current public
`https://api.wallex.ir/mcp` **tools/list** response (52 tools). Only discovery
was used; no MCP trading tool was invoked. Some developer-document links now
serve an empty application shell or 404, so the dated corpus and live responses
are distinguished rather than claiming every old page was freshly fetched.

Live `GET /margin-trade/v1/public/markets` returned **35 markets**, with
`min_risk_coef=1`, `max_risk_coef=10`, `risk_coef_step=0.5`,
`liquidity_margin=0.15`, and `max_age=1814400` seconds (21 days).
These are observed values, not code constants. The GUI takes each market's
minimum, maximum and step from the saved response. The server independently
validates the exact decimal grid relative to its minimum.

Credit ratio is Wallex's `risk_coef`. For the tested 100-USDT collateral and
ratio-2 BTC/USDT requests, the LONG preview returned a 200-USDT loan; the SHORT
preview returned a BTC loan. Collateral remains the guarantee, not additional
borrowed position notional. Do not label this automatically as generic futures
leverage or add one to the ratio.

The public loan calculator returned a **50–850 USDT** collateral range for those
requests. It is fetched for every preview, including market, direction, price
and credit ratio; it is not a universal collateral range. Both loan and preview
endpoints answered without an API key in this check, despite the older Swagger
authentication declaration. Authentication errors remain errors; no key is
obtained, requested or silently added by this adapter.

The returned preview is authoritative input for opening/trading/extension fee
amounts and currencies, warning/liquidation prices, extension period and maximum
age. In the observed responses, LONG trading fees were in BTC and its opening/
extension fees in USDT; SHORT trading fees were in USDT and opening/extension
fees in BTC. Extension period was 14400 seconds. The implementation preserves
those currencies and consumes returned periods instead of assuming all costs
are USDT or hardcoding a four-hour/21-day contract.

## Endpoint inventory and boundaries

Margin endpoint paths below come from the official references and current tool
inventory. A read or calculator is not an order or account permission.

| Method | Path | Contract / implemented scope |
|---|---|---|
| GET | `/margin-trade/v1/public/markets` | Implemented credential-free market rules and immutable receipt. |
| POST | `/margin-trade/v1/public/loan` | Implemented public collateral minimum/maximum and loan check; cannot open a position. |
| POST | `/margin-trade/v1/public/dry-run` | Implemented public preview, request/response binding and currency checks. |
| GET | `/margin-trade/v1/public/ratio/{market}` | Public LONG/SHORT aggregate ratio. Reviewed reference; not evidence of profitability or account eligibility. |
| GET | `/margin-trade/v1/user/levels` | Authenticated account limits; unavailable to the public adapter. |
| GET | `/margin-trade/v1/user/levels/{market}` | Authenticated per-market account limits; public maximum is not a personal entitlement. |
| GET | `/margin-trade/v1/user/pnl` | Authenticated account PnL; not replaced by paper PnL. |
| GET | `/margin-trade/v1/orders` | Authenticated margin orders, filters for activity/market/position/direction/type. Spot order reads are separate. |
| GET | `/margin-trade/v1/positions` | Authenticated positions; preserve unknown lifecycle states. |
| GET | `/margin-trade/v1/positions/{id}` | Authenticated position details, fills, interest and expiry. |
| POST | `/margin-trade/v1/positions/{id}/profit` | Authenticated close-profit calculator; calculation does not close the position. |
| POST | `/margin-trade/v1/positions` | Opens a funded position. Excluded from the transport; no documented caller idempotency key. |
| PATCH | `/margin-trade/v1/positions/{id}/collateral` | Changes real collateral; excluded from the transport. |
| PATCH | `/margin-trade/v1/positions/{id}/sltp` | Changes real protection prices; excluded from the transport. |
| PATCH | `/margin-trade/v1/positions/{id}/close` | Real close request; excluded. Older prose requires price; current MCP description says optional. No immediate fill or settlement inferred. |

Preview input is exactly `market`, `side` (`long`/`short`), `collateral`,
`risk_coef`, `open_price`, optionally `stop_loss`/`take_profit`. Decimal values
are strings. LONG stops are below entry and targets above it; SHORT reverses
those relationships. Public loan and preview loan values/currencies must agree.
Unknown fee currencies, inconsistent trigger levels, expired catalogue receipts,
duplicate JSON keys, redirects, oversized replies and unknown request fields
fail closed. No arbitrary endpoint, private header or credential is accepted.

The reviewed trade-credit APIs are a **different product**: package collateral
and credit share a sub-account; liquidation acts on the whole package. Its
example 60M collateral + 600M credit gives 660M starting assets, unlike the
per-position margin loan model. Do not reuse margin ratios as package leverage.

| Trade-credit family | Paths / important rules |
|---|---|
| Offerings | `GET /v1/prop/packages`, `GET /v1/prop/packages/{id}`; respect returned excluded markets and package duration/fees. |
| Eligibility | `GET /v1/prop/user/packages/{id}/check-availability`; KYC and collateral checks require account context. |
| State and history | `GET /v1/prop/user/packages/active`, `/overview`, `/history`, `/history/{subAccountClientId}`. Preserve raw status, fee and close-reason fields. |
| Sub-account reads | `GET /sub-accounts`, `/v1/account/balances-detail`, `/sub-accounts/transfers`; account-bound keys and the documented hyphenated `sub-account-client-id` header require qualification. |
| Commitment changes | `POST /v1/prop/user/packages`, `DELETE /v1/prop/user/packages`, `POST .../enable-renew`, `POST/DELETE .../connect-to-wallet`, `POST /sub-accounts/transfers`. No call is implemented or issued by the margin adapter. |
| Automatic top-up | Wallet connection can draw additional main-wallet funds. It cannot be treated as a fixed-collateral loss limit. |

Other API families checked against the 52-tool inventory: public spot market/
depth/trade/candle reads; authenticated account balances, fees, bank/wallet reads;
spot order list/detail/create/cancel; OTC markets/price/easy-trade. They retain
their existing owners. Margin does not gain credentials, spot order rights,
OTC execution, transfers, withdrawals or bank mutations through these aliases.
The MCP description is not an authorization mechanism or a replacement for
the executor's exact endpoint allowlist.

## GUI, CLI and receipt flow

**Paper research → Wallex margin** loads the current rules explicitly. Choose a
market, direction, collateral, ratio and entry limit; optionally copy a qualified
observed bid/ask and enter stop/target prices. Preview first checks the loan
calculator's collateral range, then saves the venue response. Changing any
request input invalidates the previous preview. DEMO cannot contact the venue.

The GUI and CLI share the supervised research actions:

```powershell
gymctl research margin-markets
gymctl research margin-preview preview-request.json
gymctl research margin-replay replay-request.json
```

`margin-preview` input: `{"catalogue_id":"<saved id>","request":{...}}`.
`margin-replay` input: `preview_id`, zoned ISO `from`/`to`, exact decimal string
`exit_fee_rate` (an explicitly assumed quote-currency exit fee), and optional
integer `holding_seconds` (use JSON null for no scheduled close).

Receipts are immutable native artifacts in `data/live/margin/<id>.json`, retaining
source URLs, receipt clocks, body digests, rules, currencies and input identities.
A local digest is integrity evidence, not independently authenticated venue or
account authority. Previews require catalogue age no more than five minutes.
Replay starts after the preview receipt: current terms cannot become knowledge
in an earlier historical run. Windows are past, at most 31 days and 10000 quotes.

Paper entry requires an open market, a qualified observed quote meeting the
limit and sufficient top quantity. It models the requested limit conservatively,
without price improvement. Unmet entry conditions remain pending with reasons.
LONG uses the returned quote loan for modeled units; SHORT sells the returned
base loan. Fees remain in their own currencies, including base liabilities on
SHORT. Opening costs are recognized once; extensions accrue at returned period
boundaries and stop after a modeled close.

Stop, target, liquidation, expiry and timed exits use observed bid/ask sides.
Closures, invalid quotes and insufficient depth cannot manufacture a close.
Missing quotes after expiry leave a pending close; adverse gaps can leave debt.
Unqualified/stale marks have no invented equity estimate. The report retains
events, nonfills, fees, balances, debts, coverage and the source-data digest.

These are **paper accounting assumptions**: initial preview thresholds remain
fixed; trigger prices proxy venue marks; exact margin quantity precision,
funding repricing, account eligibility, close-fee currency, real fill/settlement
and liquidation behavior during closure are not qualified. Opening/extension
cost recognition is not a claim about actual collateral debit timing. The public
adapter cannot submit a position. Native funded execution remains disabled.

Validation receipts: `.pi/margin-qualification.json` records actual CLI catalogue
and LONG/SHORT previews; tests cover grid/collateral rejection, currency-aware
fees, close/debt behavior, receipt integrity, GUI input invalidation, exact money,
token enforcement, supervisor dispatch, DEMO isolation and pinned networking.
