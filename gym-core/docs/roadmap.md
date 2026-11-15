# Roadmap

One question governs the work: is there a net edge on Wallex after costs, against holding USDT?
The [trial log](trial-log.md) holds the answer so far. This page lists open work only; finished work is in Git.

## Evidence

- Follow the BTCUSDT 50-day trend rule (T6) on paper every day until the 2027-02-08 checkpoint.
- Replay T6 through the exact paper engine.
- Next trials use information the failed ones did not: order-book imbalance, the implied Toman premium and
  recorded-quote microstructure, with expected value and position size as outputs.
- Import the off-machine recorder's quote files automatically (they expire after 90 days).

## Paper engine

- Apply zero-fee markets and the account fee tier in the cost model.
- Let strategies place venue stop orders.
- Collect the margin long/short ratio and `/v2/structured-fee`.

## Funded path

Disarmed. The wiring order is in
[ADR 0007](../../docs/adr/0007-wiring-the-funded-path-behind-an-arm-button.md): mount review frame v2, active
holds, ledger checkpoints, the privileged arm request, verified available balance in admission, then fault tests.

## Operations

- Off-machine backup on a schedule, and a restore on a second machine.
- Remove the MCP server and research worker launchers together with their installer scripts.
