# Multi-Horizon Adaptive Engine (Findings F1–F6) — Incremental Ablation & Live Venue Audit

- **Generated:** `2026-11-25T14:28:08.211598+00:00` · **Executor:** `DISARMED` (`PAPER_ONLY`)
- **Frozen v2 Champion Reference:** NAV `$1292.84` (`+29.28%`), Bear `+4.49%`, Sharpe `0.849`, MaxDD `6.44%`, Fees `$83.89`
- **Best Adaptive Arm:** `WINNERS_ONLY_F1_F2CLOCK_F4_5X` — NAV `$1385.03` (`+38.50%`), Bear `-2.34%`, Sharpe `0.952` (`0h=0.611` / `1h=0.996`), MaxDD `10.32%`, Liqs `0`, vs v2 `+0.68 bps/d` `[-1.47, +2.91]`

## 1. Incremental Ablation Stack (F1 → F6, `1,085d` `2024–2026`, Twin `0h + 1h` Phase)

| Arm | Ending NAV | Full Ret | Bear Stress | Sharpe (`0h`/`1h`) | MaxDD | Liqs | MaxLev | Fees / Borrow / Pool ($) | OCO / ML-Exit / Pyr / IntSh / RV | vs v2 (bps/d, 95% CI) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `F1_LOT_BOOK_TRUE_MARGIN_5X` | `$1338.53` | `+33.85%` | `-5.97%` | `0.874` (`0.487`/`1.000`) | `10.94%` | `0` | `5.0×` | `$174.5 / $7.2 / +$80.2` | `0 / 0 / 0 / 0 / 0` | `+0.35` `[-1.85, +2.57]` |
| `F1_F3_ONLINE_IC_ZERO_BUCKET_5X` | `$1262.17` | `+26.22%` | `-8.19%` | `0.754` (`0.247`/`1.000`) | `11.75%` | `0` | `5.0×` | `$182.9 / $6.8 / +$81.2` | `0 / 0 / 0 / 0 / 0` | `-0.21` `[-2.39, +2.23]` |
| `F1_F3_F2_TEHRAN_CLOCK_OCO_5X` | `$1196.81` | `+19.68%` | `-5.72%` | `0.755` (`0.450`/`1.172`) | `10.07%` | `0` | `5.0×` | `$156.2 / $4.7 / +$78.4` | `67 / 0 / 0 / 0 / 0` | `-0.78` `[-2.69, +1.05]` |
| `F1_F3_F2_F4_ML_EXIT_PYRAMID_5X` | `$1206.27` | `+20.63%` | `-4.97%` | `0.788` (`0.489`/`1.173`) | `9.30%` | `0` | `5.0×` | `$157.2 / $4.6 / +$78.5` | `66 / 5 / 2 / 0 / 0` | `-0.70` `[-2.60, +1.04]` |
| `F1_TO_F6_FULL_WITH_RV_HEDGE_5X` | `$1200.31` | `+20.03%` | `-5.30%` | `0.771` (`0.466`/`1.171`) | `9.29%` | `0` | `5.0×` | `$161.7 / $5.3 / +$78.4` | `66 / 5 / 2 / 0 / 10` | `-0.75` `[-2.62, +1.01]` |
| `F1_TO_F6_FULL_WITH_RV_HEDGE_2X` | `$1163.37` | `+16.34%` | `-5.24%` | `0.687` (`0.448`/`1.043`) | `9.38%` | `0` | `2.0×` | `$142.8 / $3.4 / +$77.1` | `66 / 5 / 2 / 0 / 10` | `-1.05` `[-2.84, +0.62]` |
| `WINNERS_ONLY_F1_F2CLOCK_F4_5X` | `$1385.03` | `+38.50%` | `-2.34%` | `0.952` (`0.611`/`0.996`) | `10.32%` | `0` | `5.0×` | `$175.5 / $7.7 / +$80.2` | `0 / 5 / 5 / 0 / 0` | `+0.68` `[-1.47, +2.91]` |

## 2. Live Iranian Venue Audits (F2 Tehran Clock & F5 Synthetic TMN Triangles + Borrow Currency)

- **Live Tehran Liquidity Clock (`book_top`):** Tightest hour = `UTC 5h` (`08:30 Tehran`, `34.47 bps`) vs. Widest hour = `UTC 3h` (`06:30 Tehran`, `44.6 bps`).
- **Dynamic Borrow Currency (`USDTTMN`, `1740` days):** `TMN` debt strictly cheaper than `USDT` debt on **`1081` days (`62.1%`)** with mean net carry advantage **`+17.86 bps/day`** during confirmed USDTTMN uptrends.

| Triangle Pair | Matched Mins | Synthetic TMN BUY Win% (Avg Save) | Synthetic TMN SELL Win% (Avg Save) |
| --- | ---: | ---: | ---: |
| `BTCUSDT` | `1961` | `12.6%` (`+83.59 bps`) | `10.56%` (`+21.91 bps`) |
| `ETHUSDT` | `1964` | `0.56%` (`+25.43 bps`) | `1.12%` (`+12.12 bps`) |
| `SOLUSDT` | `1960` | `11.63%` (`+77.33 bps`) | `21.02%` (`+39.91 bps`) |
| `XRPUSDT` | `1965` | `1.32%` (`+27.67 bps`) | `1.27%` (`+13.6 bps`) |
| `XAUTUSDT` | `1958` | `7.46%` (`+20.25 bps`) | `7.3%` (`+16.73 bps`) |
| `PEPEUSDT` | `1959` | `6.18%` (`+20.7 bps`) | `13.68%` (`+14.8 bps`) |
