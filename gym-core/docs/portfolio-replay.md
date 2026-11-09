# Shared-cash portfolio replay

Open **Paper research → Workbench → Shared-cash portfolio replay**. Load observed
markets and saved portfolios. Select all observed TMN or USDT markets, or enter a
comma-separated subset. A portfolio accepts 2–500 distinct base assets sharing
one quote currency. This is a local computation bound, not a Wallex restriction.
The Compare section uses independent accounts; a portfolio shares one cash book.

Set a historical UTC window, starting cash in the common quote currency, fee
assumption, strategy and registry parameters. Market orders use 500 ms modeled
latency and point-in-time rules. The CLI/API also accept supported native limit,
participation, depth, remainder and sizing assumptions. Compound strategies reject
unsupported limit/remainder configurations explicitly.

## Allocation and risk

Equal weights are the default. Optional inverse-volatility and equal-risk-
contribution targets require aligned continuous past closed returns. Unknown,
gapped, zero-variance, degenerate or nonconvergent histories stay explicit and
cannot authorize new entries. Target weights apply to subsequent decisions.
The covariance budget is markets² × lookback ≤ 1,000,000; equal weights without
correlation grouping do not require covariance.

Maximum individual weights, a cash buffer and positive-correlation group caps
leave unused cash rather than silently redistributing above a cap. Risk-parity
reports the error in the final constrained target risk contributions; constraints
can prevent equal risk. Pending buys reserve quote cash. Each actual fill,
including a resting limit partial, rechecks its permitted budget and cash floor.
Price appreciation can move an existing portfolio below its desired cash ratio;
the floor blocks additional spending rather than pretending cash was created.

Optional rebalancing trims overweight holdings and adjusts existing eligible
positions on the target refresh clock. It never reverses a strategy sell into a
buy, invents a flat-position entry, bypasses an entry gate, or tops up compound
positions outside their entry sizing. It uses normal venue rules, costs and fills;
unsettled sale proceeds are not assumed available.

Drawdown latches persist for the replay. Daily-loss latches reset at Tehran
midnight. Fresh known marks drive risk observations; stale or missing held marks
block new entries. Loss latches cancel pending buys and request exits at the next
decision. Gaps, latency, dust, partials and closures can exceed a threshold or
prevent a fill. Recovery uses verified history reconstruction: save a quote-count
checkpoint, then rebuild its exact prefix in a new worker and compare the full
saved output. Prefix observations, pending orders, reservations, targets and risk
latches are fingerprinted; changed engines or evidence are rejected. This is not
a restore of a running process or qualification on another physical host.

## Strategy controls

All sixteen registry strategies accept an optional `regime_gate`: `ANY` (off),
`UP_TREND` or `RANGE`. The shared detector uses causal EMA/ADX/ATR history, resets
indicator readiness across gaps and never blocks exits. Both detector and base
strategy must finish warmup before readiness is recorded.

Optional `exit_stop_bps`, `exit_profit_bps`, `exit_atr_multiple` and
`exit_after_bars` default to zero/off. They track actual simulated fill cost and
first-fill time, including partial entries and maker/taker exit fee assumptions.
Stops/profit targets use recorded bid decisions, never future highs/lows. An ATR
trail cannot loosen across a gap. Exit requests cancel a working entry before
selling. These are closed-bar paper decisions, not placed venue protection.
Explicitly disabled controls preserve default strategy identities.

## Results and storage

Results show currency, recorded equity/net, remaining cash, sampled drawdown,
allocation readiness/risk state, fills, realized P/L, holdings and each last bid
with its time/freshness. TMN portfolios carry causal USDT-equivalent valuations.
Missing FX stays unavailable; stale FX remains labeled and does not make held
prices fresh. Unlike currencies are never combined into one cash book.

Saved records live in `<store>/runs/portfolios`; the latest 100 are listed,
including CLI-created records. Reads verify native fingerprints and recompute
aggregate performance. Hashes detect changed content, not source authenticity.
Each replay uses an independent SQL read snapshot. Observations are bounded to
200,000 per relevant quote/trade table, the window to 31 days, artifacts to 16 MiB,
and normal API calculation time to 120 seconds. Delivery is bounded separately;
a failed response may follow a successful save, so inspect saved state before
retrying. Existing frozen study engines and records remain intact.

The private `/api/research/action` and `gymctl research` expose the same actions:

- `portfolio-replay`: requires `symbols`, `from`, `to`, `resolution`, `cash`,
  `strategy`, `params`, `rules_mode`, `cost`; optional `policy` selects controls.
- `portfolio-list`: no input; saved references and end summaries.
- `portfolio-read`: `{"run_id":"<16 lowercase hex digits>"}`; verified full record.
- `replay-checkpoint`: `run_id`, `quote_count` (1..100000); works for native saved
  portfolios as well as single-market replays.
- `replay-resume`: `checkpoint_id`; verifies the rebuilt history and full result.

Decimal financial inputs are strings. This workflow cannot borrow, place funded
orders, establish authenticated holdings/settlement, or prove profitability.
