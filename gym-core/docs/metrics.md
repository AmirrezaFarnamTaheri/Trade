# Paper performance metrics

Every saved run shows these on Paper research → Saved runs; `gymctl paper` prints the main ones.
All of them describe a paper replay with modeled costs. None of them is evidence that live trading would pay.

| Figure | Meaning | Caveat |
|---|---|---|
| Total return | End equity ÷ starting cash − 1 | Includes the open position marked at the bid |
| Annualized return | Total return compounded to a year | Shown only for windows of 30 days or more |
| Volatility per period | Standard deviation of returns between equity marks | Marks are decision bars; gaps hide moves |
| Sharpe per period | Mean ÷ standard deviation of those returns | Not annualized for short windows |
| P(true Sharpe > 0) | Probabilistic Sharpe ratio (Bailey & López de Prado): allows for skew and fat tails | Assumes returns are not serially dependent |
| 90% range | Stationary block bootstrap of the returns, fixed seed | A wide range means little evidence |
| Deflated Sharpe | P(true Sharpe > luck threshold of the best of N tries); N counts every configuration saved for the market and decision close | Sharpe spread comes from the candidates compared now |
| Sortino | Like Sharpe, with only losses as risk | Annualized only for 30+ day windows |
| Max drawdown / Calmar | Largest fall from a running peak; annualized return ÷ max drawdown | Sampled at marks, so true drawdown can be larger |
| Below the running peak | The underwater chart under the equity curve | Same sampling caveat |
| Win rate, profit factor, expectancy | From the first-in-first-out ledger of closed trades | Open positions are excluded |
| Average-cost P/L | Realized P/L if each sale used the average purchase price | Equals FIFO once the position is flat |
| Time in market, turnover | Share of the window with a position; fills ÷ starting cash | Costs scale with turnover |
| Kelly fraction | Win rate − loss rate ÷ payoff, floored at 0 | Shown after 20 trades; use a fraction of it |
| Beta, alpha, information ratio, correlation | Against holding the base asset over the same marks | Per period; alpha annualized for 30+ days |

Execution models that change these figures: `--participation`, `--walk-depth` (needs `run --depth-levels`),
`--carry-remainder`, `--order-type limit` with `--maker-fee`, and sizing with `--max-fraction` / `--vol-target`.
Default strategy configuration hashes remain unchanged (see [decision D4](decisions.md)).
New TMN historical runs include the explicit causal-fx-curve/1 valuation fingerprint;
their run IDs differ from older records, which are retained without rewriting.
USDT already uses native identity and keeps its existing default run IDs.

Resting limit fills use `queue-capacity/2`: trades first deplete the displayed
queue ahead, and only their remaining quantity can fill the order. Trades through
the limit and crossing quotes also have observed capacity bounds. Quote and print
capacity are not added when they may describe the same liquidity. Partial fills
retain a working child for the exact remaining quantity until expiry or session
end. Maker fees post on every fill. Public observations do not reveal actual queue
position; this remains a model. Older limit runs predate this correction and are
retained; new limit runs carry a different cost-model fingerprint.

RSI rebound, MACD crossover, TRIX crossover and Keltner breakout expose bounded
periods and thresholds through the strategy registry, CLI `--params` and browser
parameter controls. RSI requires `period + 1` bars; MACD requires
`slow + signal - 1`; TRIX requires `3 × period + signal - 2`. Keltner readiness
also requires its configured ADX and channel history. Gaps reset that history.
Original defaults retain version 1 and their original configuration hashes;
nondefault settings use version 2 and distinct hashes.

Historical single-market curves and shared-cash portfolios use the same causal
FX owner. Each curve mark carries its actual factor, age and LIVE/STALE/
STALE_CLOSED/UNAVAILABLE state; USDT uses exact identity. Unknown factors remain
null and prevent a joined conversion graph. FX conversion does not refresh a
stale asset mark or establish an executable conversion price. Original historical
records without these marks remain inspectable without retrospective mutation.
