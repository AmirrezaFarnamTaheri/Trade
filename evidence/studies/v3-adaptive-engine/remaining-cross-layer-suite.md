# Remaining Cross-Layer Design & Micro-Signal Stress Suite

- **Generated:** `2026-11-26T08:35:48.318567+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## 1. Relative Strength During Selloff & Sensor-vs-Trading-Venue Separation
- **Triggered Selloff Episodes:** `26`
- **Source Symbol 12h Net:** `-113.72 bps` · **Liquid BTC Equivalent:** `-42.17 bps` · **Low-Beta Control:** `-42.17 bps`

## 2. Post-Shock Liquidity Recovery, Blind-Scanner Cadence Miss & Conditional-on-Fill Adverse Selection
- **Liquidity Recovery Events:** `8` (full) vs `7` (`3x` thinned → **`12.5%` missed**) · **Mean Net Edge:** `-47.27 bps`
- **Conditional Passive Fill Markout:** Fast (`<=60s`): **`+0.00 bps`** · Slow (`>60s`): **`-11.37 bps`** · Unfilled Missed Drift: `+15.60 bps`

## 3. Delisting Stress, 5-Day Outage Restart Policies, TMN Liability & Shared-Rail Stress
- **Clean Slow Core:** `+152.23%` · **SOL Delist (50% rec):** `+156.62%` · **SOL Delist (0% rec):** `+156.62%`
- **5-Day Outage Recovery:** `RECOMPUTE=+151.47%` · `DISCARD_EXPIRED=+150.89%` · `REPLAY_STALE=+151.50%`
- **Scheduled 20M TMN Withdrawal (500 bps FX Spike):** Ending `1905.04M TMN` (extra FX spike cost `$21.30` USDT)
- **Shared Operational Dependency Stress:** `{'NOBITEX_OFFLINE_STRANDED_PCT': 50.0, 'USDT_5PCT_DEPEG_LOSS_USDT': 40.0, 'XAUT_ISSUER_FREEZE_STRANDED_PCT': 20.0, 'DUAL_NOBITEX_PLUS_XAUT_STRANDED_PCT': 60.0}`

## 4. Order Timeout → Replacement Partial → Late Original Fill Reconciliation
- **Reconciled State:** `cash=$859.58`, `units=1.4`, `fees=$0.2243`, `overfilled_orders=True`, `filled_by_order={'ord_1': 1.0, 'ord_2': 0.4}`
