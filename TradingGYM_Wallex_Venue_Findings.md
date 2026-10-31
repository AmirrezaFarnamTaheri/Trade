# TradingGYM: Wallex venue findings

*31 October 2026 | The venue moves from Abantether to Wallex. TradingGYM fetched and reviewed all **114 `/docs` pages listed in the official `developers.wallex.ir` sitemap**, covering introduction and API keys, basic services, generated REST references, spot, margin, trade credit, instant trade and twelve WebSocket pages. Internal inconsistencies are retained below as fixture or probe questions rather than silently resolved.*

## 1. What changes fundamentally

| Topic | Abantether (Revision 5) | Wallex (documented) | Consequence |
| --- | --- | --- | --- |
| Market model | OTC dealer: one buy and one sell quote per pair, uniform markup | **Order book** (spot) plus a separate instant-trade (OTC) product, margin and trade credit | `VenueProfile.market_model = ORDER_BOOK`. Execution can be maker or taker; spread is now a measured book property, not a dealer markup. |
| Market data | Quotes only; no trades; no history | Public/no-key depth (`/v1/depth`, `/depth/all`), recent trades with side (`/v1/trades`), **historical OHLCV candles** (`/v1/udf/history`), fair prices (`/v1/all-fairPrice`), market list with precision and flags, and public v2 WebSocket channels | Research can start from venue history instead of waiting for self-collection. LAST/trade bars become valid. Book-based cost models (walk the book) replace the flat markup. |
| Fees | Published flat fee; coefficient in coin-info | **Per-market maker and taker rates** and recent volume per account (`/v1/account/fee`; example 0.2%/0.2%); `is_zero_fee` flag per market; fills report fee, fee asset and maker/taker coefficients | `FeeSchedule` per market and liquidity role; actual fee read from each fill. |
| Order identity | Optional `track_id`, cancel by venue ID only | `client_id` is optional; if omitted Wallex generates `clientOrderId`, while a supplied ID must be unique or the order is not registered. Detail and cancel work **by client ID** (`GET`/`DELETE /v1/account/orders/{client_id}`). | TradingGYM still generates, stores and sends its own ID before POST, so lost-acknowledgment recovery can query it directly. `SAME_ID_RESUBMIT` still needs duplicate-ID probe evidence (Section 6). |
| Order types | Market, limit, venue stop-loss price | `LIMIT`, `MARKET`, `STOP_LIMIT`, `STOP_MARKET` (`stop_Price`) | Venue-side stops exist natively: a candidate protective-exit method that keeps working when the PC is off, after certification. |
| Market-order guard | None documented | A market order is **cancelled automatically** if it exceeds book depth or would move price more than **2%** from the last trade | A protective market sell can fail in a thin book. Exit Guard needs a limit-based fallback and must treat this cancellation as a normal outcome. |
| Rate limit | Unknown | Order placement: **at most 20 requests per 10 seconds**; repeated depth/trade polling may be rate-limited (use WebSocket) | Request scheduler budget is known; the Collector uses the documented public v2 WebSocket plus REST reseeding. |
| API key | Static, never expires, can withdraw, can log in | **Scoped permissions**: read by default, optional trade, optional withdraw. Withdraw requires the configured **IP** to match. A key is shown once and expires at the operator-selected date. Wallex documents **at most three keys** and says the main and each trade-credit account need their own key; the cap's scope across accounts is unclear. Header is `x-api-key`. | The Executor uses **read + trade only**, never withdraw. Public collection needs no key. Expiry needs a rotation reminder and graceful failure; an optional relay consumes a separate trade-key slot. |
| Account structure | Spot, credit, collateral, investment wallets via `account_type` | Main account, plus trade-credit sub-accounts selected **by key and header**; margin is a separate API (`/margin-trade/v1/...`) | Spot-only pinning becomes structural: the Executor holds the main-account trade key and never sends `sub-account-client-id`. |
| Toman movement | Not in API | **Toman withdrawal to IBAN** (`POST /v1/account/money-withdrawal`, needs withdraw permission), IBAN add/list, card list, crypto deposit addresses | All absent from the Executor allowlist (`SEC-03` carries over). |

## 2. Endpoint inventory (as documented)

| Area | Method and path | Auth | TradingGYM use |
| --- | --- | --- | --- |
| Markets | `GET /hector/web/v1/markets` | Public / no key | Instrument catalog: `is_spot`, `is_otc`, `is_margin`, `is_tmn_based`, `is_usdt_based`, `is_zero_fee`, precision, flags |
| Depth | `GET /v1/depth?symbol=`; `GET /depth/all` | Public / no key | Book snapshots; cost model |
| Trades | `GET /v1/trades?symbol=` | Public / no key | Recent trade tape, side and timestamp; not a historical archive |
| Candles | `GET /v1/udf/history?symbol&resolution&from&to` | Public / no key | Historical OHLCV. Current narrative resolutions: `1`, `15`, `60`, `240`, `480`, `720`, `1D`, `2D`, `3D`; generated material remains inconsistent |
| Fair prices | `GET /v1/all-fairPrice` | Public / no key | Venue reference midpoint for all markets; reference/mark input, not executable price |
| Balances | `GET /v1/account/balances` | Key | `value` and `locked` per asset; flags `is_dust`, `is_digital_gold` |
| Fees | `GET /v1/account/fee` | Key | Maker/taker rate per market; `recent_days_sum` volume |
| Spot orders | `POST /v1/account/orders`; `GET /v1/account/orders` (filters: market, type, side, date range by day, paging up to 100); `GET /v1/account/openOrders`; `GET` and `DELETE /v1/account/orders/{client_id}`; `DELETE /v1/account/orders` (body `clientOrderId`) | Key | The only **strategy-authorized** Executor write paths; every supplied `client_id` is stored before POST |
| Instant-trade execute | `GET /v1/account/otc/price`; `POST /v1/account/easy-trade/orders` | Key | Distinct operator-started Assisted conversion only; lost acknowledgment is `MAYBE_SENT` and never auto-retried |
| Trade-credit lifecycle | Activate `POST /v1/prop/user/packages`; fund `POST /sub-accounts/transfers`; renew `POST .../enable-renew`; close `DELETE /v1/prop/user/packages` | Key + sub-account context where documented | Distinct T2-only Executor commands; never strategy-authorized |
| Margin | `/margin-trade/v1/` positions (open, close, collateral, SL/TP, profit), orders, public markets, dry-run, loan calculator, long/short ratio, user levels, PnL | Key (public for markets, dry-run, ratio) | No margin write endpoint is allowlisted; authenticated GETs may be used only for `ExternalExposure`, reconciliation and warnings, plus public research scenarios |
| Money | IBAN add/list, card list, toman withdrawal, crypto wallet address | Key (withdraw permission for withdrawal) | Never in the Executor |

## 3. Facts that answer old open questions

- **Timestamps:** schemas are endpoint/channel-specific. The introduction and REST examples use ISO-8601 UTC and Unix seconds (`2025-06-09T13:40:05Z`, `2025-10-27T07:24:21Z`, integer order `transactTime`); private WebSocket examples also use Unix milliseconds such as `1748773416376` and `1748773416414`. Preserve the raw value and parse only by the declared schema, validating the expected magnitude.
- **Transport and numbers:** JSON request bodies use `Content-Type: application/json`. Wire types are schema-specific: many money/quantity fields are decimal strings with up to 16 fractional digits, while depth fields are JSON numbers. Preserve the raw lexeme and parse directly as decimal, never through a binary float.
- **Fills** carry price, quantity, fee, fee asset, fee coefficient and maker/taker flags. Fee posting can follow the venue's actual numbers per fill.
- **Margin terms** (from the documentation pages):
  - documentation examples describe positions up to **21 days**, but executable logic uses each market's `max_age`;
  - an opening fee is taken from collateral at close;
  - examples describe four-hour extension periods, while previews expose `extend_time` and fee fields that must drive executable calculations;
  - positions close on expiry, liquidation, manual close, or SL/TP; the price-bearing close call is not proven immediate;
  - per-market `min_risk_coef`, `max_risk_coef`, `risk_coef_step`, `liquidity_margin` and `max_age`.

## 4. Inconsistencies in the documentation (fixtures and probes must settle them)

1. **Host:** the current canonical base is `https://api.wallex.ir`. Historical generated/downloaded specifications and examples still contain `api.wallex.com`; retain those only as discrepancy fixtures, never as runtime fallback.
2. **Auth on market data:** older generated material marks some calls keyed, but current public pages, public v2 WebSocket documentation and successful unauthenticated fixtures establish markets, depth, recent trades, candles and fair prices as public/no-key. Retain a no-key fixture to detect regressions.
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
- pair-scoped regime rules (Wallex announced the same USDT/TMN night closure and 2,000 USDT cap in October 2026, and first announced automatic cancellation of open USDT/TMN orders at 21:00, then kept them through the closure and paused liquidations during it; Iran Broker item 349928 is Appendix E source X19, item 350375 is X21, and X20 is item 354108);
- external exposure;
- workstreams;
- the economic report.

Most Abantether-specific text changes:
- Sections 2.1-2.3, 2.9, 4.1, 6.3 and 17;
- Appendix A.1;
- several acceptance tests.

## 7. Plan adjustments after the complete official-site review

1. **No Collector credential.** Markets, depth, recent trades, candle history, fair prices and public v2 WebSocket channels are public/no-key. Account balances, account fees, order reads and order writes remain authenticated.
2. **Always supply our own order ID.** Wallex can generate `clientOrderId` when `client_id` is omitted, but TradingGYM always stores and sends its own unique ID before POST. Probes now target casing/length, exact echo, duplicate rejection and consistency—not whether the field exists.
3. **Budget scarce keys.** Read is the default permission; trade and withdraw are optional; withdrawal requires matching IP; a key is shown once and expires at the operator-selected date. Wallex documents at most three API keys and separate keys for the main and each trade-credit account, but does not make the scope of the three-key cap clear. The Executor uses read+trade without withdraw; an optional relay needs a separate read+trade key; public collection uses none.
4. **Use v2 WebSocket within its documented limits.** Connect first, echo raw `{}` heartbeat frames within 8 seconds, stay below 64 channels, REST-seed books after connect/reconnect, and treat private events as hints requiring REST reconciliation. Only candle channels have a small replay window.
5. **Keep unresolved contract questions explicit.** Candle-history range/depth, REST throttle windows and error bodies, the complete order-state enum, MARKET `price` request behavior, client-ID limits/echo/duplicate errors, trade-credit header/key/cap semantics, and margin/OTC recovery behavior still require fixtures, read-only probes or tightly budgeted live probes.
6. **Separate catalog, observation and execution eligibility.** Persist the complete catalog point-in-time. Observe 50 base assets by default (operator range 25–500), ranking active `is_spot` markets without `isRisky` after normalizing TMN volume through USDTTMN, and include both quote legs where listed. Custom add/remove overlays change observation only; they never grant funded eligibility. Shard at 21 markets per WebSocket, begin public REST at 4 requests/s, honor `429 Retry-After` and rotate reseeds/candle checks. The 31 October 2026 live catalog contained 469 markets, 373 active spot, 277 active spot with positive volume and 153 safely rankable base assets; these are dated observations, not limits.

## 8. Margin (معامله تعهدی) in detail

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

1. **Opening a margin position has no client ID.** The request schema has no idempotency field. After a lost response, the only recovery is listing positions and matching market, side, collateral and time. Funded margin automation would therefore be weaker on duplicate protection than spot, supporting the normative read-only scope in Decision D18 and Section 2.9.
2. **Read-only exposure is fully visible.** Positions expose `call_price` (the warning level), `liquidity_price`, `expires_at` and `interest`. `ExternalExposure` can show distance to warning and to liquidation, and time to expiry, automatically. This is better than Abantether, where these had to be entered by hand.
3. **The preview needs no key** (the loan calculator does, per the Swagger file). Research `SCENARIO`s can be checked against the venue's own fee and liquidation arithmetic without any account access.
4. **Costs and lifetime:** prose/examples describe an opening fee, trading fee, four-hour extension periods and up to 21 days, but the adapter uses current per-market `max_age` and preview `extend_time`/fee fields rather than hard-coded example values.
5. **Documentation slip:** the page for spot `GET /v1/account/orders` is titled "List margin orders" in the spot section; the real margin list is `/margin-trade/v1/orders`.
6. **Still unknown:**
   - the complete values and transitions of `state` and `close_reason`; preserve raw case and map unknown values to `UNKNOWN`;
   - what happens to a margin position during a pair closure, given the venue's announcement that liquidation pauses during the USDT/TMN night closure (Section 6);
   - whether the price-bearing `close` behaves as a limit order that can stay unfilled; never assume immediate close.

Sections 9–11 cover trade credit, instant trade and WebSocket from the same complete official-site audit.

## 9. Trade credit (اعتبار معاملاتی) in detail

Sources: the official trade-credit prose, generated references and downloadable specification (`trade-credit.yaml`, 16 operations, `x-api-key`).

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

The prose and worked example describe a daily fee, a 30-day package and renewal in the last 5 days. Treat those as product/example descriptions: executable logic uses each package's `expire_days`, lifecycle and returned daily/final fee fields, then reconciles the actual assessment and debit timing from live records.

**Endpoints**

| Purpose | Call | Notes for TradingGYM |
|---|---|---|
| Package catalogue | `GET /v1/prop/packages`, `GET /v1/prop/packages/{id}` | The detail call returns `unavailableMarkets` (e.g. `WTMN`, `METMN`, `WUSDT`). These feed ProductAvailability per sub-account. |
| Eligibility | `GET /v1/prop/user/packages/{id}/check-availability` | KYC level and balance checks. |
| Activate | `POST /v1/prop/user/packages` with `prop_package_id` | Creates the package/sub-account and commits collateral. No client idempotency key; the response carries the server's `clientId`. Reconcile exact fee assessment/debit timing from resulting records. |
| Live state | `GET /v1/prop/user/packages/active` (sub-account header) | Returns `status`, `warningLimit`, `liquidityLimit`, `profit`, fee totals, `finalPayback`, `alertsData` (e.g. `public_warning_low_credit`) and daily balance history. Distance to warning and to liquidation can be computed automatically. |
| Overview / history | `.../overview`, `.../history`, `.../history/{subAccountClientId}` | Close records carry `close_reason`, `final_balance`, `final_payBack` and `profit`. |
| Sub-account balances | `GET /v1/account/balances-detail` (sub-account header) | |
| Fund the package | `POST /sub-accounts/transfers` (`currency`, `value`, `subAccount_client_id`) | Master → sub only. A 422 example rejects BTC. **No sub → master transfer exists**, so money stays inside until the package closes. |
| Auto top-up | `POST/DELETE /v1/prop/user/packages/connect-to-wallet` (`credit`, `currency`, `usageCount`) | When value falls below the warning level, Wallex moves money from the main wallet automatically, up to `credit × usageCount`. |
| Renew / close | `POST .../enable-renew`, `DELETE /v1/prop/user/packages` | Close returns `start_balance`, `final_balance` and `final_balance_without_transfers`. |

**Implications for the design**

1. **Spot trading inside a package uses the ordinary spot API**, including `client_id`, so the existing order engine and recovery rules apply. The main and each trade-credit account use their own account-bound API key; the remaining probe is the accepted/required sub-account header spelling, key scoping and whether the three-key cap is per account or global (Question TC-1).
2. **Treat the package as a venue-owned liquidation boundary.** The Executor must assume that Wallex can close every position in the sub-account at any time. It has to poll the active endpoint, record `warningLimit`/`liquidityLimit`, and reconcile after a forced close as an external event, never as its own fill.
3. **Auto top-up breaks the loss cap.** With connect-to-wallet on, losses can exceed collateral by up to `credit × usageCount`, paid from the main wallet without an Executor action. Connect/disconnect stay outside strategy authority. If detected, add the maximum top-up to worst-case exposure and veto Autopilot entries unless an explicit policy permits the external setting.
4. **Commitment-creating calls stay out of autonomous authority.** Activate, renew, connect-to-wallet and transfer commit money or fees. They belong to the operator, as T2 actions behind explicit confirmation, or in the web app. `DELETE` (close package) is a candidate for the flatten/kill path, but only after Question TC-3 is answered.
5. **Separate ledgers.** Each sub-account is a separate book with its own balances and history. Attribution must keep the package's fees, the funding transfers and trading P&L apart, using `final_balance_without_transfers` to separate them.

**Documentation inconsistencies (fixtures and probes must settle them)**

- The sub-account header is spelled three ways: `sub-account-client-id` (Swagger), `Sub-Account-Client-id` (generated pages) and `sub_account_client_id` (prose). Header names with underscores are dropped by some proxies, so use the hyphenated form and verify it with a read-only probe.
- `prop_package_id` is a String in the prose and a number in the Swagger. The transfer `value` is a number on the generated page and a string in the Swagger.
- The "Activate User Package" page describes itself as retrieving transfer details (copy slip). Its success code is 201 in the Swagger.
- Status values mix case: packages are `ACTIVE`/`INACTIVE`, and user packages are `active`, `liquid` and `SUSPEND`. Preserve the raw case and use an unknown-safe mapping; no full list is given.
- Two examples are internally impossible. Package 81 has a warning level of 250 M above a start value of 220 M. A history record has a warning level of 1001 below a liquidation level of 1081. The examples come from staging (`phinix-public-staging` image URLs) and must not be used as test values.
- Rate-limit headers appear on responses, with `x-ratelimit-limit` example `600`, but the window is not stated.

**Questions for Wallex or a probe**

- TC-1: Which sub-account header spelling is accepted/required, can the account-bound key be scoped (read/trade) like the main key, and is the maximum of three keys per account or global?
- TC-2: Is the liquidation value measured in the package currency at which price (last, fair or bid)? How does it behave during the USDT/TMN night closure?
- TC-3: Does closing a package require flat positions, or does Wallex sell holdings itself, and at what price?
- TC-4: What are all values of `status`, `close_reason` and `alertsData.type`?

## 10. Instant trade (معامله آنی / OTC) in detail

Source: the official OTC prose, generated references and downloadable Swagger (Swagger 2.0, three operations, `x-api-key`; its title reads "Spot").

| Call | Purpose | Notes |
|---|---|---|
| `GET /v1/otc/markets` | Market list | Per market: `minQty`, `minNotional`, `maxNotional`, precision, and `buyStatus`/`sellStatus`/`exchangeStatus` (ENABLE/DISABLE). USDTTMN example: minimum notional 90,000 TMN, maximum 50 M TMN. |
| `GET /v1/account/otc/price?symbol&side` | Quote | Returns `price`, `price_expires_at` and `ttl` (17 s in the example). Under `/account`, so it needs a key. |
| `POST /v1/account/easy-trade/orders` | Execute | Body `symbol`, `side`, `quantity`, `from: "otc"`. Returns a filled order with `fills`. |

**What matters for TradingGYM**

1. **No idempotency.** `clientOrderId` is venue-generated (`OTC-<uuid>`), and the request has no field of ours. A lost acknowledgment becomes `MAYBE_SENT`; reconcile by symbol, side, quantity and time and never auto-retry.
2. **The quote is not binding.** The order does not reference the quote and has no price limit, so expiry is only a pre-submit freshness check. Compare the eventual fill with the captured quote and both fair price and book midpoint; there is no enforceable price/slippage envelope.
3. **Fees and spread are observed.** A zero-fee example is not a tariff. Reconcile actual fill fees and measure the implicit spread against fair/book references.
4. **Availability is checked immediately before approval.** Re-read `buyStatus`, `sellStatus`, `exchangeStatus`, precision and current min/max notional; an unknown or disabled value makes the route unavailable.
5. **Fit.** OTC is an immediate venue-quoted conversion whose partial-fill/rejection semantics are undocumented. It remains operator-assisted only, never an autonomous strategy route. Open questions include closure behavior, partial/rejected statuses (`executedPercent` suggests partials) and exact error bodies.

## 11. WebSocket in detail

Source: all twelve official WebSocket pages listed in the `developers.wallex.ir` sitemap.

**Two versions.** Version 1 (`wss://api.wallex.ir/ws`) is deprecated but still works. Version 2 (`wss://api.wallex.ir/connection/websocket`, no trailing slash, otherwise 404) runs on Centrifugo and is the one to build on. Official Centrifugo SDKs exist for JS, Python, Go, Java, Swift and Dart.

**Channels (v2)**

| Channel | Login | Content |
|---|---|---|
| `public:<SYMBOL>@trade` | No | One trade per message: `isBuyOrder`, `quantity`, `price` (decimal strings), `timestamp`. `isBuyOrder: true` means the **resting (maker) order was the buy**, so the aggressor sold. |
| `orderbook:<SYMBOL>@buyDepth` / `@sellDepth` | No | **Each message is a full side snapshot** (replace, do not merge): JSON-number `quantity`, `price`, and per-level quote notional `sum = price × quantity`; preserve raw lexemes |
| `public:all@price` | No | Sparse changed-market publication; `24h_ch == 0` does not prove zero return |
| `public:all@fairPrice` | No | Fair-price snapshot, observed around 20–35 s but with no cadence SLA; missing symbol means unavailable now, not delisted; identical to `GET /v1/all-fairPrice` |
| `candle:<SYMBOL>@1m` / `@1h` / `@1d` | No | Full (not delta) image of the open candle in UDF OHLCV form; the only channels with an `offset` and history (last 10 messages, up to 2 minutes) |
| `private:user#<userId>` | Yes (JWT) | Four events: `balanceUpdated` (`value`, `locked` per asset), `orderSaved` and `orderRemoved` (`clientOrderId`, `status` such as `NEW`/`CANCELED`, `active`, `origQty`, `executedQty`), `tradeDetails` (`clientOrderID`, price, quantity, `feeAmount`, `feeCurrency`, `isMaker`). Server subscribes you from the token's `channels` claim. |

**Protocol facts (v2 / Centrifugo)**

- Use `wss://api.wallex.ir/connection/websocket` with no trailing slash and no silent fallback to deprecated v1. The first command is `connect`; a subscription acknowledgement is empty and contains no initial snapshot. Publications arrive under `push.channel` and `push.pub.data`.
- SDKs manage heartbeat. A raw client echoes `{}` within 8 seconds of the 25-second ping or receives close code `3012`.
- Limit: 64 channels per connection, including private (error `106`).
- On `3005`, refresh the token and reconnect; on `3008`, fix/back off slow consumption; on `3012`, treat it as missed pong. Never retry unchanged after `3500` invalid token or `3501` malformed frame.
- Command errors: `102` unknown channel, `103` permission denied, `105` already subscribed, `106` limit exceeded, `107` bad request, `108` not available, `109` token expired.
- A misspelling before `@` (e.g. `alll@fairPrice`) can subscribe successfully and never deliver. Treat 60 s of silence as a fault, not unchanged prices. Fair-price timestamps may omit zero fractions, so compare parsed instants, never strings.

**Implications for the design**

1. **Depth is recoverable; trades are lossy.** A full side snapshot restores depth, but subscribing returns no initial state, so seed from REST at start/reconnect and use a staleness timer. Preserve JSON-number lexemes and parse directly as decimal. Trade has no replay; use the recent REST tail and record any remaining gap.
2. **Candles need an ordered hand-over.** REST UDF history → subscribe and buffer live → request channel history → apply history oldest-first → apply buffered live. `offset` is publication sequence, not candle time; insert/replace by `t`, and refetch REST after reconnect. The 10-publication/two-minute history only covers hand-over.
3. **The fair price is a reference mark, not executable price.** A missing symbol means unavailable now, not removed. Observed cadence is not an SLA.
4. **The private channel needs the website login, not the API key.** `POST https://api.wallex.ir/v3/auth/token/refresh` uses the website cookie and returns `result.ws_access_token` plus `expires_in` (900 is only the example). The JWT auto-subscribes `private:user#<userId>`; do not subscribe manually (`105`). Filter client-level publications by `ctx.channel`; reconnect without the token to log out. Never log/export cookie or JWT. The Executor never holds this session. An optional process must be outside the Executor/relay and their identities; a separate host is preferred. Events remain hints that trigger REST reconciliation, never ledger entries.
5. **Use one connection per concern and stay under the channel cap**, and unsubscribe when leaving a market.
6. **New facts for the order model:** current spot examples name `NEW`, `FILLED` and `CANCELED`; `tradeDetails` reports `isMaker` and fee per fill; private events inconsistently spell `clientOrderId`/`clientOrderID`, so fixtures must accept both without losing the raw field. A probe must still confirm that an ID we send returns unchanged.

**Still undocumented (probe or ask Wallex):** the full REST order-status enum and transitions (examples name `NEW`, `FILLED`, `CANCELED`; cancel prose uses `FINISHED`), REST error bodies, and global/read rate-limit windows. The 20 order requests/10 seconds rule and example `x-ratelimit-*` headers are documented; generated REST pages otherwise list only HTTP codes (400, 401, 404, 422, and 408/500 for margin orders) without bodies.

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
4. **The order-status enum remains undocumented.** Current spot examples name `NEW`, `FILLED` and `CANCELED`; cancel prose uses `FINISHED` as a terminal concept, and the single-order response example omits the promised status field. It stays a probe item, together with the statuses of a stop that is waiting, triggered, or triggered and then cancelled.
