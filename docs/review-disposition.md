# GPT and Gemini review disposition

Source reviews: `GPT Review.md` and `gemini review.txt`. This is a prioritized implementation pass against `dd04de5` and the existing working tree, not a checklist claiming that every proposal was reproduced or implemented.

## Implemented

- **Stale terminal portfolio valuation (GPT §5.1).** Performance is `PROVISIONAL` when any held market has a stale terminal mark. Last-known equity, per-market freshness, fills and output digests are preserved. A regression covers both newly saved and verified reloaded results.
- **Shared-cash turnover (Gemini, quantitative engine findings).** Turnover uses filled notional across market ledgers divided by starting quote cash. It does not combine asset quantities or substitute a single-asset exposure benchmark. Verified reads recompute derived metrics without changing run identities.
- **Truncated autocorrelation adjustment (Gemini, financial modeling audit).** Taper the truncated lag window with Bartlett weights. Preserve the exact finite-horizon formula when all required lags are available. Tests cover both paths.
- **Executor status (both reviews).** Source includes one-shot LIMIT submission; the installed-host evidence does not qualify it. Documentation and the service module header now draw that distinction. No executable authority changed.

- **Loopback response headers (Gemini 421–430, 2661–2720).** Apply the existing security headers and API cache defaults in the shared guard, including rotation, admission refusals, and router errors. Token and Origin admission policy is unchanged.
- **REST throttling (Gemini 401–412).** A successful request can recover one pacing step after 60 seconds without a rate-limit penalty. Recovery never exceeds the configured normal rate. The last retry's 429 also records a penalty.
- **Missing cross-market cost context (Gemini 341–360).** Toman premium and lead/lag abstain instead of raising when their fee assumption is unavailable.
- **Exploratory bootstrap resolution (Gemini 876–988).** Raise the default from 199 to up to 499 replicates within the existing work budget. Retain the conservative upper bound, explicit simulation counts, and exploratory label. This is not Hansen's consistent SPA; at the work ceiling even the new default may be too small for 5% resolution.
- **Onboarding (both reviews).** Document the synthetic DEMO launch and private session link.

- **Comparison validation (Gemini 421–430).** Preserve specific errors for invalid cash, cost fields and flags. Invalid timestamps return a bounded message without echoing input.
- **Partial historical venue metadata (GPT §3.3).** List missing precision or minimum fields even when other fields are known. This does not change fill rules or qualify the replay.
- **Irregular observations (GPT §7.1 and §9).** Enhanced performance reports include positive and nonpositive mark interval counts, median spacing, and maximum gap. These are diagnostics, not effective sample sizes or a substitute for a dependence model.

- **Market query indexes (Gemini 401–412).** Schema 6 indexes trades by instrument and event time, and quotes by availability time. A scratch schema 5 upgrade verifies both query plans and preserves replay order for equal-time trades. No production store was migrated.

## Already addressed or not reproduced as reported

- **`update-check` always exits zero.** The command dispatcher already maps policy refusal to exit code 2. Existing regression coverage includes unresolved orders, open positions without protection, and a damaged ledger. Changing the successful return would not fix a defect.
- **Portfolio count and Ruff pin drift.** The incoming working tree already corrects the architecture limit and the local Ruff references. Those edits were retained.
- **Saved-run benchmark smoke failure.** The incoming test waits for the selected run identity before asserting benchmark marks. It passed on Windows Edge. This does not establish the cause or resolution of the historical Linux Chrome failure.
- **Unbounded window-signal replay and collector diagnostics.** Recent code includes bounded window recomputation and collector crash reporting. This does not imply constant-time updates for every indicator or that synchronous collector I/O has been resolved.

## Still open

- **Paper execution evidence:** unknown historical venue constraints, date-aware fee schedules, queue/latency sensitivity, and divergence between quote marks and executable liquidation. Add these under versioned replay inputs rather than silently reinterpret frozen trials. Audit entry/exit fee and small-position semantics with exact ledger fixtures before changing execution logic.
- **Research qualification:** the centered bootstrap and Wilson upper bound in `spa.py` are deliberately conservative; a result below 5% does not constitute independent validation. A Hansen SPA replacement needs separate calibration and method labeling. Holdout overlap policy, tail-risk reliability, CPCV/PBO, sequential testing and prospective journals need their own protocols and tests. Do not rescore frozen trials.
- **Protected executor and local API:** no settlement, vault lock, authorization policy, cancellation, or recovery code was changed or qualified here. The proposed lock split needs a preserved STOP/disarm linearization point and durable handling of uncertain sends; a synthetic concurrency test is not installed-host evidence. Global browser Origin rules and making saved runs private change a documented admission contract. UI hot-asset hashing and synchronous API reads remain separate work; startup-only hashes would break the current asset-refresh test.
- **Storage and operations:** measure segment rollover, tick lag, and write amplification before moving writes or changing publication ordering. Use point-in-time fixtures for REST reseeding and spec versioning. Add a quality-event index only when a traced query justifies its write cost. Parquet, a writer actor and database consolidation need migration, crash-recovery and restore evidence. Nested SQLite backup consistency and manifest authenticity need format and restore tests. Off-device scheduling requires an owner decision; this pass did not enable it.
- **UI, maintenance and research expansion:** leave the scorecard, timeline, wider portfolio controls, accessibility work, ES-module migration, cleanup and peer-system adoption as separate changes. Preserve historical reproducers and evidence. Project licensing requires an owner decision.

### Closure criteria for open review groups

| Review sections | Open work | Evidence required to close |
| --- | --- | --- |
| GPT §§3–6, 9–12; Gemini 341–360, 761–785, 1259–1717 | Versioned execution-evidence gate, fee vintages, correct fee-leg and small-position semantics, queue and latency scenarios, liquidation and portfolio risk | Fixtures that cross missing and changing venue constraints, reproduce marked versus executable values, and verify exact postings and frozen-run compatibility |
| GPT §§7–8; Gemini 378–387, 789–797, 876–1248, 2330–2413 | Independent holdout custody, Hansen SPA, sample dependence, CPCV/PBO, sequential testing, prospective journal integrity and maker trial | Null and alternative calibration, purge/overlap tests, and registration before observations are scored; no retroactive registration or rescore |
| GPT §§12–14; Gemini 516–527, 1718–2203, 2428–2540, 2661–2720 | Settlement reconciliation, vault lock split, reservation recovery, STOP/cancellation boundaries, browser admission | Protect unrelated locked funds; inject crash and ambiguous acknowledgement cases; preserve independent STOP. Security-policy changes and installed-host drills require approval separate from these local checks. |
| GPT §§4, 14–15; Gemini 401–412, 2204–2329, 2541–2630, 2889–3224 | Collector batching and actor, recorder indexes, Parquet parity, database consolidation, backup and restore | Measure loop lag and query plans; compare timestamp boundaries and ordering with SQLite; prove crash recovery and scratch restore before any production migration. Independent backup destination requires owner approval. |
| GPT cleanup and UI plans; Gemini 667–747, 2633–2647, 2721–2888, 3225–3306 | UI parity and accessibility, app structure, source hygiene, script classification, licensing | Edge and Linux Chrome on LTR/RTL and narrow layouts; contract tests before refactors; prove no evidence reproducer loses its inputs. Do not remove compatibility code or select a license without checking ownership and callers. |
