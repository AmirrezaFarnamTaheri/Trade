# Post-Repair Signal & Model Diagnostics Study (Menu Ideas 2, 3, 4, 5, and 15)

- **Generated:** `2026-11-25T20:54:00.712471+00:00` · **Executor:** `DISARMED` (`$0` funded budget)

## Idea 2 — Sleeve Disagreement (Immediate Netting vs. 1-Bar Residual Delay)
- **Opposite-Signed Events (Slow Sell vs Fast Buy):** `5` · **Netted Notional:** `$67.50` · **Immediate Netting Fee Savings:** `$0.22`
- **1-Bar Residual Delay Price Saving:** `-254.62 bps` · **24h Relinquishing-Sleeve Opp. Cost:** `-261.51 bps`

## Idea 3 — Cheap Static BTC/XAUT/USDT Replica Benchmark (OOS `>= 2025-11-24`)
- **Dev-Fitted Static Replica Weights:** `{'BTCUSDT': 0.3068, 'XAUTUSDT': 0.1057, 'USDT_CASH': 0.5875}`
- **Slow `S1+S5` OOS:** Ret `-2.27%`, Sharpe `-0.122`, MaxDD `11.00%`
- **Cheap Replica OOS:** Ret `-9.46%`, Sharpe `-0.636`, MaxDD `14.36%`
- **OOS Residual Alpha vs Replica:** `+7.19%` · **MaxDD Diff:** `-3.36%`

## Idea 4 — Event-Clustered Episode Leave-One-Out Concentration (`<=6h` Clusters)
- **Raw Entries:** `921` → **Clustered Episodes:** `352` (`311` independent entry days)
- **Total Net Path P&L:** `+130.15` pct-pts · **Top-1 Episode:** `+95.74` · **Top-3 Share:** `201.3%` · **P&L Without Top-3:** `-131.85`

## Idea 5 — Narrow ML Job (Execute-Now vs. Wait-1-Bar Only, OOS `>= 2025-11-24`)
- **OOS Orders:** `414` · **Always Now:** `+0.00 bps` · **Always Wait 1b:** `+2.63 bps`
- **Simple Range Threshold:** `+3.82 bps` · **ML Wait Gate:** `+2.22 bps` (`wait_rate=3.4%`)

## Idea 15 — Shallow Depth-3 Tree Distillation of Frozen GRU & Disagreement Pricing
- **OOS Samples:** `782` · **Agreement Rate:** `73.7%` · **Disagreements:** `206`
- **Both Top-Tercile:** `+174.19 bps` · **GRU-Only Top (`N=111`):** `+19.60 bps` · **Tree-Only Top (`N=95`):** `+16.51 bps`
- **GRU Minus Shallow Tree on Disagreements:** `+3.09 bps`
