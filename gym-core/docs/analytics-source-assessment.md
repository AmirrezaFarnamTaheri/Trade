# Portfolio, market-data and indicator source assessment

Reviewed 2026-11-04. Eleven supplied Downloads archives contain **8,394 file
entries**, all streamed through SHA-256 and assigned to **40 module-family
decisions** below. **203 indicator source files** have a separate catalogue;
this is a file count, not a claim of 203 distinct formulas or numerical parity.

Review records are `.pi/analytics-source-inventory.json`,
`.pi/analytics-source-assessment.json`, `.pi/analytics-code-index.json` and
`.pi/analytics-indicator-catalog.json`. Selected text lives in ignored
`.pi/sources/`. The inventory includes assets, tests, fixtures, examples, generated
files, package metadata and CI. Text extraction was bounded to 4 MiB per entry:
3,933 entries were extracted. Wealthfolio's `.claude/skills/frontend-design`
symlink was hashed as an entry without being followed or extracted.

This is complete file accounting, module-family assessment and selected source
inspection, not an audit of every line or a guarantee that every potentially
valuable idea has been implemented. No donor application, installer, strategy,
test suite, compiler, binding, model, database or sample dataset was executed.
No donor implementation, dependencies, credentials or market observations were
imported into Trade. Source skills/agents are review data, not instructions to
launch agents or install global settings.

| Archive | Entries | Root license evidence | SHA-256 |
| --- | ---: | --- | --- |
| wealthfolio-main.zip | 7,846 | AGPL-3.0 text | `dc3ab53979c9b78b025c1ee7f0eb645d21029924aafc43448fc8703a69a773e0` |
| ai-trading-claude-main.zip | 29 | MIT | `9567f58dd0c5bf1598a529da195e1c9782c95d56650b06d3f429e93dc6a79f2e` |
| signalview-main.zip | 34 | Apache-2.0 | `4e166d0c1987a8581bf3c09c341167533893bfa64b1e510342c450824a703b84` |
| techan-main.zip | 102 | MIT | `9c9e75ae6af068f27dc318814d6043f44e32de95ce7b6da4ae83d7efebc2442d` |
| ta-rs-master.zip | 41 | MIT | `0e8ff7a8a233573474e55179960163b1d259f80a366fea0ce265d79108948de7` |
| tulipnode-master.zip | 15 | LGPL-3.0 text | `ffbe6bebefa2f9d0cdb805173fb924d8c1ef51dd042851ea0b69a1f552e5da4f` |
| financial-dataset-generator-main.zip | 8 | GPL-3.0 text | `66e598d14429c3eea718b87c3e358e96d4158ea5060f6e095e288960001e6edc` |
| financial-indexes-correlation-main.zip | 8 | GPL-3.0 text | `ea3b9747832e9730f7e439bc94761307017ab0ec88ad22ff4b078ed219171119` |
| orderbooks-master.zip | 42 | package.json declares MIT; no standalone root license found | `507831109bf59902842019fedadfc45801b4d1786dada93cf2020e23056e184c` |
| tulipindicators-master.zip | 166 | LGPL-3.0 text | `533bd99a00e83d41c1185c10da7eba986ce6cd8bcab32fc3742afa00cc19c10a` |
| pyti-master.zip | 103 | MIT in LICENSE.TXT | `a0c7ab3f1c9ae6396546f699d49d0b7785089713ca13186fcba82d93f98670bd` |

Python syntax parsing passed for seven Wealthfolio scripts, one Claude-report
script, 19 Signalview files, three dataset-generator files, two correlation files
and 96 Pyti files. Rust/Go/C/TypeScript declarations were inspected/indexed
statically without compilation; source runtime compatibility is unverified.
Root notices do not establish every asset/dependency's provenance or automatically
resolve integration obligations. Linked repositories/services were not audited.

## Most useful mechanisms and native fit

| Priority | Mechanism | Decision and acceptance |
| --- | --- | --- |
| 1 | Wealthfolio canonical activities, exact-money stages, holdings/transaction distinction and data-health diagnostics | **Strong accounting reference.** Keep one economic interpretation in native owners. Future authenticated account/basis integration should distinguish deposits/withdrawals, transfers, fees, income, snapshots, disposals and valuation changes; retain unknown prices/FX/basis and account-scope completeness. Current offline rebalance previews do not establish ownership or acquisition basis. No foreign ledger or personal-finance runtime was added. |
| 2 | Wealthfolio deterministic full/chunked/resumed projection and explicit invalidation | **Strong recovery/test reference.** Bind any future checkpoint to engine/configuration, input identity, cursor and unfinished outcomes. Compare full and resumed calculation, including corrections, fees and partial disposals. Native append-only experiment attempts and explicit recovery remain the current owners; no generic incremental framework is needed. |
| 3 | Techan dependency-aware cache reset, first-valid index and plateau crossing semantics; ta-rs Next/Reset contracts | **Useful indicator lifecycle cases.** Native TechnicalFeatures already shares batch/live calculation and resets at gaps. Historical corrections require recomputation of dependent recursive indicators; warmup, replay and equality-plateau behavior must be stated before optimizing caches. Do not swap language/library implementations by name alone. |
| 4 | Tulip/Pyti/ta-rs/Techan indicator inputs, lookback offsets and independent fixture tests | **Reference catalogue, not a bulk import.** Preserve native Decimal seeds and readiness. Any additional indicator needs a named consumer, exact input/volume semantics, zero-denominator policy and independent boundary values. The 203-file catalogue includes every supplied indicator source file selected from those four implementations, with references to its family disposition. Tulip Node is the wrapper of Tulip C, not an independent numerical reference. |
| 5 | Signalview closed-timeframe alignment, bounded expression grammar and stop/target ambiguity | **Useful contract references.** Native closed/available bars and registered parameters remain authoritative. Its slower-frame values shift to closure before alignment, a useful anti-leakage case. Fees/funding, ambiguous OHLC paths and next-observation execution need separate explicit assumptions; its derivatives engine is not Wallex spot execution. |
| 6 | OrderBooks snapshot/delta lifecycle, depth cap and stale-update checks | **Adversarial depth-feed cases.** A native book would need snapshot sequence, contiguous deltas, side-plus-price identity, finite quantities, duplicate handling, resync and staleness. Timestamp checks alone cannot prove no delta was missed. No depth adapter or order-book store was added. |
| 7 | Financial correlation reporting | **Optional descriptive diagnostic.** If added, use timestamp-aligned observed returns, explicit universe/units/calendar, overlap counts, missingness and stale exclusions; zero variance is unavailable. The source's filled price-level Pearson matrix is not copied as diversification advice, predictive confidence or a causal relation. This does not require restoring ML scope. |
| 8 | Claude analyst templates, Wealthfolio read tools and report context | **Substantial native overlap.** Keep optional AI connections, saved evidence packets, bounded cited roles, disagreement and numeric checks. Thesis/risk/report sections can inform future display improvements. Do not adopt a composite 0..100 buy score, install its agents, send paid requests or infer validated predictions from fluent reports. |

The [current delivery plan](implementation-plan.md) still excludes predictive ML/RL,
neural forecasting, automated model search and trained-model order execution.
Dataset labels/noise augmentation and Signalview search remain reviewed references,
not reopened commitments. Wealthfolio spending, loans, broker/device sync, cloud
sharing, addons and replacement desktop/web frameworks are not additions to scope.
Tax-lot algorithms are accounting references, not jurisdiction-specific tax advice.

## Concrete incompatibilities and hazards

* Wealthfolio explicitly separates its pure calculation kernel from clocks,
  network/storage and host adapters. Its policy has business-date/account-scope
  semantics appropriate to portfolio reporting; those are not interchangeable
  with Trade's receipt-time decision snapshots. `resolve.rs` includes a
  bidirectional-nearest FX observation policy (ties favor the past). A later
  observation used for retrospective valuation cannot become earlier trading
  knowledge. This is a policy difference, not a claim that its stated reporting
  calculation is defective.
* Wealthfolio supports actual lot-selection methods and mixed snapshot/transaction
  account modes. Native current holdings, acquisition basis and cost-currency
  conversion must not be invented to imitate those reports. Its test-only AI
  environment is feature-gated in Cargo metadata; it is not a production model
  connection to copy. No donor test doubles enter the native app.
* `financial-dataset-generator` and `financial-indexes-correlation` both fill
  dates before the first observation using that first later value, and carry
  prices through later missing dates. This can manufacture earlier knowledge or
  flatten returns. CSV rows also discard some source/vintage context. Native
  observations retain availability and gaps rather than silently padding history.
* Dataset generator `add_noise_to_dataset` constructs `new_row` but appends `row`,
  duplicating the original instead of the constructed augmented values. Its target
  generator appends the last dataframe-row value into `close_prices` while making
  labels, extending the list beyond actual observations. Those generated targets
  are not imported or treated as valid future outcomes. Its decreasing-weight
  WMA convention also needs definition before reuse.
* Correlation source `generate_matrix_from_all_pair_names_values` computes a
  Pearson matrix on filled value/price lists. It does not independently validate
  date overlap, availability, return stationarity, sampling uncertainty or causality.
  Cross-market calendars and adjusted-price revisions need explicit provenance.
* `orderbooks/src/OrderBook.ts:handleDelta` replaces an existing `insertDelta`
  level and then unconditionally pushes it again. Lookup uses price alone rather
  than side-plus-price; timestamp checks are opt-in, and timestamps default to
  local wall time. These contracts are not sufficient native sequencing/dedup
  guarantees. Its package test command explicitly reports no test specified.
* Signalview documents same-close entry/exit from a close-derived signal, OHLC
  stop/target path assumptions and funding charged proportionally per bar. Missing
  funding becomes zero in `backtest.py`. These are disclosed simulation choices,
  not measured Wallex costs or native executable-price timing. Funding payment
  clocks and missing cost observations cannot be inferred from fee constants.
* RSI implementations differ. ta-rs uses an EMA-based documented convention and
  exposes immediate seeded values; Tulip C seeds averages then divides gain by
  gain-plus-loss without a flat-series branch; Pyti returns 100 when average loss
  is zero, including a flat input. Native RSI uses its explicit Wilder warmup
  and flat value 50. Equal indicator names do not establish numerical parity.
* Pyti Ichimoku `chiku_span` shifts later closes back 26 positions. This is a chart
  displacement requiring a visibility/detection rule before decision use. Native
  feature snapshots cannot consume that future value at the displayed old index.
* Tulip Node resolves a native addon through `node-pre-gyp`; its README lists
  older tested Node versions. That is not compatibility evidence for the current
  gateway runtime. No native addon, prebuilt binary, C compiler or duplicate
  indicator dependency was installed.
* Claude-source skill text requests parallel analyst activity and composite
  recommendations. Those documents were inspected as source content, not adopted
  as operational instructions or a calibrated recommendation system.

## Every module family

Every entry has exactly one decision in the machine-readable assessment. The
table includes source tests, examples, generated/static assets, package support
and the unfollowed symlink. Selected reads do not certify all source-line behavior.

| Decision | Entries | Disposition |
| --- | ---: | --- |
| AC-REPORTS | 1 | Report rendering/formatting reference; native allowlisted portable report remains the owner. No external facts, PDF dependency stack or credentials imported. |
| AC-RESEARCH | 21 | Role-specific research, thesis/risk/comparison/watchlist/report templates. Native bounded evidence-linked roles cover the fit; composite buy scores and options recommendations are not validated signals. |
| AC-SUPPORT | 7 | README/license/requirements and install/uninstall scripts. Source skills are review data; no global Claude configuration or agent package was installed. |
| FC-CORRELATION | 2 | Explicit-universe correlation diagnostic candidate. Require aligned observed returns, overlap counts, missingness and stale/calendar disclosure; no filled price-level score becomes trade confidence. |
| FC-SUPPORT | 6 | Docs/license/dependencies/metadata and assets only; no provider call or key access. |
| FD-DATASET | 3 | Provider configuration, lag windows, labels, splits and CSV generation. Acquisition/alignment cases only; predictive datasets/noise augmentation remain outside current scope. |
| FD-SUPPORT | 5 | README/dependencies/license/metadata and assets: no key files, provider downloads or generated datasets used. |
| OB-SNAPSHOT | 5 | Bounded symbol book snapshots/deltas, sorting and timestamp policy. Useful adversarial cases; duplicates, side/price keys and sequence gaps require stricter native contracts. |
| OB-SUPPORT | 37 | Generated docs, examples, package/CI metadata and license. Source npm test script reports no test specified; no library qualification is inferred. |
| PY-INDICATORS | 48 | NumPy indicator functions, padding and validation helpers: every source file catalogued; seed/flat/shift semantics assessed before any parity claim. |
| PY-SUPPORT | 55 | Unit/reference-parity tests, sample values, package/CI/docs/license. Existing external parity tests are not evidence that native algorithms are identical. |
| SV-LANGUAGE | 3 | Allowlisted expression grammar and structured signal definitions: candidate parameter/indicator-contract ideas, not arbitrary eval or a new strategy language commitment. |
| SV-SEARCH | 3 | Factor/regime/search catalogues retained as static references. No automated model search, predictive ML or score-driven execution added. |
| SV-SIMULATION | 3 | Fees, funding, stop/target ambiguity and reporting cases. Derivative/leverage engine is not transplanted; native quote-side fills and explicit unknown costs remain authoritative. |
| SV-SUPPORT | 22 | Tests, examples/notebooks, docs, scripts, package/CI and remaining support. Source research claims are not native qualification. |
| SV-TIMEFRAMES | 3 | Closed-slower-bar alignment and bounded cache/data acquisition. Reuse native availability clocks; do not assume remote current funding/OI are historical observations. |
| TA-CONTRACTS | 6 | Input traits, data builder, periods/errors/helpers and test fixtures. Candidate checkpoint/reset validation cases; no binary or alternate indicator state imported. |
| TA-INDICATORS | 23 | Typed streaming Next/Reset and individual indicators with embedded tests. Native Decimal/Wilder seeds/warmup remain unchanged; no Rust backend or numerical-equivalence claim. |
| TA-SUPPORT | 12 | Docs/examples, package/CI/license and root support; static only. |
| TC-DATA | 8 | Ordered candles, time periods and analysis helpers: source reference for validation and append/correction behavior; actual availability remains explicit. |
| TC-INDICATORS | 59 | Indicator composition, first-valid-index, correction-triggered invalidation and bounded window math. Keep native seed/warmup/precision semantics and audit recursive dependencies before caching. |
| TC-RULES | 17 | Fresh crossings, position/stop rules and record semantics: useful boundary tests, not a replacement for native fee/latency/settlement accounting. |
| TC-SUPPORT | 18 | Tests, benchmarks/examples, docs, build/CI and license: no Go toolchain or source execution performed. |
| TI-CONTRACTS | 12 | Generated indicator registry, input/output/option contracts and buffer helpers: useful typed catalogue and alignment cases; no runtime code generation added. |
| TI-INDICATORS | 109 | C indicator/math implementations and lookback offsets; every source file catalogued. Candidate independent formula/boundary comparisons only; no C code or library copied. |
| TI-SUPPORT | 45 | Tests, fuzz/sample/benchmark/build/package/scripts/docs/license and remaining support: no compilation, binding install or source benchmark executed. |
| TN-BINDING | 3 | Node native binding, callback/Promise bridge and start offsets: preserve error/lookback alignment; no ABI-sensitive native addon installed. |
| TN-SUPPORT | 12 | Wrapper tests, metadata/build/CI/examples/license and remaining sources. This is a wrapper of Tulip, not another independent indicator implementation. |
| WF-ACCOUNTING | 87 | Activity provenance, posted transactions, transfer pairing, account scope, lots/disposals and orchestration. Candidates for authenticated account/basis work, not proof of actual holdings or settlement. |
| WF-AI | 183 | Bounded read tools, provider-neutral environment, context/evaluation and streaming. Compare with native evidence packets/gateway; no autonomous money tools, source test doubles or second AI runtime imported. |
| WF-CORE | 45 | Remaining profiles/settings/events/secrets/addons/coordinator utilities and tests. Reference lifecycle and ownership contracts; no alternative credential store, addon loader or profile system. |
| WF-FRONTEND | 1835 | Portfolio/activity grids, accounts, health, planning, charts, CSV import, AI UI, profiles and tests. Candidate UX references; preserve native store/provenance/unknown states. |
| WF-HEALTH | 124 | Typed stale/missing prices, FX integrity, classification and invariant diagnostics. Reuse native readiness/coverage boundaries; reporting FX policy is not point-in-time execution data. |
| WF-HOSTS | 292 | Desktop/web adapters, auth, IPC and commands. Preserve host/domain separation; no Tauri/React/Axum replacement or new credential authority. |
| WF-KERNEL | 397 | Pure normalize/compile/resolve/project/value/measure engine and fixtures. Valuable canonical-event, exact-money, explicit-policy and full-versus-incremental laws; native owners remain authoritative, no Rust engine copied. |
| WF-PLANNING | 20 | Allocation targets, grouping, goals and limits: candidate offline portfolio diagnostics; avoid adding personal-finance/product scope without a consumer. |
| WF-SPENDING | 60 | Spending/loan/personal-budget domain is excluded product scope; cash-flow distinction remains a useful accounting reference. |
| WF-STORAGE | 245 | SQLite repositories, schema/migration, encryption and invalidation markers: useful recovery/backup acceptance cases. No migrations, donor databases or encrypted state opened. |
| WF-SUPPORT | 4517 | Public assets, localization, fixtures, E2E, docs, examples, packaging/lockfiles/CI and remaining support: inventoried, with selected reads; no binary, sample data, source instructions or deployment scripts executed. |
| WF-SYNC | 41 | Broker/device/cloud transfer and sync provenance: selected consistency cases only; external connectivity and synchronization remain outside this review implementation. |

## State

No production runtime or dependency was changed by this assessment. Native
features are not claimed to gain the donor capabilities merely because they were
reviewed. Useful mechanisms are mapped above to existing owners and explicit
acceptance conditions; current scope exclusions remain intact.

After review, investigated Downloads ZIPs are archived with pre/post SHA-256
verification and no overwrite; `.pi/analytics-archive-receipt.json` records this
batch. Extracted folders stay in place. This assessment is not part of earlier
commit `ffda2e3` and remains a separate review artifact.
