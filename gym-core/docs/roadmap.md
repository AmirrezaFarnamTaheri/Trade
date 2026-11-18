# Roadmap

One question governs the work: is there a net edge on Wallex after costs, against holding USDT?
The [trial log](trial-log.md) holds the answer so far. This page lists open work only; finished work is in Git.

## Evidence

- Follow the BTCUSDT 50-day trend rule (`btc-daily-trend`) on paper every day until the 2027-02-08 checkpoint.
- Later trials use information the failed ones did not: order-book imbalance, the implied Toman premium and
  recorded-quote microstructure, with expected value and position size as outputs.
- Candidate forward record: `funding-confirmed-trend` was positive where the plain trend rule lost, but missed its pass mark
  (probability 0.759). Running it forward on paper needs daily funding observations, which the public archive publishes
  only as monthly files; collect daily funding before starting it.
- The broad Binance held-out set (2024 to 2026, about 450 coins) is consumed for daily trend and breakout rules. New trials
  need new data: intraday bars, order-book data, or the forward record.
- Research budget: at most two registered trials open at a time, each with new information or new data.
  Another broad parameter sweep of the same price history is exploration, not a trial (trial-log method notes).
- Machine-learning and reinforcement-learning models stay paper-only and wait for a signal that a simple rule shows
  is useful. `logistic-entry-gate` failed; a larger model on the same inputs is not new evidence.

## Paper engine

- Extend strategy stop-market support to stop-limit and trailing orders after their paper contracts are defined.
- Reconstruct in-run fee-tier and catalogue fee changes when historical receipts exist.
- Collect the margin long/short ratio and `/v2/structured-fee`.

## Funded path

Disarmed. Arming is not the next routine milestone: it waits for the 2027-02-08 checkpoint, a published bundle,
owner approval and installed-host qualification, in that order. If the checkpoint shows no edge, the observatory
is the product and funded-path work stops. Trading-credit packages stay separate from position margin: they put
money in a sub-account and are a different risk contract, not a leverage setting. The wiring order is in
[ADR 0007](../../docs/adr/0007-wiring-the-funded-path-behind-an-arm-button.md). Review v2, active holds and
checkpoint events, independent startup audit, privileged approval, native admission and one-shot LIMIT
transport/settlement are wired and locally fault tested. Remaining: owner review/publication of the complete
binary bundle, installed-host/venue qualification and the registered prospective checkpoint.
The owner accepted [service receipt ordering](../../docs/adr/0008-balance-observation-ordering.md): two fresh
reads, own-activity fencing, disagreement disarm and conservative held-funds subtraction. That contract is
implemented. The venue's undocumented balance sequence is no longer a requirement.

## Operations

- Qualify each reviewed native service build on the installed Windows host before use.

The owner canceled off-machine backup scheduling and second-machine restoration on 2026-11-16. That accepts a
known exposure: losing this laptop or its disk loses everything since the last copy the owner made by hand.
Local restore drills prove the backup files decrypt; they do not remove that exposure.
