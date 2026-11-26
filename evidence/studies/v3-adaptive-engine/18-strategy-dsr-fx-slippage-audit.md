# 18-Strategy DSR, Dual-Factor FX, Empirical Slippage & ML Shadow Audit

- **Generated (UTC):** `2026-11-26T18:35:38.145968+00:00`
- **Mode:** `PAPER_ONLY` (`TradingGYMExecutor` remains `DISARMED` / `$0`)
- **Strategies Audited:** `18` across `2577` daily bars

## 1. 18-Strategy Deflated Sharpe Ratio (N=18) & Leave-K-Out Fragility

| Strategy | Signals | Episodes | Ann Sharpe | DSR (N=18) | LKO K=0 (bps) | LKO K=1 (bps) | Tier |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `ema-trend` | 104 | 52 | 1.214 | 0.7253 | 820.8 | 440.3 | `SHADOW_CANDIDATE` |
| `donchian-breakout` | 66 | 33 | 1.171 | 0.6859 | 1609.4 | 450.3 | `SHADOW_CANDIDATE` |
| `slow-s1-trend` | 110 | 55 | 1.166 | 0.6815 | 908.0 | 204.9 | `PROMOTE_REFERENCE` |
| `macd-cross` | 144 | 72 | 1.027 | 0.5402 | 345.0 | 269.7 | `SHADOW_CANDIDATE` |
| `trix-cross` | 78 | 39 | 0.951 | 0.4603 | 587.3 | 449.4 | `RETIRE_FAIL_DSR` |
| `sma-cross` | 126 | 63 | 0.777 | 0.2867 | 469.8 | 161.8 | `RETIRE_FAIL_DSR` |
| `keltner-breakout` | 34 | 17 | 0.647 | 0.1820 | 684.0 | 463.0 | `RETIRE_FAIL_DSR` |
| `signal-blend` | 60 | 30 | 0.470 | 0.0841 | 297.8 | 165.5 | `RETIRE_FAIL_DSR` |
| `rsi-rebound` | 18 | 9 | 0.112 | 0.0100 | 133.7 | -266.4 | `RETIRE_FAIL_DSR` |
| `sma-reversion` | 251 | 126 | 0.085 | 0.0082 | -25.6 | -34.2 | `RETIRE_FAIL_DSR` |
| `toman-premium` | 0 | 0 | 0.000 | 0.0043 | 0.0 | 0.0 | `HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY` |
| `lead-lag` | 0 | 0 | 0.000 | 0.0043 | 0.0 | 0.0 | `HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY` |
| `ema-confirmed` | 0 | 0 | 0.000 | 0.0043 | 0.0 | 0.0 | `HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY` |
| `relative-momentum` | 0 | 0 | 0.000 | 0.0043 | 0.0 | 0.0 | `HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY` |
| `trend-pullback` | 0 | 0 | 0.000 | 0.0043 | 0.0 | 0.0 | `HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY` |
| `adaptive-channel` | 0 | 0 | 0.000 | 0.0043 | 0.0 | 0.0 | `HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY` |
| `compression-breakout` | 0 | 0 | 0.000 | 0.0043 | 0.0 | 0.0 | `HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY` |
| `bollinger-reversion` | 81 | 41 | -0.007 | 0.0041 | -66.8 | -116.1 | `RETIRE_FAIL_DSR` |

## 2. USD/USDT vs. IRR Dual-Factor Attribution

- **Status:** `OK` | **Consensus Kalman USDT/TMN:** `297832.011`
- **Window:** `2019-10-16` → `2026-11-18` (2567 days) | **Global Crypto:** `2.0531` | **FX Devaluation:** `3.1499` | **Venue Basis:** `0.0208` | **Ending Basis:** `-60.7 bps`

## 3. Empirical Slippage & 1.5× Implementation-Shortfall Calibration

- **Instrument:** `wallex:BTCUSDT` | **Quotes Scanned:** `50000` | **Tehran Hours Covered:** `24`

## 4. ML Lifecycle & Shadow Readiness

- **Status:** `NO_SHADOW_ARTIFACT` | **Permitted Weight:** `0.0` | **Engine Digest:** `9806035feb9a0dd4`
