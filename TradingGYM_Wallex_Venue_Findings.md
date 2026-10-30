# TradingGYM: Wallex venue findings (interim)

*30 October 2026 | The venue moves from Abantether to Wallex. Sources are the operator-supplied documentation: the text export with three embedded Swagger files (basic services, spot, margin), seven saved documentation pages, and twelve screenshots. Later batches added margin, trade credit, instant trade and the full WebSocket section (Sections 8–11). The documentation contains no REST order-status, error-code or rate-limit pages; those become probe questions.*

## 1. What changes fundamentally

| Topic | Abantether (Revision 5) | Wallex (documented) | Consequence |
| --- | --- | --- | --- |
| Market model | OTC dealer: one buy and one sell quote per pair, uniform markup | **Order book** (spot) plus a separate instant-trade (OTC) product, margin and trade credit | `VenueProfile.market_model = ORDER_BOOK`. Execution can be maker or taker; spread is now a measured book property, not a dealer markup. |
| Market data | Quotes only; no trades; no history | Depth (`/v1/depth`, `/depth/all`), recent trades with side (`/v1/trades`), **historical OHLCV candles** (`/v1/udf/history`), market list with precision and flags | Research can start from venue history instead of waiting for self-collection. LAST/trade bars become valid. Book-based cost models (walk the book) replace the flat markup. |
| Fees | Published flat fee; coefficient in coin-info | **Per-market maker and taker rates** and recent volume per account (`/v1/account/fee`; example 0.2%/0.2%); `is_zero_fee` flag per market; fills report fee, fee asset and maker/taker coefficients | `FeeSchedule` per market and liquidity role; actual fee read from each fill. |
| Order identity | Optional `track_id`, cancel by venue ID only | **`client_id` must be unique, or the order is not registered**; detail and cancel **by client ID** (`GET`/`DELETE /v1/account/orders/{client_id}`) | Lost-acknowledgment recovery becomes direct: query by our own ID. `SAME_ID_RESUBMIT` is plausibly certifiable, but needs probe evidence (Section 6). |
| Order types | Market, limit, venue stop-loss price | `LIMIT`, `MARKET`, `STOP_LIMIT`, `STOP_MARKET` (`stop_Price`) | Venue-side stops exist natively: a candidate protective-exit method that keeps working when the PC is off, after certification. |
| Market-order guard | None documented | A market order is **cancelled automatically** if it exceeds book depth or would move price more than **2%** from the last trade | A protective market sell can fail in a thin book. Exit Guard needs a limit-based fallback and must treat this cancellation as a normal outcome. |
| Rate limit | Unknown | Order placement: **at most 20 requests per 10 seconds**; repeated depth/trade polling may be rate-limited (use WebSocket) | Request scheduler budget is known; the Collector uses WebSocket once documented. |
| API key | Static, never expires, can withdraw, can log in | **Scoped permissions**: read, trade, withdraw. Withdraw permission requires an **IP allowlist**. Keys expire (screenshot shows up to **90 days**). **At most three keys.** Trade-credit sub-accounts need their own key plus a `sub-account-client-id` header. Header is `x-api-key`. | Major security improvement: the Executor's key is **read + trade only**, never withdraw. Expiry needs a rotation reminder and a graceful "key expired" state. One key slot for the Executor, one for read-only research; keep one free. |
| Account structure | Spot, credit, collateral, investment wallets via `account_type` | Main account, plus trade-credit sub-accounts selected **by key and header**; margin is a separate API (`/margin-trade/v1/...`) | Spot-only pinning becomes structural: the Executor holds the main-account trade key and never sends `sub-account-client-id`. |
| Toman movement | Not in API | **Toman withdrawal to IBAN** (`POST /v1/account/money-withdrawal`, needs withdraw permission), IBAN add/list, card list, crypto deposit addresses | All absent from the Executor allowlist (`SEC-03` carries over). |

## 2. Endpoint inventory (as documented)

| Area | Method and path | Auth | TradingGYM use |
| --- | --- | --- | --- |
| Markets | `GET /hector/web/v1/markets` | Swagger disagrees: required in one file, public in the other | Instrument catalog: `is_spot`, `is_otc`, `is_margin`, `is_tmn_based`, `is_usdt_based`, `is_zero_fee`, precision, flags |
| Depth | `GET /v1/depth?symbol=`; `GET /depth/all` | Key (one file) / public (other) | Book snapshots; cost model |
| Trades | `GET /v1/trades?symbol=` | Key | Trade tape, side, timestamp |
| Candles | `GET /v1/udf/history?symbol&resolution&from&to` | Key | Historical OHLCV. Resolutions 1, 15, 60, 240, 480, 720, 1D, 2D, 3D per the page; 1, 5, 15, 60, D per Swagger |
| Balances | `GET /v1/account/balances` | Key | `value` and `locked` per asset; flags `is_dust`, `is_digital_gold` |
| Fees | `GET /v1/account/fee` | Key | Maker/taker rate per market; `recent_days_sum` volume |
| Spot orders | `POST /v1/account/orders`; `GET /v1/account/orders` (filters: market, type, side, date range by day, paging up to 100); `GET /v1/account/openOrders`; `GET` and `DELETE /v1/account/orders/{client_id}`; `DELETE /v1/account/orders` (body `clientOrderId`) | Key | The only Executor write paths |
| Margin | `/margin-trade/v1/` positions (open, close, collateral, SL/TP, profit), orders, public markets, dry-run, loan calculator, long/short ratio, user levels, PnL | Key (public for markets, dry-run, ratio) | Research and read-only exposure only; never in the Executor |
| Money | IBAN add/list, card list, toman withdrawal, crypto wallet address | Key (withdraw permission for withdrawal) | Never in the Executor |

## 3. Facts that answer old open questions

- **Timestamps:** the introduction says ISO-8601 datetimes and Unix-second timestamps. The examples use `Z` (UTC): trades `2025-06-09T13:40:05Z`, withdrawal `2025-10-27T07:24:21Z`. Order `transactTime` is an integer.
- **Numbers** arrive as decimal strings with up to 16 fractional digits (for example `"7209722048.0000000000000000"`), so parsing must be decimal, never float.
- **Fills** carry price, quantity, fee, fee asset, fee coefficient and maker/taker flags. Fee posting can follow the venue's actual numbers per fill.
- **Margin terms** (from the documentation pages):
  - positions live at most **21 days**;
  - an opening fee is taken from collateral at close;
  - an extension fee accrues **every 4 hours**;
  - positions close on expiry, liquidation, manual close, or SL/TP;
  - per-market `min_risk_coef`, `max_risk_coef`, `risk_coef_step`, `liquidity_margin` and `max_age`.

## 4. Inconsistencies in the documentation (fixtures and probes must settle them)

1. **Host:** the introduction and the margin Swagger say `api.wallex.ir`; the basic and spot Swaggers and the code samples say `api.wallex.com`.
2. **Auth on market data** differs between the two Swagger files (markets, depth).
3. **`/v1/trades` `symbol`:** required in Swagger, optional in the page table.
4. **Candle parameters:** all required in Swagger, optional on the page; the resolution lists differ.
5. **Cancel:** two forms exist (path `client_id`, or body `clientOrderId`); the sub-account variant uses `client_order_id`.
6. **Order-list responses** are keyed objects (`additionalProp1…`) in the examples, while the schema names an array. The real shape must come from a fixture.
7. **`stop_Price`** is mixed-case in the request and `stopPrice` in responses.
8. **Order-list date filters** are day-granular (`YYYY-MM-DD`). They are too coarse for recovery windows, so recovery uses `GET /orders/{client_id}` and `openOrders`.

## 5. Market-specific notice seen in the app

The UNGON notice is a tokenized natural-gas ETF. Its price discovery follows global gas prices and the fund's value, with **Wallex's internal market makers** keeping the price aligned; it may diverge at times. Deposit and withdrawal of the coin are temporarily unavailable.

**Consequences:**
- tokenized assets need a `TOKENIZED_FUND` kind with a reference-price source;
- a "venue market maker present" flag;
- per-asset deposit/withdrawal availability as a `ProductAvailability` rule.

The Revision 5 rule engine already models this.

## 6. What carries over unchanged from Revision 5

The architecture carries over, because it was built venue-neutral:
- the restricted Executor and authority tiers;
- three-axis order state;
- durable intent before POST;
- rules as versioned data in three classes;
- pair-scoped regime rules (Wallex announced the same USDT/TMN night closure and 2,000 USDT cap in October 2026, and first announced automatic cancellation of open USDT/TMN orders at 21:00, then kept them through the closure and paused liquidations during it; sources are Iran Broker items 349928 and 350375, already in Appendix E as X20);
- external exposure;
- workstreams;
- the economic report.

Most Abantether-specific text changes:
- Sections 2.1-2.3, 2.9, 4.1, 6.3 and 17;
- Appendix A.1;
- several acceptance tests.

## 7. Plan once the remaining documentation arrives

1. Rewrite Section 2 for Wallex: interface table, order-book economics (taker cost = half-spread + depth impact + taker fee; maker option), regime, product surface (spot, instant trade, margin, trade credit).
2. Change the market model to order book throughout:
   - bid/ask/trade bars;
   - book-walk simulator with partial fills;
   - maker/taker cost model.
3. Change identity and recovery to the venue's mandatory unique `client_id`, with a probe plan for duplicate-ID behavior, the consistency window and the 2% market-order guard.
4. Change the Executor allowlist to: balances, fee, markets, depth, order create/detail/cancel/list/open.
5. Change keys:
   - one read-only key for the Collector;
   - one read+trade key for the Executor;
   - expiry handling and a T2 rotation flow;
   - withdraw permission never granted.
6. Replace the venue questions with a Wallex list:
   - order status enum and terminal states;
   - duplicate `client_id` error;
   - partial fills and cancel races;
   - stop-order trigger source;
   - key expiry behavior;
   - WebSocket channels and sequence numbers;
   - instant-trade quote semantics and fees.

## 8. Margin (معامله تعهدی) in detail (pages added later)

| Step | Endpoint | Inputs | What it returns or does |
| --- | --- | --- | --- |
| Active markets | `GET /margin-trade/v1/public/markets` (public) | none | `base`, `quote`, `min_risk_coef`, `max_risk_coef`, `risk_coef_step`, `liquidity_margin` (remaining % before liquidation), `max_age` |
| Collateral range | `POST /margin-trade/v1/public/loan` (key required in the Swagger file despite the `public` path) | `market`, `risk_coef`, `side` (`long`/`short`) required; `collateral`, `open_price` optional | Minimum and maximum collateral; loan value and currency |
| Preview | `POST /margin-trade/v1/public/dry-run` (public) | `collateral`, `market`, `open_price`, `risk_coef`, `side` required; `stop_loss`, `take_profit` optional | `call_price` (warning level), `liquidity_price`, loan, opening fee, trading fee, extension fee per `extend_time`, `max_age` |
| Open | `POST /margin-trade/v1/positions` | same as preview | Position: `id`, `state`, `first_order_filled`, `is_called`, `call_price`, `liquidity_price`, `expires_at`, `interest`, `profit`, `open_filled_price` |
| Add collateral | `PATCH /margin-trade/v1/positions/{id}/collateral` | `change` | Updated position |
| Edit SL/TP | `PATCH /margin-trade/v1/positions/{id}/sltp` | `stop_loss`, `take_profit` (both optional) | Updated position |
| Close | `PATCH /margin-trade/v1/positions/{id}/close` | `price` (**required**: closing is at a stated price) | Position with `close_price`, `close_filled_price`, `close_reason` |
| Read | `GET .../positions`, `GET .../positions/{id}`, `GET .../orders` (filters: active, market, side, position side/ID/type), `GET .../user/levels[/{market}]` (per-level max loan and position volume, max risk coefficient), `GET .../user/pnl`, `POST .../positions/{id}/profit` (what-if close) | | Read-only exposure and analysis |

**What matters for TradingGYM:**

1. **Opening a margin position has no client ID.** The request schema has no idempotency field. After a lost response, the only recovery is listing positions and matching market, side, collateral and time. Funded margin automation would therefore be weaker on duplicate protection than spot, which supports keeping it out of scope (open decision O9).
2. **Read-only exposure is fully visible.** Positions expose `call_price` (the warning level), `liquidity_price`, `expires_at` and `interest`. `ExternalExposure` can show distance to warning and to liquidation, and time to expiry, automatically. This is better than Abantether, where these had to be entered by hand.
3. **The preview needs no key** (the loan calculator does, per the Swagger file). Research `SCENARIO`s can be checked against the venue's own fee and liquidation arithmetic without any account access.
4. **Costs:** an opening fee, a trading fee and an extension fee every 4 hours, all charged to collateral at close. The maximum position life is 21 days.
5. **Documentation slip:** the page for spot `GET /v1/account/orders` is titled "List margin orders" in the spot section; the real margin list is `/margin-trade/v1/orders`.
6. **Still unknown:**
   - the values of `state` and `close_reason`;
   - what happens to a margin position during a pair closure, given the venue's announcement that liquidation pauses during the USDT/TMN night closure (Section 6);
   - whether `close` with a price behaves as a limit order that can stay unfilled.

Margin is now covered. Sections 9–11 cover trade credit, instant trade and the WebSocket pages supplied so far.

## 9. Trade credit (اعتبار معاملاتی) in detail

Sources: the trade-credit Swagger (`trade-credit.yaml`, 16 operations, `x-api-key`) and the operator-supplied prose and generated pages.

**What it is.** Each activated package creates a separate sub-account with its own wallet, its own order history and, per the intro page, its own API key. The sub-account holds your collateral (دارایی ورودی) plus Wallex's credit. You trade it on spot, instant trade and convert. Liquidation is **account-level**: when the package's total value falls to `liquidity_limit`, Wallex closes the whole package. This is not per position.

**Economics of the one real-looking example** (package 147, "600 میلیون اعتبار معاملاتی"):

| Item | Value |
|---|---|
| Collateral / credit / start value | 60 M / 600 M / 660 M TMN |
| Effective leverage on collateral | 11× |
| Warning level | 642 M (97.3 % of start; a loss of 30 % of collateral) |
| Liquidation level | 624 M (94.5 % of start; a loss of 60 % of collateral) |
| Daily fee | 600 k TMN/day (0.091 % of capital/day) |
| Full 30-day fee | 18 M TMN (30 % of collateral; 3 % of the credit) |

The fee is charged per elapsed day whether or not you trade. It is a fixed daily hurdle the strategy must beat, and it must be part of the cost model whenever a package is open. Packages run 30 days, close automatically and can be renewed only in the last 5 days.

**Endpoints**

| Purpose | Call | Notes for TradingGYM |
|---|---|---|
| Package catalogue | `GET /v1/prop/packages`, `GET /v1/prop/packages/{id}` | The detail call returns `unavailableMarkets` (e.g. `WTMN`, `METMN`, `WUSDT`). These feed ProductAvailability per sub-account. |
| Eligibility | `GET /v1/prop/user/packages/{id}/check-availability` | KYC level and balance checks. |
| Activate | `POST /v1/prop/user/packages` with `prop_package_id` | Creates the sub-account and commits collateral and fees. No client idempotency key; the response carries the server's `clientId`. |
| Live state | `GET /v1/prop/user/packages/active` (sub-account header) | Returns `status`, `warningLimit`, `liquidityLimit`, `profit`, fee totals, `finalPayback`, `alertsData` (e.g. `public_warning_low_credit`) and daily balance history. Distance to warning and to liquidation can be computed automatically. |
| Overview / history | `.../overview`, `.../history`, `.../history/{subAccountClientId}` | Close records carry `close_reason`, `final_balance`, `final_payBack` and `profit`. |
| Sub-account balances | `GET /v1/account/balances-detail` (sub-account header) | |
| Fund the package | `POST /sub-accounts/transfers` (`currency`, `value`, `subAccount_client_id`) | Master → sub only. A 422 example rejects BTC. **No sub → master transfer exists**, so money stays inside until the package closes. |
| Auto top-up | `POST/DELETE /v1/prop/user/packages/connect-to-wallet` (`credit`, `currency`, `usageCount`) | When value falls below the warning level, Wallex moves money from the main wallet automatically, up to `credit × usageCount`. |
| Renew / close | `POST .../enable-renew`, `DELETE /v1/prop/user/packages` | Close returns `start_balance`, `final_balance` and `final_balance_without_transfers`. |

**Implications for the design**

1. **Spot trading inside a package uses the ordinary spot API**, including `client_id`, so the existing order engine and its recovery rules apply. That makes trade credit a better fit than margin, whose open call has no client ID (Section 8). It remains to be confirmed whether trading uses the sub-account's own key or the master key plus the sub-account header (Question TC-1).
2. **Treat the package as a venue-owned liquidation boundary.** The Executor must assume that Wallex can close every position in the sub-account at any time. It has to poll the active endpoint, record `warningLimit`/`liquidityLimit`, and reconcile after a forced close as an external event, never as its own fill.
3. **Auto top-up breaks the loss cap.** With connect-to-wallet on, losses can exceed the collateral by up to `credit × usageCount`, paid from the main wallet with no Executor action. Recommendation: keep `connect-to-wallet` off the Executor allowlist. If the operator turns it on in the web app, observe it read-only and add the maximum top-up to exposure.
4. **Commitment-creating calls stay out of autonomous authority.** Activate, renew, connect-to-wallet and transfer commit money or fees. They belong to the operator, as T2 actions behind explicit confirmation, or in the web app. `DELETE` (close package) is a candidate for the flatten/kill path, but only after Question TC-3 is answered.
5. **Separate ledgers.** Each sub-account is a separate book with its own balances and history. Attribution must keep the package's fees, the funding transfers and trading P&L apart, using `final_balance_without_transfers` to separate them.

**Documentation inconsistencies (fixtures and probes must settle them)**

- The sub-account header is spelled three ways: `sub-account-client-id` (Swagger), `Sub-Account-Client-id` (generated pages) and `sub_account_client_id` (prose). Header names with underscores are dropped by some proxies, so use the hyphenated form and verify it with a read-only probe.
- `prop_package_id` is a String in the prose and a number in the Swagger. The transfer `value` is a number on the generated page and a string in the Swagger.
- The "Activate User Package" page describes itself as retrieving transfer details (copy slip). Its success code is 201 in the Swagger.
- Status values mix case: packages are `ACTIVE`/`INACTIVE`, and user packages are `active`, `liquid` and `SUSPEND`. No full list is given.
- Two examples are internally impossible. Package 81 has a warning level of 250 M above a start value of 220 M. A history record has a warning level of 1001 below a liquidation level of 1081. The examples come from staging (`phinix-public-staging` image URLs) and must not be used as test values.
- Rate-limit headers appear on responses, with `x-ratelimit-limit` example `600`, but the window is not stated.

**Questions for Wallex or a probe**

- TC-1: Does spot trading in a package use the sub-account's own API key or the master key plus the header? Can the sub-account key be scoped (read/trade) like the master key?
- TC-2: Is the liquidation value measured in the package currency at which price (last, fair or bid)? How does it behave during the USDT/TMN night closure?
- TC-3: Does closing a package require flat positions, or does Wallex sell holdings itself, and at what price?
- TC-4: What are all values of `status`, `close_reason` and `alertsData.type`?

## 10. Instant trade (معامله آنی / OTC) in detail

Source: the OTC Swagger (Swagger 2.0, three operations, `x-api-key`; its title reads "Spot") and the operator-supplied pages.

| Call | Purpose | Notes |
|---|---|---|
| `GET /v1/otc/markets` | Market list | Per market: `minQty`, `minNotional`, `maxNotional`, precision, and `buyStatus`/`sellStatus`/`exchangeStatus` (ENABLE/DISABLE). USDTTMN example: minimum notional 90,000 TMN, maximum 50 M TMN. |
| `GET /v1/account/otc/price?symbol&side` | Quote | Returns `price`, `price_expires_at` and `ttl` (17 s in the example). Under `/account`, so it needs a key. |
| `POST /v1/account/easy-trade/orders` | Execute | Body `symbol`, `side`, `quantity`, `from: "otc"`. Returns a filled order with `fills`. |

**What matters for TradingGYM**

1. **No idempotency.** `clientOrderId` is generated by the server (`OTC-<uuid>`), and the request has no field of ours. A lost response is MAYBE_SENT with no way to look it up by our own ID. Recovery has to match by symbol, side, quantity and time, as for margin.
2. **The quote is not binding.** The order does not reference the quote and has no price limit, so execution can differ from the price just fetched. The envelope check must compare `executedPrice` with the quote after the fact. Breaches are recorded as slippage incidents.
3. **The cost is inside the price.** The example fill shows a zero fee (`fee: 0`, coefficients 0). The spread is therefore embedded in the quoted price and must be measured against the order book's mid or fair price to be costed.
4. **Fit.** OTC is a fill-or-nothing taker product with venue-set price and per-order notional caps. It suits occasional conversion, not the strategy order path. Recommendation: allow it only as an operator-assisted conversion, never as an autonomous order route, until a probe measures its spread against the book.
5. **Open questions:** whether OTC stays open during the USDT/TMN night closure; whether a partially filled or rejected status exists (`executedPercent` suggests partials); and what errors look like.

## 11. WebSocket in detail

Source: all twelve operator-supplied WebSocket pages.

**Two versions.** Version 1 (`wss://api.wallex.ir/ws`) is deprecated but still works. Version 2 (`wss://api.wallex.ir/connection/websocket`, no trailing slash, otherwise 404) runs on Centrifugo and is the one to build on. Official Centrifugo SDKs exist for JS, Python, Go, Java, Swift and Dart.

**Channels (v2)**

| Channel | Login | Content |
|---|---|---|
| `public:<SYMBOL>@trade` | No | One trade per message: `isBuyOrder`, `quantity`, `price` (decimal strings), `timestamp`. `isBuyOrder: true` means the **resting (maker) order was the buy**, so the aggressor sold. |
| `orderbook:<SYMBOL>@buyDepth` / `@sellDepth` | No | **Each message is a full snapshot** of that side (replace, do not merge): `quantity`, `price`, `sum`, sent as JSON **numbers**, not strings |
| `public:all@price` | No | Price changes for all markets |
| `public:all@fairPrice` | No | Full snapshot of fair prices every 20 s (sometimes about 35 s); 46–50 KB per message; fair price = (bid + ask) / 2; identical to `GET /v1/all-fairPrice` |
| `candle:<SYMBOL>@1m` / `@1h` / `@1d` | No | Full (not delta) image of the open candle in UDF OHLCV form; the only channels with an `offset` and history (last 10 messages, up to 2 minutes) |
| `private:user#<userId>` | Yes (JWT) | Four events: `balanceUpdated` (`value`, `locked` per asset), `orderSaved` and `orderRemoved` (`clientOrderId`, `status` such as `NEW`/`CANCELED`, `active`, `origQty`, `executedQty`), `tradeDetails` (`clientOrderID`, price, quantity, `feeAmount`, `feeCurrency`, `isMaker`). Server subscribes you from the token's `channels` claim. |

**Protocol facts**

- The first command is `connect`. A public connection needs no token. The server pings every 25 s with `{}`; the client must answer within 8 s or the connection closes with code 3012.
- Limit: 64 channels per connection, the private one included (error 106).
- Close codes 3000–3499 mean reconnect. Codes 3500 and above mean a client-side fault where retrying is useless (3500 invalid token, 3501 bad frame). Code 3005 means the token expired, and 3008 means the client is consuming too slowly.
- Command errors: 102 unknown channel, 103 permission denied, 105 already subscribed, 106 limit exceeded, 107 bad request, 108 not available, 109 token expired.
- A misspelling before `@` (e.g. `alll@fairPrice`) subscribes successfully and then never delivers. Treat 60 s of silence as a fault, not as unchanged prices.
- Timestamps in `fairPrice` omit zero fractions, so compare them as parsed instants, never as strings.

**Implications for the design**

1. **Depth is simple; trades are lossy.** Depth messages are full snapshots, so one message fully restores a side. A quiet market sends nothing, though, and subscribing returns nothing, so the book needs a REST snapshot at start and after every reconnect, plus a staleness timer that marks it STALE and blocks new entries. Depth values arrive as JSON numbers: parse them straight into decimals from the raw text, never through floats. The trade tape has no sequence numbers or replay, so trades missed during a disconnect are gone; fill the gap from `GET /v1/trades`, which only returns recent trades.
2. **Candles are recoverable only for short gaps.** After a reconnect, refetch `GET /v1/udf/history` and upsert candles by `t`. The 10-message, 2-minute history only covers the hand-over.
3. **The fair price is a usable reference mark.** It is the venue's own number, available by REST and socket, and suits mark-to-market and the OTC spread check. It can omit a symbol in any given snapshot, so a missing key means "no price now", not "market removed".
4. **The private channel needs the website login, not the API key.** The token page states it plainly: `POST /v3/auth/token/refresh` authenticates with the **user's login cookie**, and a bot outside a browser must build the `Cookie` header itself. Tokens last `expires_in` seconds (900 in the example) and must be refreshed before expiry (error 109, close code 3005). Version 1 uses a `stream_key` returned by the login API. Either way the credential is a full web session, which can do everything the website can, including withdrawals. **Decision: the Executor never holds a web session.** Fills and order state come from REST (order detail by `client_id`, open orders, balances), polled on a schedule the rate limit allows. If private events are wanted later, they belong in a separate, optional read-only process that the operator logs into, never on the key-holding host, and their events are hints that trigger a REST check, never ledger entries.
5. **Use one connection per concern and stay under the channel cap**, and unsubscribe when leaving a market.
6. **New facts for the order model:** statuses `NEW` and `CANCELED` are confirmed by the private-event examples; `tradeDetails` reports `isMaker` and the fee per fill; and the example `clientOrderId` values (`LIMIT-xxxx`, `LIMIT-<uuid>`) suggest that Wallex prefixes or generates IDs when the client sends none. A probe must confirm that an ID we send comes back unchanged.

**Not in the documentation at all (probe or ask Wallex):** the full REST order-status list (only `ACCEPTED`, `PENDING`, `NEW`, `CANCELED` appear in examples), REST error codes and bodies, and REST rate-limit windows. The generated REST pages list only HTTP codes (400, 401, 404, 422, and 408/500 for margin orders) without bodies.

## 12. Spot order types (from the spot-terms page)

The spot-terms page (اصطلاحات معامله اسپات) defines the four order types. It contains **no order-status list**.

- **LIMIT:** rests in the order book at the stated price.
- **MARKET:** fills at the best available prices, possibly in several parts at different prices. It is cancelled automatically if it exceeds book depth or would move the price more than 2% from the last trade (this confirms Section 1).
- **STOP_LIMIT / STOP_MARKET:** the order stays out of the book until the trigger fires.
  - The trigger is the **last traded price**, not bid, ask or fair price.
  - The direction is fixed when the order is created:
    - a stop below the last trade fires when the last trade is less than or equal to the stop;
    - a stop above the last trade fires when the last trade is greater than or equal to the stop.
  - After triggering, STOP_LIMIT behaves as a LIMIT order and STOP_MARKET as a MARKET order.

**Implications for the design**

1. **A venue STOP_MARKET is not a guaranteed exit.** Once triggered, it is a market order, so in a gap or a thin book the same 2% / depth guard can cancel it. A protective stop can therefore end up cancelled while the position is still open. Exit Guard must:
   - treat "stop triggered then cancelled" as a live, unprotected position;
   - re-check after every trigger;
   - fall back to a STOP_LIMIT with a deliberate limit offset, or to an Executor-managed limit ladder.
2. **The trigger fires on last-trade prints**, so a single small trade can fire a stop in an illiquid market. The book-walk simulator must trigger stops on the trade tape, not on mid or fair price, so that backtests match the venue.
3. **Direction is inferred at creation.** If the last price moves past the stop between our decision and the venue receiving the order, the venue reads the direction the other way. The stop then waits for a move back across the level instead of firing at once. Before sending, the Executor must check the stop's side against the latest trade price and refuse the order if it is already on the wrong side.
4. **The order-status list remains undocumented** (examples show `ACCEPTED`, `PENDING`, `NEW`, `CANCELED`). It stays a probe item, together with the statuses of a stop that is waiting, triggered, or triggered and then cancelled.
