# Paper costs and strategy stops

New runs use `paper-session/12` (market) or `/13` (limit). Existing saved runs,
their identities and results stay intact. A frozen hypothesis requiring an older
engine must use that engine; it is not silently upgraded.

## Fees

`calibrated_cost` resolves omitted fees from a recent account GET receipt known
at the replay start, retaining its timestamp and maker/taker rates by market.
Stale, later, demo or absent receipts leave the declared fallback of 0.001.
Explicit account-fee overrides remain available. A catalogue `isZeroFee` or
`is_zero_fee` boolean known at the replay start makes that market's fee zero,
including optional cost profiles. Strings such as `"true"` do not establish this.
The effective market cost is recorded beside the paper result.

Fees are frozen at the replay start; this batch does not reconstruct changes to
the account tier or zero-fee status inside a run. Fees charged in the received
asset remain a declared accounting assumption. A read receipt does not establish
spendable balances or funded permission.

## Strategy stop-market

Set `exit_stop_bps` to a positive fixed loss threshold and `exit_venue_stop` to 1
in a single-rule strategy's parameters. Zero disables the new mode. ATR trailing
stops and compound strategies are refused in this mode. Profit/time exits and
ordinary strategy exits retain their existing behavior.

After a buy fills, the session models a fixed stop using the fee-inclusive entry
and exit fee. Waiting stops reserve no inventory. Only a public trade received
after placement, with an event at or after placement and price at/below the stop,
activates it. A crossing quote alone does not. Activation cancels the session's
working ordinary order; the stop then uses available quote liquidity and the
existing market-order rules, costs, precision and minimums. Partial remainders
continue on later quotes. Earlier bar decisions cannot see a later stop fill.

The run retains trigger event/receipt times, fill/nonfill records, unfinished stop
state and consumed trade evidence in its identity, including shared-cash portfolios
and replay checkpoints. Input budgets fail explicitly rather than dropping ticks.

This is a paper model of a fixed stop-market order. It does not install a venue
order, certify activation/queue latency, or promise an exit across gaps, closures,
unknown rules or insufficient liquidity. Historical candles cannot supply missing
historical trade triggers.
