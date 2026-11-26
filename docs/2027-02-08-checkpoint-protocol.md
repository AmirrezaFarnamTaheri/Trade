# 2027-02-08 Funded-Path Checkpoint Protocol

**Status:** Frozen pre-committed decision gate (task `G006`, implementing [PRODUCT.md](../PRODUCT.md#L41-L54) and [ADR 0006](adr/0006-arming-and-fail-closed-custody.md))  
**Committed date:** 2026-11-21 · **Pinned baseline:** `8fba0b15115b617067fc93b9c9769c9351472900`  
**Review date:** 2027-02-08 (UTC) · **Authority:** Decision gate only — never an arming signal.

## 1. Stop rule (pre-committed, non-negotiable)

On **2027-02-08**, funded-execution work **pauses** and TradingGYM remains a research-only observatory if **any** of the following conditions fails. No parameter, threshold, denominator, or date window may be relaxed after observing outcomes.

| Gate | Requirement | Exact denominator and measurement | Fail outcome |
| --- | --- | --- | --- |
| **G1 — Feed reliability (Instant Mode)** | **Instant Mode (2026-11-24, owner-directed, zero calendar wait):** Immediate live `/api/health` check confirms `connected = true`, `40` markets across `2` shards, `0s` lag, `--depth-levels 5` populating `book_top.depth`, and live Nobitex quotes recording in `multi_venue_quotes.sqlite3` (`gym-core/scripts/instant_gate_check.py`). *(Original 30-day calendar wait retired per owner directive.)* | Live loopback `/api/health` + immediate read-only SQLite check on `data/live/market.db` (`book_top.depth IS NOT NULL`) and `data/live/multi_venue_quotes.sqlite3`. | Pause funded path |
| **G2 — Independently validated net edge (Instant Mode)** | **Instant Mode (2026-11-24, owner-directed, zero calendar wait):** Replace 30-day/90-day forward waits with immediate **Development (`<= 2025-11-23`) vs. 365-Day Sealed Historical Holdout (`2025-11-24..2026-11-23`)** evaluation + **Purged CPCV/PBO (`< 0.50`)** + **500-run path-preserving placebo (`p < 0.05`)** + **Causality perturbation check (`True`)** + **Deflated Sharpe Probability (`DSR >= 0.95`)** after exact Wallex L1 / Nobitex `-30%` executable costs. *(Original v1 `8fba0b1` DSR threshold preserved; only calendar-waiting delays removed.)* | Executed on demand via `gym-core/scripts/instant_gate_check.py` against existing multi-year `data/live/market.db` candles (`2019–2026`) and archived `book_top` / `trades`, preserving exact multiplicity denominator (`N = 21` registered trials) and exact executable fee schedules. | Pause funded path |
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
