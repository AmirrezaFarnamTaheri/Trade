# Bellman Optimal-Stopping V2 & Defeated-Strategy Resurrection Study

- **Generated:** `2026-11-25T14:57:23.316836+00:00` · **Executor:** `DISARMED` (`PAPER_ONLY`)
- **Frozen v2 Reference:** NAV `$1292.84` (`+29.28%`), Bear `+4.49%`, Sharpe `0.849`, MaxDD `6.44%`
- **New Standing Best Arm:** `E3_V2_NONLINEAR_BELLMAN` — NAV `$1429.83` (`+42.98%`), Bear `+2.18%`, Sharpe `1.090` (`0h=0.676`/`1h=1.170`), MaxDD `8.17%`, Liqs `0`

## Part 1 & 3 — Bellman V2 Upgrades & Unified Portfolio Integration (`1,085d`, Twin `0h + 1h`)

| Arm | Ending NAV | Full Ret | Bear Stress | Sharpe (`0h`/`1h`) | MaxDD | Liqs | Borrow / Pool ($) | ML-Exit / Pyr / SlowBM / Extra | vs E3v1 / vs v2 (bps/d) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `E3_V1_RIDGE_REF` | `$1428.39` | `+42.84%` | `+2.08%` | `1.067` (`0.678`/`1.142`) | `9.13%` | `0` | `$8.28 / +$80.13` | `28 / 8 / 0 / 0` | `+0.00` / `+0.95` |
| `E3_V2_NONLINEAR_BELLMAN` | `$1429.83` | `+42.98%` | `+2.18%` | `1.090` (`0.676`/`1.170`) | `8.17%` | `0` | `$8.09 / +$80.29` | `30 / 10 / 0 / 0` | `+0.00` / `+0.95` |
| `E3_V2_PLUS_SLOW_1D_BELLMAN` | `$1405.64` | `+40.56%` | `+0.83%` | `1.046` (`0.610`/`1.170`) | `8.10%` | `0` | `$8.29 / +$80.28` | `30 / 10 / 26 / 0` | `-0.16` / `+0.79` |
| `E3_V2_PLUS_EARLY_IGNITION_Z15` | `$955.81` | `-4.42%` | `-7.95%` | `-0.092` (`0.126`/`-0.530`) | `12.48%` | `0` | `$2.82 / +$66.61` | `413 / 14 / 0 / 500` | `-3.75` / `-2.80` |

## Part 2 — Previously Defeated Entry Families: Static Exit vs. Bellman Optimal Closing (`2024-09..2026-11` OOS)

| Defeated Family | Static Ret / Bear / Sharpe / DD | Bellman Ret / Bear / Sharpe / DD | Sharpe Delta | Giveback (Static → Bellman) | Pre-EOD 0% Brw | Resurrected? |
| --- | --- | --- | ---: | --- | ---: | --- |
| `flush_rebound` | `-43.0%` / `-14.0%` / `-1.728` / `47.7%` | `-32.4%` / `-8.1%` / `-2.002` / `36.7%` | `-0.274` | `228 → 110 bps` | `81.3%` | `NO` |
| `breakdown_short` | `-48.1%` / `-40.9%` / `-1.544` / `54.2%` | `-49.3%` / `-37.7%` / `-2.195` / `52.4%` | `-0.651` | `266 → 135 bps` | `79.6%` | `NO` |
| `early_ignition_z15` | `-43.7%` / `-34.8%` / `-0.850` / `46.0%` | `-51.5%` / `-27.8%` / `-3.002` / `51.8%` | `-2.152` | `252 → 109 bps` | `80.4%` | `NO` |
