# Venue API Specifications & Protocol Guardrails

Clean machine-readable OpenAPI / Swagger specifications for TradingGYM's two primary Iranian venues, plus verified operational guardrails.

> **Authority boundary:** `TradingGYMExecutor` remains **`DISARMED / NOT CERTIFIED`** (`$0` funded-loss budget). All active multi-venue ingestion in TradingGYM uses **public, zero-auth read-only endpoints only**. Never grant `WITHDRAW`, `ADDRESS_BOOK`, or `OTP` scopes to any automated key.

---

## 1. Nobitex (`nobitex/`, 10 OpenAPI 3.0.3 YAML Specs)

- **Production:** `https://apiv2.nobitex.ir` · WebSocket: `wss://ws.nobitex.ir/connection/websocket`
- **Testnet:** `https://testnetapiv2.nobitex.ir` · WebSocket: `wss://testnetws.nobitex.ir/connection/websocket`
- **Bot Header:** `User-Agent: TraderBot/<name-and-version>`
- **Auth:** Scoped Ed25519 API Keys (`Nobitex-Key`, `Nobitex-Timestamp`, `Nobitex-Signature` = URL-safe Base64 Ed25519 of `timestamp + method + full_path + raw_body`). Scopes: `READ`, `TRADE`, `DEPOSIT`, `WITHDRAW`, `ADDRESS_BOOK`, `OTP`.
  - *Nuance:* `POST /wallets/transfer` currently requires `TokenAuth`; `GET /positions/list` & `GET /positions/{id}/status` require `TRADE` scope.
- **HTTP Convention:** Business/validation errors frequently return **HTTP 200** with `{"status": "failed", "code": "...", "message": "..."}` — always verify `body["status"] == "ok"`.
- **Key Files:**
  - [market_data.yaml](nobitex/market_data.yaml) — `GET /v3/orderbook/all` (`300 req/min`), `/v2/depth/{symbol}`, `/v2/trades/{symbol}`, `/market/stats`, `/market/udf/history` (`500` bars/page, `60 req/min`).
  - [websocket.yaml](nobitex/websocket.yaml) — Centrifugo v2 (`450` channels/conn, zero-token public channels: `public:orderbook-{SYMBOL}`, `public:trades-{SYMBOL}`, `public:candle-{SYMBOL}-{RES}`, `public:market-stats-all`; private `private:orders#{authParam}`, `private:trades#{authParam}` with exact `isMaker` flag).
  - [spot_trade.yaml](nobitex/spot_trade.yaml) — `limit`, `market` (optional slippage-guard `price`), `stop_market`, `stop_limit`, native **`mode: oco`**, `clientOrderId` (`^[A-Za-z0-9-]+$`, max 32), `pro: true`, bulk `/market/orders/cancel-old`. Rate limit: `300 req/10min` shared with margin orders.
  - [margin_trade.yaml](nobitex/margin_trade.yaml) — Isolated Margin (`marginRatio = 1.1`, `30d` max duration, daily EOD extension fee `0.05%/day` on 65 USDT pairs = `13/13` `BASE_13` & `18/18` `IGN18`), live `GET /liquidity-pools/list` (`+2.64% APR` idle USDT), native `OCO` / `stop_limit` / `stop_market` on `/positions/{id}/close`.
  - [user_data.yaml](nobitex/user_data.yaml), [portfolio.yaml](nobitex/portfolio.yaml), [security.yaml](nobitex/security.yaml), [address_book.yaml](nobitex/address_book.yaml), [withdraw.yaml](nobitex/withdraw.yaml), [rial-withdraw.yaml](nobitex/rial-withdraw.yaml).

---

## 2. Wallex (`wallex/`, 4 Swagger 2.0 JSON Specs)

- **Production:** `https://api.wallex.ir` · WebSocket v2 (Centrifugo): `wss://api.wallex.ir/connection/websocket` *(exact path — trailing `/` returns `404`; legacy `wss://api.wallex.ir/ws` is deprecated)*.
- **Key Files:**
  - [basic-services.json](wallex/basic-services.json) — `/hector/web/v1/markets`, `/v1/depth`, `/v1/trades`, `/v1/udf/history`, `/v1/account/balances`, `/v1/account/fee`.
  - [spot.json](wallex/spot.json) — `GET /depth/all`, `POST /v1/account/orders` (`LIMIT`, `MARKET`, `STOP_LIMIT`, `STOP_MARKET`, caller `client_id`), `GET/DELETE /v1/account/orders/{client_id}`, isolated `subAccount_client_id` support.
  - [margin.json](wallex/margin.json) — `14` endpoints including public **`GET /margin-trade/v1/public/ratio/{market}`** (live retail long/short %), `POST /margin-trade/v1/public/dry-run`, `PATCH /margin-trade/v1/positions/{id}/sltp`, `PATCH .../close`, `PATCH .../collateral`, `21d` max age, `0.015%/4h` extension fee.
  - [otc.json](wallex/otc.json) — `/v1/otc/markets`, `/v1/account/otc/price`, `/v1/account/easy-trade/orders` *(excluded from alpha; 1.5%–2.5% worse than orderbooks)*.
- **Critical Wallex Guardrails:**
  - **2% Market-Order Auto-Cancel:** Any `MARKET` order exceeding book depth or moving last trade price by `> 2%` is automatically canceled by Wallex — always use collared `LIMIT` orders for urgent exits.
  - **Centrifugo v2-only channels:** `public:all@fairPrice` (~20s snapshot of all markets' `(bid+ask)/2` fair prices, also at `GET /v1/all-fairPrice`), `candle:<SYMBOL>@1m|1h|1d`, and server-auto-subscribed `private:user#<userId>` (do **not** manually `subscribe()`, or server returns `105: already subscribed`).
  - **Prop / Trade-Credit Hazards:** Fixed daily fee bleeds equity `-81%` to `-91%` in cash/chop regimes; `10×` packages liquidate after just `-5.45%` sub-account drops (`liquidity_limit`); **never** enable `POST /v1/prop/user/packages/connect-to-wallet` (auto-drains main wallet into losing sub-accounts).
