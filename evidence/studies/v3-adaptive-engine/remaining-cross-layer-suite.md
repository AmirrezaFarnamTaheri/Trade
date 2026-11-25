# Remaining Cross-Layer Design & Micro-Signal Stress Suite

- **Generated:** `2026-11-25T21:51:32.420957+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## 1. Relative Strength During Selloff & Sensor-vs-Trading-Venue Separation
- **Triggered Selloff Episodes:** `26`
- **Source Symbol 12h Net:** `-113.72 bps` · **Liquid BTC Equivalent:** `-42.17 bps` · **Low-Beta Control:** `-42.17 bps`

## 2. Post-Shock Liquidity Recovery, Blind-Scanner Cadence Miss & Conditional-on-Fill Adverse Selection
- **Liquidity Recovery Events:** `3` (full) vs `1` (`3x` thinned → **`66.7%` missed**) · **Mean Net Edge:** `-27.05 bps`
- **Conditional Passive Fill Markout:** Fast (`<=60s`): **`+0.00 bps`** · Slow (`>60s`): **`-12.82 bps`** · Unfilled Missed Drift: `+16.93 bps`

## 3. Delisting Stress, 5-Day Outage Restart Policies, TMN Liability & Shared-Rail Stress
- **Clean Slow Core:** `+152.24%` · **SOL Delist (50% rec):** `+156.63%` · **SOL Delist (0% rec):** `+156.63%`
- **5-Day Outage Recovery:** `RECOMPUTE=+151.95%` · `DISCARD_EXPIRED=+151.15%` · `REPLAY_STALE=+151.75%`
- **Scheduled 20M TMN Withdrawal (500 bps FX Spike):** Ending `1905.04M TMN` (extra FX spike cost `$21.30` USDT)
- **Shared Operational Dependency Stress:** `{'NOBITEX_OFFLINE_STRANDED_PCT': 50.0, 'USDT_5PCT_DEPEG_LOSS_USDT': 40.0, 'XAUT_ISSUER_FREEZE_STRANDED_PCT': 20.0, 'DUAL_NOBITEX_PLUS_XAUT_STRANDED_PCT': 60.0}`

## 4. Order Timeout → Replacement Partial → Late Original Fill Reconciliation
- **Reconciled State:** `cash=$859.58`, `units=1.4`, `fees=$0.2243`, `overfilled_orders=True`, `filled_by_order={'ord_1': 1.0, 'ord_2': 0.4}`
