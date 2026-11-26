# `btc-daily-trend` exact-accounting replay - 2026-11-16 Tehran

The fixed BTCUSDT 50-day close-above-mean rule was replayed through `PaperSession`,
`market_order` and `CashBook` using exact Decimal postings. No settings were selected
and no statistical score was recalculated on the already consumed `btc-daily-trend` data.

- Engine: `paper-session/10`; local immutable artifact: `data/research/daily-trend-replay/142b9e014757fb99.json`.
- Window: 1,049 traded venue daily candles, 2024-01-01 through 2026-11-14; 50 earlier closes for warmup.
- Start: 1,000 USDT, flat. End: 1,802.951269573206689888678554 USDT, flat (+80.2951%).
- Fills: 72. Modeled fees 108.73528970 USDT; modeled spread cost 108.73625618 USDT.
- Original floating-point screen: +80.6%, 71 switches. The replay starts with cash instead of inheriting
  the pre-2024 position and uses received-asset fees and multiplicative bid/ask prices.
- Tests: `tests/test_daily_trend_replay.py`, 2 passed: exact cash conservation, no negative balances,
  no orders using the final candle's future, input rejection.

The captured result uses engine 10 on `codex/research-evidence`, before the paper
engine batch. From that branch's `gym-core`, reproduce with
`scripts/daily_trend_replay.py --db ../data/live/market.db --out ../data/research/daily-trend-replay`.
The script freezes the original window and uses the immutable artifact writer.
Running it with a later engine creates a different input identity; it does not
replace this artifact or authorize another statistical score.

Daily candles are retrospective data, not recorded historical books. The replay assumes bid/ask at
close minus/plus 0.10%, a 0.10% fee per side and immediate execution. Historical liquidity, fills,
and historical venue rules are unknown; dated lot constraints apply where recorded. UTC daily boundaries
match the downloaded candles. These assumptions validate accounting only. The forward journal and
2027-02-08 checkpoint remain the independent evidence requirement; funded execution remains disarmed.
