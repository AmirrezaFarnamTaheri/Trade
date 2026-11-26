# Instant Zero-Wait Gate Verification Packet (Caveats Resolved)

**Evaluated (UTC):** `2026-11-24T09:01:54.333484+00:00` · **Mode:** Strictly Causal Next-Bar Open + Real Order-Book Adversarial Replay · **Executor:** `DISARMED` (`$0` funded budget).

## Gate Summary

| Gate | Instant Counterpart | Status | Key Evidence |
| --- | --- | --- | --- |
| **G1-Instant** | Live `/api/health` + L2 depth5 + Nobitex recorder | **PASS** | `connected=True`, `40` mkts / `2` shards, `lag=0.1s`, `depth5=106558`, `nobitex=140` |
| **G2-Instant** | Causal next-bar holdout + real order-book `adversarial_lower_bound` + CPCV/PBO + Placebo + DSR | **NOT_MET** | Cand. A hourly=`False`, orderbook=`False`; Cand. B=`False` |
| **G3-Instant** | Safety/authority boundaries & `DISARMED` invariant | **PASS** | Verified by pytest safety suite (`41 passed`, `0` drift) |
| **G4** | Explicit owner sign-off | **OPEN** | Never auto-armed |

## Candidate A — Dual Check (Causal Next-Bar Hourly + Tick-Level Order-Book Adversarial)

### A1. 22-Month Causal Next-Bar Open Hourly Replay (Fees & Spread Deducted Inside Sharpe/DSR)

- **Aligned Hours:** `16439` · **Dev Trades:** `2226` · **Holdout Trades:** `2726` · **Holdout Placebo p:** `0.9581`
- **Dev (`<= 2025-11-23`):** Wallex Net `-49027.52 bps`, Ann. Sharpe `-10.064`, DSR `0.0`
- **Sealed Holdout (`>= 2025-11-24`):** Wallex Net `-54773.38 bps`, Nobitex `-30%` Net `-27513.38 bps`, Ann. Sharpe `-12.178`, DSR `0.0`

### A2. Real Order-Book + Trades Replay (`duplicate_print_mode='adversarial_lower_bound'`, `post_only=True`)

- **Lookback:** `72h` · **Signals:** `1` · **Filled Entries:** `0` · **5m Markout Cov.:** `0.0`
- **Net Proceeds After Compulsory Unwind (USDT):** **`0.0`** · **Order-Book Pass:** **`False`**

## Candidate B — 4-Year Convex L1 Allocation (365-Day Sealed Holdout + Purged CPCV/PBO)

- **Causality:** `True` · **Purged CPCV PBO:** `0.5333` · **500-Run Placebo p:** `0.3952`

| Split | Days | Ann. Sharpe | DSR (`N=21`) | Return (%) | MaxDD (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dev (`<= 2025-11-23`) | 1281 | 0.887 | 0.397 | 85.02% | 19.45% |
| **Sealed Holdout (`365d`)** | 365 | -0.196 | 0.0171 | -2.19% | 7.71% |
| Full (`4yr`) | 1646 | 0.745 | 0.367 | 80.98% | 19.45% |
