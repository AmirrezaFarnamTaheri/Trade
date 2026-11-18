# Toman and USDT conversion routes - 2026-11-18

`gym-core/scripts/conversion_route_study.py` asked, every 15 minutes from 2026-10-31 to 2026-11-18, the question
`gymctl convert-route` answers live: convert directly on USDTTMN, or buy a coin with one currency and sell it for the
other? Each leg filled at the best displayed price, paid 0.10%, and had to fit the displayed size. Samples without fresh
quotes (collector gaps) are left out.

| Direction and size | Samples | Coin route cheaper | Median saving then | USDTTMN unavailable | Coin now vs waiting for USDTTMN |
| --- | --- | --- | --- | --- | --- |
| 5M TMN to USDT | 868 | 10.8% | 4.0 bps | 405 | median -17.9 bps; better 18% of the time |
| 50M TMN to USDT | 806 | 3.1% | 2.7 bps | 484 | median -34.8 bps; better 7% |
| 500M TMN to USDT | 83 | 0% | | 6 | median -1.4 bps; better 50% |
| 20 USDT to TMN | 840 | 13.4% | 5.1 bps | 421 | median -14.8 bps; better 22% |
| 200 USDT to TMN | 770 | 0.8% | 2.6 bps | 521 | median -28.0 bps; better 10% |
| 2,000 USDT to TMN | 27 | 0% | | 3 | median -23.0 bps; better 0% |

## What it means

- Converting directly on USDTTMN is almost always cheapest. A coin route saves a few basis points on small amounts, rarely.
- While USDTTMN is closed (23:30 to 11:30 Tehran) or stale, a coin route is always available but usually dearer than
  waiting: a median 15 to 35 bps worse. Wait unless the timing matters more than that.
- One 20 USDT sample showed a 1,769 bps "saving". That is a single thin or stale quote, not a saving to expect.
- Larger amounts rarely fit the displayed top of book. The collector does not currently store depth, so routes for large
  amounts cannot be priced; turning on depth recording would fix that.
