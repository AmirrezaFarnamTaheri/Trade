# Roadmap

One question governs the work: is there a net edge on Wallex after costs, against holding USDT?
The [trial log](trial-log.md) holds the answer so far. This page lists open work only; finished work is in Git.

## Evidence

- Follow the BTCUSDT 50-day trend rule (T6) on paper every day until the 2027-02-08 checkpoint.
- Later trials use information the failed ones did not: order-book imbalance, the implied Toman premium and
  recorded-quote microstructure, with expected value and position size as outputs.

## Paper engine

- Extend strategy stop-market support to stop-limit and trailing orders after their paper contracts are defined.
- Reconstruct in-run fee-tier and catalogue fee changes when historical receipts exist.
- Collect the margin long/short ratio and `/v2/structured-fee`.

## Funded path

Disarmed. The wiring order is in
[ADR 0007](../../docs/adr/0007-wiring-the-funded-path-behind-an-arm-button.md). Review v2, active holds and
checkpoint events are wired in source and awaiting separate owner review/publication. Remaining: checkpoint
scale/background verification, privileged arm request, verified available admission and end-to-end fault tests.
The owner accepted [service receipt ordering](../../docs/adr/0008-balance-observation-ordering.md): two fresh
reads, own-activity fencing, disagreement disarm and conservative held-funds subtraction. Implement that
contract; the venue's undocumented balance sequence is no longer a requirement.

## Operations

- Qualify each reviewed native service build on the installed Windows host before use.

The owner canceled off-machine backup scheduling and second-machine restoration on 2026-11-16.
