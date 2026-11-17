# Current capability boundaries

The [architecture](architecture.md) identifies implementation owners and browser
locations. The [roadmap](roadmap.md) lists open work. This page describes
the supported product boundary.

## Stages

Every capability statement names one of these stages. A later stage is never implied by an earlier one.

| Stage | Meaning |
| --- | --- |
| In source | Merged on master with local tests; not built into the installed bundle |
| Installed | The exact binary bundle on this host, identified by its published hashes |
| Qualified | Installed and exercised on this host against its recorded checks (custody, STOP, recovery, venue reads) |
| Armed | An owner has armed the qualified installation; only then can a funded order be sent |

Today the funded LIMIT path is **in source** only. The installed service predates it. Nothing is qualified or armed.

| Capability | Current scope | Evidence limit |
| --- | --- | --- |
| Market collection | Catalogue-wide public spot observations, recorded depth/trades/candles, SQL publication and raw archive | Selection is not freshness; per-market gaps and stale quotes remain visible |
| Paper strategies | Sixteen native long/flat rules, configurable indicators, compound policies, default-off regime gates, fixed/profit/ATR/time exits and opt-in trade-triggered fixed stop-market | Paper exits can miss or exceed thresholds; no venue protection or established edge |
| Comparison and validation | Matched independent accounts, expanding walk-forward selection and held-out diagnostics | Historical selection is not independent final evaluation |
| Shared-cash portfolios | Up to 500 distinct-base markets per quote book, exact reservations, equal/inverse-volatility/risk-parity targets, correlation caps, conditional rebalancing, cash buffers, loss latches, causal FX and verified checkpoint reconstruction | Covariance/observation/worker budgets apply; stale held marks block entries; no authenticated portfolio execution or runtime recovery qualification |
| Product capabilities | All observed markets joined to an explicitly selected public margin receipt, credit grid and LONG/SHORT availability | Observation is not current listing, credit eligibility, permission or collateral qualification |
| Coverage and recovery | Recorded bucket/readiness timeline and explicit retry, catch-up, skip and interrupted-claim controls | Missing periods stay missing; claim interruption does not kill a process |
| Replay and experiments | Verified decisions, annotations, registry pages, retained trials/failures, scorecards/heatmaps/path overlays, store-scoped counts, instrumented process ownership and local consume-once evaluations | Ready/traded counts are a bounded verified sample; old progress is not liveness; local ledgers are not independent custody |
| Paper sizing | Exact stop-risk entries against held exposure/pending cash, plus capped fractional Kelly diagnostics from completed preregistered evaluations | Unknown venue limits abstain; hypothetical stops can fail; fractional diagnostics require simple closed positions and do not change allocation automatically |
| Screening and diagnostics | Comparable recorded markets, exact supplied-data models and return/cost diagnostics | Supplied holdings/fills/forecasts are unauthenticated; scoring is not prediction |
| Margin paper | Public rules/previews and recorded LONG/SHORT positions using venue credit grids | No real loan, position or protective order is submitted |
| Account observations | Sanitized journal and separately protected read-only transport contracts | Observation is not completeness, spendability or settlement |
| Protected executor | In source: custody, review, receipts, holds, elevated approval, one-shot LIMIT orders, settlement and independent STOP | Installed bundle predates the LIMIT path; nothing is qualified or armed; browser cannot arm or submit |
| Backups | Encrypted native backup/restore and append-only receipt history | Receipt presence does not prove current archives or runtime readiness |

Predictive ML/RL training is paper-only; models may be fitted on historical data, with every fit registered and counted as a trial (see PRODUCT.md). Unrelated donor runtimes and automatic paid requests are outside accepted scope.

## Venue coverage

Every trading capability in the [Wallex reference](wallex-reference.md) has a row here. A venue capability
without paper support is a gap to close, not a boundary. Funded use of every row stays DISARMED.

| Venue capability | Reference section | Paper support | Gap |
| --- | --- | --- | --- |
| Spot `LIMIT` and `MARKET` orders | Spot orders | Simulated with fees, depth walk and the 2% market-order guard | None known |
| Spot `STOP_LIMIT` and `STOP_MARKET` orders | Spot orders | `stop-preview` replays one supplied order; single-rule strategies can opt into fixed stop-market activation from received trades and work partial remainders | Strategy stop-limit and trailing venue stops remain unsupported; missing historical trades cannot supply activation |
| Instant trade (OTC) quotes and orders | Instant trade (OTC) | Availability and notional limits come with the spot catalogue and show in the product report | `GET /v1/account/otc/price` refuses the read-only key (403 scope, checked 2026-11-13), so no quote is collected and no quoted fill is replayed. Sampled once with a trade-scope key: the quote was 0.75% to 1.4% worse than the order book on each side (trial T7) |
| Margin LONG / SHORT positions | Margin trading | Public rules, loan and dry-run previews; replay with opening, trade and 4-hour extension fees, liquidation, call warning, stop-loss, take-profit, expiry and timed exit | Stop-loss, take-profit and collateral changes during a position; account level limits (`/user/levels` needs a key) |
| Margin long/short ratio | Margin trading | None | `GET /public/ratio/{market}` is public and not collected |
| Trading credit packages and sub-accounts | Trading credit | `credit-packages` saves the public package list; `credit-replay` holds one asset in one package on recorded quotes with the daily fee, the warning level, liquidation and expiry | The limits are assumed to apply to the whole account value; renewal, wallet top-up and trading inside the package are not modeled |
| Per-account maker and taker fees | Account | Recent start-known account rates feed the paper cost model by market, with dated provenance | Rates are frozen at replay start; `/v2/structured-fee` is not collected |
| Catalogue product flags (`is_margin`, `is_otc`, `max_leverage`, `leverage_step`, `is_zero_fee`) | Public market data | Stored/shown by catalogue version; a start-known boolean zero-fee flag applies in paper replay | In-run flag changes are not reconstructed; absent flags remain unknown |
| Fair price | Public market data, Websocket | Observed and stored | None known |
| Candles, depth and trades | Public market data, Websocket | Collected | `GET /depth/all` and `public:all@price` are unused; not needed while per-market channels run |
| Deposits, withdrawals, IBANs and cards | Account | None | Out of scope: custody, not trading |

