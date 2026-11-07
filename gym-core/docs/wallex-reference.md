# Wallex API reference (local copy)

A self-contained record of the official Wallex API as read on **2026-11-08**, for offline work and for
checking adapter code. It summarizes; the official pages remain the authority. How this repository uses
each part is in [wallex-api.md](wallex-api.md) (adapter contracts and the cross-check table) and
[wallex-margin.md](wallex-margin.md) (margin research).

## Sources

| Source | What it covers | Read |
| --- | --- | --- |
| [developers.wallex.ir/docs](https://developers.wallex.ir/docs/) | Current reference: 120 pages (basic services, spot, margin, trading credit, instant trade, websocket) | All pages, through the sitemap |
| [api-docs.wallex.ir](https://api-docs.wallex.ir/) | Older single-page reference (socket.io-era websocket, Wallgate store API) | Whole page |

Where the two disagree, developers.wallex.ir is newer and wins. The Swagger files behind
developers.wallex.ir were hashed when read, so a later change can be detected:

| File (under `https://developers.wallex.ir/assets/files/`) | Bytes | SHA-256 |
| --- | --- | --- |
| `basic-services-0ff3bee03ca00b31f254d76fff33a631.json` | 49882 | `685c76497a84bc429b82a0079dc6c86c559a202fba711db3df764ed335928ee5` |
| `spot-b9d06896d1009adc9ebc69b9a5495e7e.json` | 22778 | `10d8667602b3f82428b7a35688174449843e6ed36c9de816050dccc3e6a69753` |
| `margin-c709e1f52cb44387a2e35ffd678c6dfa.json` | 32257 | `16c5f89381d9449456edb2e7c4b297f64139851b9795fc877add1823dd4e7ff4` |
| `trade-credit-ff5c60b5b97b77a5b2c2e4800f07729c.yaml` | 220907 | `d8141055d11f6fa63867f70d3d0449af2bf7c5d86f67eab7f0d37e73ba3395eb` |
| `otc-8e321a32f4509cbf103b3127bf7c9918.json` | 13254 | `f9347b5f61786f76ce5d5dc234381edd836b751bbb866ca54e62d4aa4f4203f1` |

The site's `robots.txt` refuses automated fetchers, so these were read through a browser at the
operator's request. The Swagger `host` fields say `api.wallex.com`; every page and example uses
`https://api.wallex.ir`, which is the origin the code pins.

## Conventions

- **Origin:** `https://api.wallex.ir`. Responses wrap data as `{"success": bool, "message": str, "result": …}`;
  errors use the same envelope with an integer `code` (Swagger `ErrorResponse`).
- **Authentication:** header `x-api-key: <key>`. Swagger marks even public reads as `ApiKeyAuth`; the
  collector reads public market data without a key, which works in practice.
- **Numbers:** prices and quantities are usually decimal strings (`"0.9944000000000000"`); depth levels in
  REST and websocket are JSON numbers; `recent_days_sum` is a double. Parse money as `Decimal`, never float.
- **Times:** ISO 8601 UTC strings (`2025-06-09T13:40:05Z`), except UDF candles and their websocket form
  (Unix seconds) and private websocket events (`timestamp` in Unix milliseconds).
- **Pagination:** `page` and `per_page` query parameters; responses add
  `result_info: {page, per_page, count, total_count}`. Limits: order history `per_page` at most 100
  (default 25); crypto withdrawals at most 20.
- **Requests:** bodies are JSON and every request carries `Content-Type: application/json`.
- **Rate limits:** two are published: order placement at most **20 requests per 10 seconds**, and crypto
  withdrawal submission 6 per minute. Others answer HTTP 429 when exceeded. The docs discourage polling REST
  depth and trades and point to the websocket instead.

## API keys

- Created on the Wallex website per account. The main account and each trading-credit sub-account need
  their own key; a key from one cannot trade the other.
- At most **three** keys per account. Each key's validity is chosen at creation, **at most 90 days**, and
  cannot be extended; plan replacement before expiry.
- Permissions: read (always on), trade, withdraw. Withdrawal through the API requires the request IP to be
  on the key's IP allowlist; an empty allowlist admits every IP for the other permissions.
- The key is shown once. Crypto withdrawal additionally needs user level 2, refuses Iranian and private IPs,
  and is blocked for 24 hours after a password or two-factor change.

## Public market data

| Method and path | Parameters | Response (inside `result` unless noted) |
| --- | --- | --- |
| `GET /hector/web/v1/markets` | none | `markets[]`: `symbol`, `base_asset`, `quote_asset`, `fa_/en_base_asset`, `fa_/en_quote_asset`, `categories[]`, `price` (string), `change_24h`, `change_7D`, `volume_24h`, `quote_volume_24h`, `is_new`, `spot_is_new`, `otc_is_new`, `is_spot`, `is_otc`, `is_margin`, `is_tmn_based`, `is_usdt_based`, `is_zero_fee`, `leverage_step`, `max_leverage`, `created_at`, `amount_precision`, `price_precision`, `flags[]` |
| `GET /v1/markets` (older reference) | none | `symbols{SYMBOL: {baseAsset, quoteAsset, baseAssetPrecision, quotePrecision, stepSize, tickSize, minQty, maxQty, minNotional, stats{bidPrice, askPrice, lastPrice, 24h_volume, 24h_quoteVolume, …}}}` |
| `GET /v1/depth` | `symbol` (required) | `ask[]`, `bid[]` of `{price: number, quantity: number, sum: string}`; no timestamp or sequence |
| `GET /depth/all` (spot Swagger; `/v2/depth/all` in the older reference) | none | `result{SYMBOL: {ask[], bid[]}}` |
| `GET /v1/trades` | `symbol` (required) | `latestTrades[]`: `symbol`, `quantity`, `price`, `sum` (strings), `isBuyOrder` (bool), `timestamp`; no trade ID |
| `GET /v1/udf/history` | `symbol`, `resolution`, `from`, `to` (Unix seconds). The candles page lists resolutions `1`, `15`, `60`, `240`, `480`, `720`, `1D`, `2D`, `3D`; the Swagger example also shows `5` and `D`. Daily is `1D` | Top level, not in `result`: `s` (`ok` or `no_data`), arrays `t` (int), `o`, `h`, `l`, `c`, `v` (strings) |
| `GET /v1/all-fairPrice` | none | Fair price of every market, identical to the `public:all@fairPrice` channel (fields below) |
| `GET /v1/networks`, `GET /v1/currencies` | none (public) | Network names, withdrawal fees and minimums per coin |
| `GET /v1/otc/markets` | none | `symbols{…}` with spot fields plus `maxNotional`, `buyStatus`, `sellStatus`, `exchangeStatus`, `isZeroFee`, `stats` |

**Trade direction.** `isBuyOrder=true` means the resting (maker) order was the buy, so a seller was the
aggressor; `false` means a buyer was. The repository's collected data agrees (20,000 trades: buyer-initiated
prints sat at or above the prior ask 5,761 times against 1,014 at the bid).

## Account (key required)

| Method and path | Parameters | Response |
| --- | --- | --- |
| `GET /v1/account/balances` | none | `balances{ASSET: {asset, faName, fiat, value, locked, is_dust, is_digital_gold, asset_png_icon, asset_svg_icon}}`; `value` and `locked` are decimal strings |
| `GET /v1/account/fee` | none | `{SYMBOL: {makerFeeRate, takerFeeRate (strings), recent_days_sum (number)}}`. Live responses also carry account-level keys such as `levels`; skip rows without the rate fields |
| `GET /v1/account/card-numbers` | none | `[{id, card_number (masked), owners[], status, is_default, bank_details{code, label}}]` + `result_info` |
| `GET /v1/account/ibans` | `page`, `per_page` | `[{id, iban (masked), owners[], bank_name, status, is_default, withdraw_daily_amount, withdraw_available_amount, bank_details{code, label, is_available}}]` + `result_info` |
| `POST /v1/account/ibans` | body `{iban}` (without the `IR` prefix) | The new IBAN record, `status: PENDING` |
| `GET /v1/account/wallets/{symbol}` | `network` (query, e.g. `ERC20`) | `coin_type{key, name, type, deposit_/withdrawal_availability, …}`, `wallets{NETWORK: {network{id, name, type, …}, address, memo, expire_at, min_confirmation, transaction_fee, min_withdrawal_value, min_deposit_value}}` |
| `POST /v1/account/money-withdrawal` | body `{iban: <IBAN record id>, value: <rials>}` | 201: `amount`, `fee`, `tracking_code`, `created_at`, `status`, `iban{…}`, `details[{value, status}]` |
| `POST /v1/account/crypto-withdrawal` | body `{coin, network, value (string), wallet_address, memo?, client_unique_id?}`; resending the same `client_unique_id` returns the earlier withdrawal | Not specified by the Swagger |
| `GET /v1/account/crypto-withdrawal` | `asset`, `wallet_address`, `memo`, `network_id`, `from_date`, `to_date`, `page`, `per_page` (at most 20) | List; statuses `Accomplished`, `InProgress`, `Rejected` |
| `GET /v1/account/crypto-withdrawal/{withdrawal_id}` | path id | One withdrawal; empty `result` if it belongs to another user |

## Spot orders (key with trade permission)

| Method and path | Parameters | Response |
| --- | --- | --- |
| `POST /v1/account/orders` | body `{symbol, side, type, price, quantity, stop_Price?, client_id?}`; `type` one of `LIMIT`, `MARKET`, `STOP_LIMIT`, `STOP_MARKET`; numbers as strings; `stop_Price` required for the stop types and forbidden otherwise; `client_id` letters, digits and `_` only, unique per account (a duplicate rejects the order; omitted, Wallex generates one); at most 20 requests per 10 s | 201: `OrderResource` |
| `GET /v1/account/orders/{client_id}` | path client order ID | `OrderResource`; 404 if unknown |
| `DELETE /v1/account/orders` | body `{clientOrderId}` | Cancelled `OrderResource` |
| `DELETE /v1/account/orders/{client_id}` | path client order ID | Cancelled `OrderResource` |
| `GET /v1/account/openOrders` | `symbol`, `page`, `per_page` | `result{KEY: [OrderResource]}` (a map of arrays) + `result_info` |
| `GET /v1/account/orders` | `market`, `type`, `side`, `page`, `per_page` (default 25, at most 100), `from`, `to` (`YYYY-MM-DD`) | `result{KEY: [OrderResource]}` + `result_info` |
| `GET /v1/account/trades` (older reference) | `symbol`, `side` | `AccountLatestTrades[]`: `symbol`, `price`, `quantity`, `sum`, `fee`, `feeCoefficient`, `feeAsset`, `isBuyer`, `timestamp` |

`OrderResource`: `symbol`, `type`, `side`, `price`, `stopPrice`, `stopPriceCondition`, `origQty`, `sum`,
`executedQty`, `executedPrice`, `executedSum`, `executedPercent` (int), `fee`, `status` (seen: `NEW`,
`FILLED`, `CANCELED`), `active` (bool), `clientOrderId`, `transactTime` (int), `created_at`, `updated_at`,
`fills[]` of `{symbol, price, quantity, sum, fee, feeAsset, feeCoefficient, makerFeeCoefficient,
takerFeeCoefficient, isBuyer, timestamp}`. An order can be cancelled until its status is `FINISHED`.
To trade from a trading-credit sub-account, use that sub-account's key and add the header
`sub-account-client-id`.

Order-type rules (spot-types page):

- **LIMIT** rests in the book at the given price.
- **MARKET** fills immediately against the book and may fill at several prices. It is **cancelled
  automatically if it is larger than the book or would move the price 2% from the last trade.**
- **STOP_LIMIT / STOP_MARKET**: if the stop is below the last trade at creation, the order activates when
  the last trade falls to or below the stop; if above, when it rises to or above. Once active it behaves as
  LIMIT or MARKET.

## Instant trade (OTC)

| Method and path | Parameters | Response |
| --- | --- | --- |
| `GET /v1/account/otc/price` | `symbol`, `side` (query) | `price` (string), `price_expires_at` |
| `POST /v1/account/easy-trade/orders` | body `{symbol, side, quantity, from}` | 201: `symbol`, `sourceMarket`, `destinationMarket`, `type`, `side`, `clientOrderId`, `transactTime`, `price`, `origQty`, `executedQty`, `executedPrice`, `executedSum`, `sum`, `executedPercent`, `status`, `active`, `fills[]` (as spot fills) |

The older reference used `POST /v1/account/otc/orders` with `{symbol, side, amount}`; the current Swagger
replaces it with the easy-trade path above.

## Margin trading (`/margin-trade/v1`)

| Method and path | Parameters | Notes |
| --- | --- | --- |
| `GET /public/markets` | none | `Market`: `symbol`, `base`, `quote`, `min_risk_coef`, `max_risk_coef`, `risk_coef_step`, `liquidity_margin`, `max_age` |
| `POST /public/loan` | `{market, side, collateral, risk_coef, open_price}` | `{collateral{min, max}, loan}` |
| `POST /public/dry-run` | `{market, side, collateral, risk_coef, open_price, stop_loss?, take_profit?}` | `call_price`, `liquidity_price`, `loan`, `open_fee`, `extend_fee`, `extend_time`, `trade_fee`, `max_age`, echo of inputs |
| `GET /public/ratio/{market}` | path market | `long_percents`, `short_percents` |
| `GET /user/levels`, `GET /user/levels/{market}` | key | `user_level`, `levels` (per-level `max_loan_volume`, `max_position_volume`, `max_risk_coefficient`, `min_trade_volume`) |
| `GET /user/pnl` | key | `collaterals`, `loans`, `profits`, `total` |
| `GET /positions` | `active`, `position_side`, `market` | `Position` list |
| `POST /positions` | `OpenRequest` (as dry-run) | Opens a position |
| `GET /positions/{id}` | path id | `Position`: `state`, `side`, `market`, `collateral`, `loan`, `risk_coef`, `open_price`, `open_filled_price`, `close_price`, `close_filled_price`, `close_reason`, `call_price`, `liquidity_price`, `stop_loss`, `take_profit`, `interest`, `profit`, `profit_percentage`, `max_age`, `expires_at`, `extend_time`, `is_called`, timestamps |
| `PATCH /positions/{id}/close` | `{price}` | Close |
| `PATCH /positions/{id}/collateral` | `{change}` | Add or remove collateral |
| `PATCH /positions/{id}/sltp` | `{stop_loss, take_profit}` | Edit protection |
| `POST /positions/{id}/profit` | `{close_price, strategy}` | `fee`, `interest`, `profit`, `volume`, `filled_percentage` |
| `GET /orders` | `active`, `market`, `position_side`, `position_id`, `position_type`, `side` | `Order`: `id`, `market`, `side`, `price`, `volume`, `filled`, `filled_price`, `fee`, `status`, `trades[]` |

Terms (margin-types page): the credit ratio (`risk_coef`) multiplies the collateral into the loan; an
opening fee is charged per position and an extension fee every **4 hours**, both deducted from collateral
at close; a position lives at most **21 days** and closes on expiry, liquidation, manual close, or its
stop-loss or take-profit.

## Trading credit (prop packages and sub-accounts)

Endpoints: `GET /sub-accounts`; `GET`/`POST /sub-accounts/transfers`; `GET /v1/account/balances-detail`;
`GET /v1/prop/packages`, `GET /v1/prop/packages/{id}`; `GET /v1/prop/user/packages/active`, `/overview`,
`/history`, `/history/{subAccountClientId}`, `/{id}/check-availability`; `POST`/`DELETE
/v1/prop/user/packages` (activate, cancel); `POST`/`DELETE /v1/prop/user/packages/connect-to-wallet`;
`POST /v1/prop/user/packages/enable-renew`.

Terms: a package lasts 30 days and closes automatically unless renewed (renewal opens 5 days before the
end); credit costs a daily fee; a warning level allows closing or adding collateral before the liquidation
level closes the package; connect-to-wallet tops the package up from the main wallet below the warning level.
The repository does not use trading credit.

## Websocket

Current version (Centrifugo, "version 2"): `wss://api.wallex.ir/connection/websocket` (exact path; a
trailing `/` returns 404). Version 1 (`wss://api.wallex.ir/ws`, socket.io-style
`["subscribe", {"channel": …}]` frames) still works but is deprecated and lacks the newer channels.

### Protocol without an SDK

1. Send `{"id": 1, "connect": {}}` (add `"token"` for the private channel). Reply:
   `{"id": 1, "connect": {"client", "ping": 25, "pong": true}}`.
2. Send one `{"id": n, "subscribe": {"channel": …}}` per channel; several may share a frame. Success is
   `{"id": n, "subscribe": {}}` with no data. Errors return `{"id": n, "error": {"code", "message"}}` and do
   not affect other channels.
3. Data arrives as `{"push": {"channel", "pub": {"data": …}}}`. A frame may contain several messages
   separated by newlines.
4. The server sends `{}` every 25 s; reply `{}` within 8 s or the connection closes with code 3012.
5. After any disconnect, connect and subscribe again. Nothing is replayed, so the gap is lost.

| Limit or behavior | Value |
| --- | --- |
| Channels per connection | 64 (the private channel counts); more fails with error 106 |
| Snapshot on subscribe | None for any channel, including depth; the first message arrives on the next change |
| History | Only `candle:` channels: last 10 messages for up to 2 minutes, via the `history` method |
| Message sequence numbers | Only on `candle:` channels (`offset`) |

Command errors: 102 unknown channel (wrong namespace, e.g. the retired `ticker:all@price`), 103 permission
denied (name without `:` or not in the token), 105 already subscribed (subscribing to the private channel),
106 limit exceeded, 107 bad request (name does not match the namespace pattern), 108 not available, 109
token expired. Close codes: 3005 connection expired (reconnect with a new token), 3008 client too slow
(reconnect), 3012 missed ping (reconnect), 3500 invalid token and 3501 malformed frame (do not retry).
Codes 3000–3499 may reconnect; 3500 and above may not.

### Channels

| Channel | Payload (`push.pub.data`) |
| --- | --- |
| `public:<SYMBOL>@trade` | One trade: `isBuyOrder`, `quantity`, `price` (strings), `timestamp` |
| `orderbook:<SYMBOL>@buyDepth`, `@sellDepth` | Array of `{quantity, price, sum}` (numbers). **Each message is a full snapshot of that side; replace, do not merge** |
| `public:all@price` | One market whose price changed: `symbol`, `price` (string), `24h_ch` (number, 2 decimals, 0 without 24 h data) |
| `public:all@fairPrice` | Every 20 s (sometimes up to ~35 s), a full snapshot: `ts` (ISO; compare as time, not text), `prices{SYMBOL: string}` = (fair bid + fair ask) / 2 rounded to 8 decimals. Symbols may be missing from one message; refetch `GET /v1/all-fairPrice` after 60 s of silence. The channel name is case-sensitive, and a typo before `@` subscribes silently and never delivers |
| `candle:<SYMBOL>@1m`, `@1h`, `@1d` | One candle in UDF shape with single-element arrays (`s`, `t`, `o`, `h`, `l`, `c`, `v`) plus `offset`. Repeated `t` values are full replacements of the open candle; upsert by `t` |
| `private:user#<userId>` | Joined automatically from the token; never subscribe. Events `balanceUpdated`, `orderSaved`, `orderRemoved`, `tradeDetails` (`clientOrderID`, `price`, `quantity`, `sum`, `feeAmount`, `feeCurrency`, `isMaker`, `side`, `symbol`), each with a millisecond `timestamp` |

Private-channel token: `POST /v3/auth/token/refresh` authenticated by the user's website session cookie
(not an API key) returns `ws_access_token` and `expires_in` (900 s observed). Refresh before `ttl` runs out;
expiry gives error 109 and close code 3005.
