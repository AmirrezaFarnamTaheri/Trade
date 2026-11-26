# Post-Repair Microstructure & Treasury Study — Signal Expiry (Idea 1), Cash Option Value (Idea 6), Feed Ablation (Idea 11) & Dual-Clock Readiness

- **Generated:** `2026-11-25T20:31:11.142935+00:00` · **Executor:** `DISARMED` (`$0` funded budget)
- **Engine:** Strictly post-repair zero-lookahead causal open execution & exact equity conservation.

## Part 1 — Idea 1: Signal Expiry Time (Delay = 0, 1, 2, 4 Bars)

### Slow 1d Trend (`BASE_13` S1+S5)
| Delay (bars / h) | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `0d (0h)` | `$2522.43` | `+152.28%` | `0.993` | `22.35%` | `1889` | `$79.23` |
| `1d (24h)` | `$2357.64` | `+135.76%` | `0.926` | `22.78%` | `2606` | `$87.70` |
| `2d (48h)` | `$2418.68` | `+141.87%` | `0.950` | `23.57%` | `2748` | `$91.76` |
| `4d (96h)` | `$2586.96` | `+158.70%` | `1.007` | `21.53%` | `2826` | `$98.05` |

### Fast 2h Ignition (`IGNITION_18_CRYPTO`, Fixed Original Exit Deadline)
| Delay (bars / h) | Ending NAV | Return | Ann. Sharpe | MaxDD | Entries | Missed/Expired | Win% | Fees ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `0b (0h)` | `$1160.43` | `+16.04%` | `0.426` | `16.41%` | `181` | `47` | `37.0%` | `$192.85` |
| `1b (2h)` | `$1017.48` | `+1.75%` | `0.111` | `18.75%` | `184` | `42` | `35.9%` | `$191.42` |
| `2b (4h)` | `$920.85` | `-7.91%` | `-0.128` | `21.68%` | `185` | `43` | `35.1%` | `$188.30` |
| `4b (8h)` | `$1071.85` | `+7.18%` | `0.241` | `17.02%` | `182` | `45` | `39.0%` | `$196.46` |

## Part 2 — Idea 6: Pricing the Option to Hold Idle Cash (Slow Spot vs. Fast 2h Ignition)

| Policy | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Ign Exec | Ign Blocked | Blocked 24h Net | Avg Idle Cash | Fees ($) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `RESERVE_0PCT` | `$1154.34` | `+15.43%` | `-3.84%` | `0.381` | `10.93%` | `167` | `15` | `+1.556%` | `73.0%` | `$82.86` |
| `RESERVE_10PCT` | `$1158.23` | `+15.82%` | `-3.54%` | `0.407` | `10.25%` | `171` | `8` | `+1.850%` | `75.5%` | `$82.29` |
| `RESERVE_20PCT` | `$1148.98` | `+14.90%` | `-3.21%` | `0.413` | `9.57%` | `174` | `2` | `-0.185%` | `78.0%` | `$80.51` |
| `RESERVE_30PCT` | `$1142.59` | `+14.26%` | `-2.85%` | `0.429` | `8.75%` | `175` | `0` | `+0.000%` | `80.6%` | `$78.09` |
| `ADAPTIVE_ARRIVAL_RESERVE` | `$1161.62` | `+16.16%` | `-3.74%` | `0.408` | `10.44%` | `171` | `8` | `+1.850%` | `74.7%` | `$83.22` |
| `SEPARATE_ACCOUNTS_70_30` | `$1126.50` | `+12.65%` | `-2.84%` | `0.409` | `8.10%` | `175` | `0` | `+0.000%` | `81.5%` | `$68.05` |

## Part 3 — Idea 11: Data-Feed Value Ablation (Mask L2-L5 & Thin Snapshots on Live Matched Books)

| Notional | Feed Arm | Symbols | Samples | Med Smart Taker | Med Asym Router | Passive BUY Fill% | NBX Depth Fill% | WLX Depth Fill% | NBX Cheaper% |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `$250` | `FULL_L5_1X` | `15` | `9738` | `+27.19bp` | `+25.66bp` | `17.3%` | `98.2%` | `92.7%` | `84.5%` |
| `$250` | `MASK_L2_L5_L1_ONLY` | `15` | `9738` | `+36.70bp` | `+34.92bp` | `17.3%` | `46.5%` | `46.6%` | `76.7%` |
| `$250` | `THIN_SNAPSHOTS_2X` | `15` | `4873` | `+27.17bp` | `+27.52bp` | `13.9%` | `98.0%` | `92.6%` | `84.6%` |
| `$250` | `THIN_SNAPSHOTS_5X` | `15` | `1953` | `+27.11bp` | `+29.05bp` | `0.0%` | `98.1%` | `92.6%` | `84.1%` |
| `$1000` | `FULL_L5_1X` | `15` | `9738` | `+33.78bp` | `+35.28bp` | `17.3%` | `86.6%` | `76.0%` | `85.1%` |
| `$1000` | `MASK_L2_L5_L1_ONLY` | `15` | `9738` | `+43.92bp` | `+41.78bp` | `17.3%` | `23.6%` | `18.4%` | `81.3%` |
| `$1000` | `THIN_SNAPSHOTS_2X` | `15` | `4873` | `+32.79bp` | `+35.66bp` | `13.9%` | `86.5%` | `75.8%` | `85.8%` |
| `$1000` | `THIN_SNAPSHOTS_5X` | `15` | `1953` | `+34.89bp` | `+34.50bp` | `0.0%` | `86.5%` | `75.4%` | `85.2%` |

## Part 4 — Dual-Clock Readiness Audit (Ideas 7 + 12: Venue Price Discovery + Prefunding)

- **`venue_quotes` columns:** `['id', 'venue', 'symbol', 'ts_avail', 'bid', 'ask', 'bid_qty', 'ask_qty', 'spread_bps', 'depth_json']`
- **Exchange event clock (`ts_event`) present:** `False` · **Local receipt clock (`ts_avail`) present:** `True`
- **`nobitex`:** `15,089` quotes (`2026-11-24T08:27:55.774044Z` -> `2026-11-25T20:30:00.383058Z`)
