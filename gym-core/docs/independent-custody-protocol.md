# Independent Final-Evaluation Custody & No-Peek Protocol

**Status:** Active research governance specification (tasks `E001`, `E002`, `E003`, `E005`, `E008`, `E022`)  
**Scope:** Elevating TradingGYM from local accident-prevention (`HoldoutLedger`, `ResearchProtocol`) to verifiable independent final-outcome custody.

## 1. Current boundary vs genuine custodian (`E001`)

Today's `HoldoutLedger` (`gym-core/src/gym/services/holdout_ledger.py`) and `ResearchProtocol` (`gym-core/src/gym/services/research_protocol.py`) enforce append-only SQLite triggers, overlap detection, engine digests, and pre-read `CONSUMED` transitions **within the same operator account and workstation**. As `ResearchProtocol.evaluation()` explicitly discloses (`independent_final_evidence: false`), a local SQLite database writable or bypassable by the researcher is **accident prevention, not independent custody**.

A **genuine final-data custodian** requires physical or account-level separation before any new independently evidenced edge claim can be made:

| Role | Access rights | Prohibited actions |
| --- | --- | --- |
| **Researcher (normal operator)** | Read/write training and validation data; submit frozen evaluation packages (code SHA, strategy config hash, cost/fee/benchmark model, universe, window, criterion); receive signed release bundles only after cutoff | Cannot read unreleased final-window raw segments/candles; cannot edit, delete, or backfill consumption receipts; cannot alter pass marks post-registration |
| **Final-data custodian (separate OS account / host / external runner)** | Sole write custody of the append-only consumption ledger; sole read access to sealed future/final evaluation datasets until release; executes the pinned code digest and emits a signed release bundle | Never tunes parameters; never drops failed/aborted runs; never backfills a "fresh" consumption receipt after results were seen |

### Preregistered public-data evaluation on a single-owner project

Future-time preregistration and external anchoring establish a prospective protocol. Once public market outcomes exist, the researcher can inspect them independently of the scoring runner. Classify this workflow as **forward registered** unless a separately controlled evaluator provides evidence of the access restrictions in the table above.
1. **Preregistration anchor before data exists:** Commit the frozen evaluation identity JSON (section 2) to a signed Git tag / remote commit whose timestamp strictly precedes `test_from`.
2. **Untouched future window:** Outcomes are generated strictly by future calendar days (`now < test_from < test_to`) fetched from verifiable public archives (e.g. SHA-256-checked Binance monthly archives or timestamped Wallex recordings) after `test_to`.
3. **Separate execution identity:** Run final scoring in a clean, read-only CI workflow or isolated Windows account against the pinned commit SHA and archive checksums, publishing the immutable workflow log/artifact as the external release receipt.

## 2. Preregistered evaluation identity (`E002`)

Every registered final evaluation must freeze the following canonical fields **before** `test_from` (and before any observation in `[test_from, test_to)` is read):

- `trial_id` and `family_id` (maps every hyperparameter, asset subset, date shift, failed fit, and plot inspection to one selection family — `E005`)
- `code_commit_sha` and `engine_digest` (exact SHA-256 of Python/Rust engine sources)
- `strategy_name`, `strategy_params`, `config_hash`, and `position_model` (`legacy`, `inventory/1`, or `inventory/2`)
- `economic_model`: exact fee source/rate, spread/depth/queue/latency policy, stop mechanics, and executable-net refusal rule
- `data_origin` and `symbol_universe` (point-in-time eligibility rules, zero future listing/delisting knowledge)
- `selection_end`, `purge_gap`, `test_from`, `test_to`, `resolution`, and `calendar_timezone`
- `benchmark_identity` (investable same-currency, same-universe, same-cost baseline)
- `minimum_detectable_effect` and prospective power calculation (`scripts/detectable_edge.py`)
- `pass_criterion` and precommitted stop/extension/missing-day rules (`E018`)

## 3. No-peek threat model (`E003`)

Every read path in TradingGYM that could expose unreleased final-window data before a recorded consumption receipt is a leakage vector and must fail closed or withhold test-derived values:

| Surface / outlet | Leakage vector | Required control | Verification |
| --- | --- | --- | --- |
| **Long-history & research scripts** (`scripts/long_history_study.py`, `held_out_followups.py`) | Printing ridge skill, walk-forward yearly stats, or summary metrics after failed validation or refused holdout look | Hard return before any test-window slice or diagnostic; strict finite `end` scoping | Outcome-perturbation test (`E004`): shock test prices, assert identical stdout & returned dict |
| **Protocol & holdout ledgers** (`research_protocol.py`, `holdout_ledger.py`) | Shifted window, shortened range, or revised price array bypassing `window_id`; peeking before `CONSUMED` write | Per-market `[start, end]` overlap check across all prior looks; `BEGIN IMMEDIATE` `CONSUMED` write before loading test data; monotonic state on crash/abort | Overlapping-window refusal & crash-leaves-consumed tests (`E006`, `E007`) |
| **Loopback HTTP API & Browser UI** (`gym/api/server.py`, `research_actions.py`) | Querying saved runs, charts, scorecards, CSV exports, or `/api/runs` containing future/unreleased outcomes before `as_of` cutoff | Cutoff-bound `review_runs(..., as_of=...)` refusal; UI badges clearly separate `WITHHELD`, `REGISTERED`, and `RELEASED` | Cutoff refusal & perturbation tests |
| **Background job queue & caches** (`research_process.py`, `data/live/runs/`, `experiments.sqlite3`) | Cached intermediate artifacts, sweep tables, or job progress messages leaking test-window Sharpe/equity | Isolate sealed final-evaluation runs from exploratory sweep/cache directories; never render unconsumed run digests in exploratory views | Artifact isolation audit |
| **Charts, CSV exports & logs** | Error messages, tracebacks, CSV formulas, or diagnostic logs printing raw test prices/returns | Bounded sanitized error payloads; no raw test return arrays in error logs | Negative export & error-log inspection |
| **Interactive notebooks & human/AI analysis** (`E021`) | Ad-hoc SQL queries against `market.db` or `data/binance-public` inspecting post-cutoff days without incrementing family attempt count | Log exact inspected source packet & date span; any peek into candidate OOS data counts as a consumed look for that family; prose summaries are never evidence | Mandatory analyst peek log entry |

## 4. Pre-read consumption & signed release bundle (`E007`, `E008`)

1. **Pre-read monotonicity:** `CONSUMED` (or `looks` row insertion) commits durably **before** the first byte of withheld test data is queried. Cancellation, exception, or missing data transitions to `FAILED` or `INCOMPLETE` — never back to `REGISTERED`.
2. **Release bundle contents:** Every completed, failed, or aborted final evaluation emits an immutable JSON receipt containing: evaluation identity, code/data SHA-256 digests, cumulative family attempt count across all looks, exact sample counts and missing/stale counts, decision metric vs frozen criterion, refusal/unknown flags, and independent signature or external CI/Git anchor.
3. **Retention of negative evidence (`E009`):** Failed and invalidated evaluations remain append-only and reconstructible; deleting run files never resets selection counts.

For local verification, `verify_release_attestation` accepts a detached Ed25519 signature, a raw 32-byte public key obtained through a separate trust channel, and the expected SHA-256 from the release receipt. The signer signs the bytes `TradingGYM release-bundle/1`, followed by one zero byte and the raw 32-byte bundle digest. The verifier checks the payload and both digest values before validating the 64-byte signature. A valid signature authenticates the pinned payload to that key. Custodian independence still requires access-control evidence and separate sign-off.

Run `gymctl research verify-release-attestation packet.json` with `bundle`, `signature_hex`, `trusted_public_key_hex` and `expected_digest`. An unauthenticated result exits nonzero. Supply the trusted public key and digest through the separate trust channel described above.

## 5. Two-trial concurrency budget (`E022`)

Per [roadmap.md](roadmap.md#L16-L22), at most **two registered trials** may be concurrently active at any time, and each must introduce genuinely new information (not another parameter sweep of consumed 2024–2026 daily price history). Currently active registered forward trials:
1. `funding-confirmed-trend-forward` (registered 2026-11-18, score after 2027-02-08)
2. `breadth-trend-forward` (registered 2026-11-19, score after 2027-05-19)

No third registered trial may be opened unless one of the active trials completes or is formally superseded in `trial-log.md` with preserved negative/aborted evidence.
