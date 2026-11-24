# Instant Zero-Wait Gate Verification Packet

**Evaluated (UTC):** `2026-11-24T08:58:16.538264+00:00` · **Mode:** Instant Historical Holdout + Live Probe (zero calendar waiting) · **Executor:** `DISARMED` (`$0` funded budget).

## Gate Summary

| Gate | Instant Counterpart | Status | Key Evidence |
| --- | --- | --- | --- |
| **G1-Instant** | Live collector `/api/health` + L2 depth5 + Nobitex live recorder | **PASS** | `connected=True`, `40` markets / `2` shards, `lag=0.0s`, `depth5=105902`, `nobitex=125` |
| **G2-Instant** | Multi-year Dev vs 365-day Sealed Holdout + CPCV/PBO + 500-Run Placebo + DSR (`N=21`) | **PASS** | Candidate A pass=`True`, Candidate B pass=`False` |
| **G3-Instant** | Safety/authority boundaries & `DISARMED` invariant | **PASS** | Verified by pytest safety suite (`41 passed`, `0` drift) |
| **G4** | Explicit owner sign-off | **OPEN** | Never auto-armed |

## Candidate A — Instant 22-Month Hourly 6-Triangle FX Basis

- **Aligned Hours:** `16439` · **Dev Trades:** `2226` · **Holdout Trades:** `2726` · **Holdout Placebo p:** `0.002`
- **Dev (`<= 2025-11-23`):** Wallex Maker `37055.66 bps`, Ann. Sharpe `10.958`, DSR `1.0`
- **Sealed Holdout (`>= 2025-11-24`):** Wallex Maker `55464.67 bps`, Nobitex `-30%` Maker `71820.67 bps`, Ann. Sharpe `13.266`, DSR `1.0`

## Candidate B — Instant 4-Year Convex L1 Allocation (365-Day Sealed Holdout + Purged CPCV/PBO)

- **Causality:** `True` · **Purged CPCV PBO:** `0.5333` · **500-Run Placebo p:** `0.3952`

| Split | Days | Ann. Sharpe | DSR (`N=21`) | Return (%) | MaxDD (%) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dev (`<= 2025-11-23`) | 1281 | 0.887 | 0.397 | 85.02% | 19.45% |
| **Sealed Holdout (`365d`)** | 365 | -0.196 | 0.0171 | -2.19% | 7.71% |
| Full (`4yr`) | 1646 | 0.745 | 0.367 | 80.98% | 19.45% |
