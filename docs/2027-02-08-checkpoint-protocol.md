# 2027-02-08 Funded-Path Checkpoint Protocol

**Status:** Frozen pre-committed decision gate (task `G006`, implementing [PRODUCT.md](../PRODUCT.md#L41-L54) and [ADR 0006](adr/0006-arming-and-fail-closed-custody.md))  
**Committed date:** 2026-11-21 · **Pinned baseline:** `8fba0b15115b617067fc93b9c9769c9351472900`  
**Review date:** 2027-02-08 (UTC) · **Authority:** Decision gate only — never an arming signal.

## 1. Stop rule (pre-committed, non-negotiable)

On **2027-02-08**, funded-execution work **pauses** and TradingGYM remains a research-only observatory if **any** of the following conditions fails. No parameter, threshold, denominator, or date window may be relaxed after observing outcomes.

| Gate | Requirement | Exact denominator and measurement | Fail outcome |
| --- | --- | --- | --- |
| **G1 — 30-day feed reliability** | `gymctl doctor` / collector-feed health fails on **<= 10%** of days (at most 3 of 30 UTC days) **and** maximum raw archive gap is **<= 24.0 hours** | 30 full UTC calendar days: **`2027-01-09T00:00:00Z` to `2027-02-08T00:00:00Z`**. Measured from `data/live/market.db` (`segments`, `book_top`, `quality_events`) and dated `gymctl doctor` receipts. Unclosed crash tails and missing UTC days count as gaps. | Pause funded path |
| **G2 — Independently validated net edge** | **Original v1 (2026-11-21, `8fba0b1`):** At least one preregistered strategy passes validation **and** an independently consumed holdout (`gymctl research final-run` / independent custodian release) with **Deflated Sharpe Probability >= 0.95** after modeled executable costs.<br>**Amended v2 (2026-11-24, owner-directed):** Clears **either Track A (High-N Active / Structural Edge)** — validation + independently consumed holdout (`gymctl research final-run` / custodian release) with **DSR >= 0.95** (and optional sequential `e-process` only where pre-run power simulation confirms `>= 80%` power at the declared per-step loss floor) — **or Track B (Slow Macro / Multi-Asset Allocation)** — multi-year/multi-asset out-of-sample **DSR >= 0.95** plus a completed **90-day live-paper implementation-shortfall audit** (`earliest_release >= start + 90d`). Cohorts younger than 90 days on `2027-02-08` report `IMMATURE_AT_CHECKPOINT`. The `2027-02-08` review receipt reports outcomes against **both v1 and v2**. | Exact candidate family count across all attempts (`trial_ledger.sqlite3`, `gym-core/docs/trial-log.md`, `holdout_ledger`). Background forward monitors (`funding-confirmed-trend-forward`, `breadth-trend-forward`) stay counted in the multiplicity denominator without blocking the two active hypothesis slots. Must satisfy the executable-net gate ([evidence-and-sampling-contract.md](../gym-core/docs/evidence-and-sampling-contract.md)) — exact Wallex Level-1 published fees (TMN 0.25% maker / 0.30% taker; USDT 0.10% maker / 0.13% taker) or dated account receipts; never zero cost unless explicit `is_zero_fee`. | Pause funded path |
| **G3 — Authority & admission checks** | Automated authority/admission checks ([ADR 0006](adr/0006-arming-and-fail-closed-custody.md), [ADR 0007](adr/0007-wiring-the-funded-path-behind-an-arm-button.md), [ADR 0008](adr/0008-balance-observation-ordering.md)) pass on the exact pinned commit | CI + local pinned `cargo test --locked --workspace --all-targets` and `./tasks.ps1 rust python browser`, zero silent authority drift, `DISARMED` startup invariant intact. | Pause funded path |
| **G4 — Explicit owner sign-off** | Written owner go/no-go decision recorded under `evidence/` | Requires signed decision record referencing the exact G1, G2, G3 receipts. | Default **NO-GO** |

## 2. Explicit non-arming boundary (`G005`)

- Passing the 2027-02-08 checkpoint authorizes **only** entering Stage 6 (published signed bundle + installed-host qualification, tasks `H001–H029`).
- Passing does **not** arm `TradingGYMExecutor`, does **not** raise the funded-loss budget above zero, and does **not** authorize paper-to-funded promotion.
- Separate forward milestone: `breadth-trend-forward` is scored **after 2027-05-19** and must **not** be pulled forward or inspected early to influence the 2027-02-08 gate.
- `funding-confirmed-trend-forward` is scored **after 2027-02-08** only once Binance monthly funding zips cover `2027-02-08`; its incomplete record cannot satisfy G2 early.

## 3. Required evidence bundle on 2027-02-08

The review receipt written to `evidence/2027-02-08-checkpoint-decision.md` must attach or cite exact digests for:

1. Exact Git commit SHA and CI run URL covering that SHA.
2. 30-day UTC daily feed coverage table (`2027-01-09`..`2027-02-07`), count of failed doctor/feed days, longest raw segment gap in hours, and unclosed segment list.
3. Prospective `btc-daily-trend` (`data/live/allocation/journal.jsonl`) and `passive-multi-asset-mix` (`mix-journal.jsonl`) continuity audit: expected days, recorded days, missing/stale days, and exact economic accounting version.

   The Windows allocation wrapper records refresh failures by symbol and continues with the other symbols. The subsequent journal commands require the preceding completed UTC day. A partial refresh can finish successfully when both journals cover that day from stored candles. A missing day fails and leaves earlier decisions in place. On November 23 the previous wrapper stopped its mix refresh at XAUTUSDT after TLS handshake failures. Both November 22 journal entries were recovered exactly against their original cutoffs using the stricter local commands and the retained read-only database. The next scheduled run will provide a receipt for the updated wrapper.
4. Independent holdout/final-evaluation release bundle (preregistered identity, total selection attempts, DSR probability, exact cost model, refusal/unknown checks).
5. Installed-host vs source capability status (`C:\Program Files\TradingGYM\Executor` hashes, service state `Stopped` / `DISARMED`).
6. Backup status disclosure (including whether the 2026-11-16 off-machine backup cancellation exception remains in force; reconsideration is strongly recommended before any funded-host work).

## 4. Decision ownership matrix (`G011`)

No single automated job or AI workflow may self-approve across domains. Each domain requires explicit sign-off before promoting claims:

| Domain | Scope | Required approver | Minimum evidence |
| --- | --- | --- | --- |
| **Financial math & exact money** | Decimal conservation, fee legs, inventory defaults (`inventory/1` / `inventory/2`), shared-cash rules | Owner + independent differential/property oracle | Passing conservation & standalone-vs-portfolio parity fixtures |
| **Statistical inference & edge claims** | Sampling grain, dependence adjustment, DSR/SPA/bootstrap, MDE/power | Owner + registered trial-log & null calibration | Pre-committed pass mark, complete family attempt count |
| **Research outcome release** | Holdout custody & consumption release | Separate final-data custodian ([independent-custody-protocol.md](../gym-core/docs/independent-custody-protocol.md)) | Pre-read consumption receipt & signed release bundle |
| **Local API & security boundaries** | Loopback route matrix, Origin/Host/CSRF, token/secret isolation | Owner | Route/negative-security test suite |
| **Backups & recovery policy** | Off-machine scheduling, key escrow, restore scope | Owner (explicit opt-in only) | Isolated full restore receipt; never auto-enabled |
| **Installed HOST & funded authority** | Signed binaries, Windows SID/DPAPI/ACL, STOP/send, venue reads, arming | Owner + independent OS/venue reviewer | Installed-host qualification bundle (`H001–H029`) |
