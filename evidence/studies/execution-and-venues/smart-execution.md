# Side-Asymmetric Smart Execution Audit (Walked L2 Depth + Live Passive BUY Fill Check)

- **Generated:** `2026-11-24T21:05:00.674519+00:00`
- **Order Size Evaluated:** `$250` USDT per leg (walking up to 5 displayed book levels)
- **Policy:** `SIDE_ASYMMETRIC_ROUTER` posts passive limit `BUY` at Nobitex best bid (300s causal live-book fill check, fallback to `SMART_TAKER_ROUTER`), and sweeps immediately on `SELL` via `SMART_TAKER_ROUTER`.

| Symbol | Samples | Side | Wallex Taker (bps) | Nobitex Taker (bps) | Smart Taker (bps) | Asym Router (bps) | Saving vs Wallex | Nobitex Cheaper% | WLX/NBX 5L Fill% | Passive BUY Fill% |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| `BTCUSDT` | `709` | `BUY` | `+20.25` | `+17.40` | `+14.71` | `+10.32` | `+9.93 bps` | `59.8%` | `100% / 99%` | `45.7%` |
| `BTCUSDT` | `709` | `SELL` | `+22.84` | `+15.72` | `+14.72` | `+14.72` | `+8.12 bps` | `77.3%` | `100% / 99%` | `0.0%` |
| `ETHUSDT` | `709` | `BUY` | `+24.59` | `+18.10` | `+16.77` | `+14.09` | `+10.50 bps` | `73.1%` | `100% / 98%` | `37.1%` |
| `ETHUSDT` | `709` | `SELL` | `+25.64` | `+17.48` | `+16.61` | `+16.61` | `+9.03 bps` | `83.1%` | `100% / 98%` | `0.0%` |
| `SOLUSDT` | `666` | `BUY` | `+38.27` | `+29.79` | `+23.29` | `+16.57` | `+21.70 bps` | `60.2%` | `96% / 90%` | `36.6%` |
| `SOLUSDT` | `666` | `SELL` | `+43.76` | `+22.04` | `+21.84` | `+21.84` | `+21.92 bps` | `95.6%` | `99% / 99%` | `0.0%` |
| `XRPUSDT` | `714` | `BUY` | `+27.02` | `+20.48` | `+19.03` | `+16.78` | `+10.25 bps` | `74.9%` | `100% / 98%` | `31.1%` |
| `XRPUSDT` | `714` | `SELL` | `+29.46` | `+19.35` | `+19.08` | `+19.08` | `+10.39 bps` | `87.1%` | `100% / 97%` | `0.0%` |
