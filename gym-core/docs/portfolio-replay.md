# Shared-cash portfolio replay

Open **Paper research → Workbench → Shared-cash portfolio replay**. Load observed
markets, enter 2–8 comma-separated markets with different base assets and one quote
currency, then set a historical UTC window, starting cash, fee assumption, strategy
and parameters. Available markets come from the stored observations, without a
BTC/ETH shortlist. The eight-market bound is a local calculation budget, not a
Wallex restriction.

The form checks the running backend's portfolio capability. If an older
observatory process is still running, it stays disabled and requests a restart;
new static assets alone do not establish a new backend capability.

Each market runs the same strategy against one cash book. Entries target an equal
share of portfolio equity and cannot spend more cash than remains. Market clocks
close before later quotes become visible. This models simultaneous holdings;
the Compare tab instead compares independent accounts.

The form uses market orders, 500 ms modeled latency and point-in-time rules. Cash
is in the common quote currency: 1000 TMN and 1000 USDT are different budgets.
The supplied fee is an assumption, not a newly measured account fee. Results show
the recorded equity curve, per-market fills, realized P/L and remaining holdings.
Aggregate return and sampled drawdown are recomputed when the saved record is
verified; unbound saved performance fields are not trusted.

Saved portfolios live in `<store>/runs/portfolios`. The workbench lists the latest
100, including CLI-created records. It loads full records through a bounded native
integrity check. Hashes detect changed content; they do not authenticate its source.
Large results may exceed the API's 2 MiB delivery limit; narrow the replay window
or inspect the saved record locally. A failed response can follow a successful
save, so inspect saved portfolios before repeating a calculation.

The private `/api/research/action` route and `gymctl research` expose these same
actions:

- `portfolio-replay`: requires exactly `symbols`, `from`, `to`, `resolution`, `cash`,
  `strategy`, `params`, `rules_mode` and `cost`; returns a saved record reference.
- `portfolio-list`: no input; lists saved references and end summaries.
- `portfolio-read`: `{"run_id":"<16 lowercase hex digits>"}`; verifies the saved record.

`cost` accepts the existing native cost description: `fee_rate`, `latency_ms`,
`max_wait_s`, `fee_assumption` and supported execution/sizing options. Decimal
amounts remain strings. The replay window is at most 31 days, native portfolio
observation counts are bounded, and the disposable worker has a 120-second
deadline. It cannot submit a venue order or borrow money.

Revision 3 binds point-in-time FX conversion to the saved identity. Both boundary
rates and every curve rate use the last qualified quote already available, with a
one-day lookback before the window. Missing start FX leaves USDT-equivalent net
unavailable. STALE and STALE_CLOSED retain an old derived rate explicitly; this
is valuation rather than executable conversion. A graph is omitted if any FX
curve mark is unavailable, instead of connecting across that gap.

Replay marks can be stale and gaps can hide losses. Dynamic weights and
portfolio-wide risk limits remain separate items in the
[implementation plan](implementation-plan.md); this workflow does not claim them.
