# Arming policy

A policy states the most money a funded probe may lose and when it must stop. Writing one arms nothing: the
executor stays DISARMED, and `gymctl arm-preflight` keeps listing every other gate. When the privileged arming
path exists, the active policy's hash is bound into the arm record, so a probe can never run under different
limits than the ones you chose.

```powershell
uv run gymctl arm-policy list            # the options below and which one is active
uv run gymctl arm-policy show cost-probe
uv run gymctl arm-policy set cost-probe  # writes data\live\arm-policy.json
uv run gymctl arm-preflight              # READY / BLOCKED with reasons
```

## The options

| | **cost-probe** (recommended first) | **pilot** | **extended** |
|---|---|---|---|
| Purpose | Measure real fills, fees and slippage against the paper cost model | Run one strategy that survived the gates, small | Longer run after the pilot matched its paper costs |
| Total loss cap | 10 USDT | 50 USDT | 200 USDT |
| Largest single order | 5 USDT | 20 USDT | 50 USDT |
| Orders per day | 10 | 20 | 40 |
| Kill: stop at a loss of | 5 USDT | 25 USDT | 100 USDT |
| Kill: stop when data is older than | 10 s | 15 s | 20 s |
| Kill: open orders at most | 1 | 2 | 3 |
| Markets | ETHUSDT, BTCUSDT | ETHUSDT, BTCUSDT | ETHUSDT, BTCUSDT |
| Expires after | 7 days | 14 days | 30 days |
| Prerequisite | Executor arming path built and reviewed | cost-probe finished; acceptance gates closed; one strategy passed the holdout | pilot costs matched the paper model within its stated tolerance |

## Why these numbers

- **No positive paper result exists yet** (acceptance status), so the first funded step should buy information,
  not returns. A cost probe answers the question every later step depends on: do real fills cost what the paper
  model says? Its whole budget is the price of that answer.
- **Liquidity is thin.** On 2026-11-09 the most liquid USDT markets traded about 236,000 (ETHUSDT) and 121,000
  (BTCUSDT) USDT a day. A 5 USDT order is roughly 0.002-0.004% of daily volume, small enough that it measures the
  market instead of moving it; 50 USDT is still under 0.05%.
- **USDT markets, not toman.** A USDT-quoted probe keeps the toman/USDT exchange-rate swing out of the cost
  measurement. A toman variant needs its own policy with `quote_asset: TMN` (orders well above the observed
  90,000 TMN OTC minimum).
- **Kill at half the cap** leaves room for a stop that executes late without breaching the cap itself.
- **Stale-data limits** sit just above the collector's normal quote cadence, so a feed outage stops new orders
  quickly; the larger tiers allow a little more because they hold positions longer.
- **One open order** in the cost probe means every fill is attributable to one decision.
- **Every policy expires.** Arming never outlives its review window; renew it on purpose.

## Unverified facts to check before arming

- The venue's minimum **spot** order size is not in the stored instrument specs (only the OTC minimum of
  2 USDT is). Confirm a 5 USDT spot order is accepted, or raise `max_order_quote` in the cost probe.
- The fee rate used by the paper model (0.10%) was observed once on 2026-11-01 via the account endpoint; the cost
  probe exists to measure it under real conditions.

## Choosing

Start with **cost-probe**. Move to **pilot** only after the probe's measured costs are recorded and the
acceptance gates are closed. To change any number, copy a file in `contracts/arm-policy/`, edit it, and install
it with `arm-policy set`; the validator rejects incoherent limits (an order larger than the cap, a kill level
above the cap, symbols in the wrong quote currency, no expiry).
