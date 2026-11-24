# Track III Ablations — Lead-Lag Diffusion, Single-ADMM Cross-Sleeve Netting & Live Venue Dislocation Rebates

- **Generated:** `2026-11-24T22:38:35.295314+00:00`

## Idea #5 — Cross-Sectional BTC/ETH Lead-Lag Diffusion Sleeve (2h Bars)

| Arm | Offset | Cost | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries | Win% | Avg Hold | Corr vs Base |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `IDEA_5_DIFFUSION_NBX16_OFF0H` | `+0h` | `16.0bp` | `$837.36` | `-16.26%` | `-0.34%` | `-1.005` | `16.75%` | `89` | `46.1%` | `9.7h` | `+0.016` |
| `IDEA_5_DIFFUSION_WLX25_OFF0H` | `+0h` | `25.0bp` | `$797.95` | `-20.21%` | `-1.52%` | `-1.264` | `20.21%` | `89` | `44.9%` | `9.7h` | `+0.015` |
| `IDEA_5_DIFFUSION_NBX16_OFF1H` | `+1h` | `16.0bp` | `$1006.93` | `+0.69%` | `-1.91%` | `0.069` | `6.86%` | `84` | `52.4%` | `9.5h` | `+0.022` |
| `IDEA_5_DIFFUSION_WLX25_OFF1H` | `+1h` | `25.0bp` | `$962.17` | `-3.78%` | `-3.38%` | `-0.197` | `7.93%` | `84` | `48.8%` | `9.5h` | `+0.021` |

## Idea #9 — Joint Single-ADMM Cross-Sleeve Netting & Sector Cluster Caps vs. Post-Hoc 70/30 Blend

| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fills | Fees ($) | Turnover | vs Post-Hoc (bps/d, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BENCH_POSTHOC_70_30_NBX16` | `$1240.45` | `+24.04%` | `+2.06%` | `0.650` | `8.54%` | `964` | `$74.65` | `46.7x` | `+0.00 [+0.00, +0.00]` |
| `IDEA_9_JOINT_ADMM_NETTED_NBX16` | `$1258.06` | `+25.81%` | `+2.22%` | `0.685` | `8.63%` | `882` | `$72.66` | `45.4x` | `+0.13 [-0.18, +0.44]` |
| `BENCH_POSTHOC_70_30_WLX25` | `$1197.02` | `+19.70%` | `+0.74%` | `0.554` | `8.60%` | `957` | `$114.34` | `45.7x` | `+0.00 [+0.00, +0.00]` |
| `IDEA_9_JOINT_ADMM_NETTED_WLX25` | `$1205.96` | `+20.60%` | `+1.14%` | `0.582` | `8.59%` | `755` | `$105.25` | `42.1x` | `+0.06 [-0.48, +0.61]` |

## Idea #6 — Live Nobitex <-> Wallex Fair-Value Entry Guard & Exit Rebate Audit (`multi_venue_quotes.sqlite3`)

| Symbol | Matched Live Pairs | Entry Guard >=15bp (%) | Med Entry Gap (bps) | Exit Rebate >=15bp (%) | Med Exit Rebate (bps) | Mean Exit Rebate (bps) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `AAVEUSDT` | `57` | `38.6%` | `8.57` | `45.6%` | `9.63` | `21.53` |
| `ADAUSDT` | `61` | `1.6%` | `6.92` | `95.1%` | `34.63` | `31.38` |
| `BCHUSDT` | `60` | `53.3%` | `17.05` | `45.0%` | `13.25` | `13.46` |
| `BNBUSDT` | `60` | `13.3%` | `3.38` | `11.7%` | `4.81` | `7.39` |
| `BTCUSDT` | `769` | `11.2%` | `6.59` | `13.4%` | `6.51` | `8.12` |
| `DOGEUSDT` | `59` | `25.4%` | `5.43` | `15.3%` | `9.31` | `10.00` |
| `ETHUSDT` | `770` | `11.3%` | `6.98` | `14.5%` | `6.97` | `8.71` |
| `FILUSDT` | `30` | `100.0%` | `582.52` | `100.0%` | `52.72` | `95.25` |
| `LINKUSDT` | `59` | `6.8%` | `6.11` | `74.6%` | `18.71` | `21.39` |
| `LTCUSDT` | `62` | `66.1%` | `29.43` | `38.7%` | `12.25` | `22.74` |
| `SOLUSDT` | `729` | `53.5%` | `16.24` | `50.1%` | `15.05` | `18.50` |
| `TRXUSDT` | `50` | `30.0%` | `11.99` | `16.0%` | `2.92` | `6.66` |
| `UNIUSDT` | `62` | `9.7%` | `3.84` | `38.7%` | `12.20` | `58.09` |
| `XAUTUSDT` | `47` | `63.8%` | `21.01` | `34.0%` | `11.28` | `14.28` |
| `XRPUSDT` | `775` | `22.3%` | `7.26` | `24.3%` | `8.10` | `11.13` |
