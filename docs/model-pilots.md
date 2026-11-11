# Model pilots: what is built, and what the owner runs (L-6, L-7, L-8)

No model is part of the product. These are the only routes for trying one, and every output stays advisory and
off the order path.

## Built

| Piece | Where | Purpose |
|---|---|---|
| Offline evaluation set and no-model baseline | `gymctl assistant-eval` (`services/assistant_eval.py`) | L-6: JSON validity, catalogue hit rate, latency, against a random catalogue pick (baseline valid-proposal rate 0.344) |
| Local loopback connection | gateway `auth.type: "local"` | L-1: an OpenAI-compatible server on 127.0.0.1, no key, no redirects |
| Typed-decision client | `gymctl research entailment-check <pairs.json>` (`services/typed_decision.py`) | L-8: an advisory entailment probability per claim and passage |
| Artifact registry and fit counting | `services/model_artifacts.py` | M-2: content-addressed artifacts; each fit is a trial |

## L-8 pilot: evaluated, advisory enablement refused

On 2026-11-11, the pinned `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` checkpoint
(`704310ca0bb8eb15bca150fc1e11083cd423dd02`, MIT) ran locally with quantized ONNX weights.
The weight SHA-256 is `27c39e884c14b03cf46cfc5485971b6db70ff330220d93dfe729c63fde43af0e`.
The versioned synthetic fixture contains 128 EN/FA numerical and matched instruction-injection pairs;
64 fit and 64 untouched test pairs were frozen before inference. Fixture SHA-256:
`829b7f0edc9d0d2a9fd33865b40a99695e3664a2b97af9a02cedbf44aca79256`.

Predeclared per-language limits were AUROC >= 0.90, calibration error <= 0.10 and
clean-to-adversarial accuracy drop <= 0.05. Temperature 0.85 was selected using the fit split only.

| Held-out synthetic fixture | AUROC | Calibration error | Accuracy | Adversarial accuracy drop | Verdict |
|---|---:|---:|---:|---:|---|
| English, 32 pairs | 1.0000 | 0.0397 | 1.0000 | 0.000 | Pass |
| Persian, 32 pairs | 0.9961 | 0.0745 | 0.9375 | 0.125 | Fail |

The Persian failures were confident, without abstention. Advisory enablement remains off and
`semantic_grounding_verified` remains false. These are synthetic fixture results, not empirical language accuracy.
The unchanged typed-decision client matched all 64 held-out probabilities through an ephemeral loopback server.
Across 192 inferences, median latency was 99.2 ms and p95 186.2 ms on one CPU thread.
Pinned assets, runtime requirements, protocol, raw results and receipts are retained locally under
`.pi/qualification/entailment-pilot-20261111/`; the server is stopped.

### Requalification procedure

1. Run a typed-decision model (Kev 0.8B or an openjev checkpoint, whichever the laptop can run) behind a loopback
   server that answers `POST /v1/systemone` with `{"task":"entailment","premise","hypothesis"}` ->
   `{"probability": p}`.
2. Pin the weights: write `data/live/typed-decision.json` with the URL, the SHA-256 of the weights file, and a
   timeout.
3. Prepare a versioned synthetic claim/passage fixture set with deterministic truth labels, including adversarial
   instructions and Persian pairs. Hold out an evaluation split. Report these results as fixture reliability,
   not empirical language accuracy or calibrated real-world probabilities.
4. Write the thresholds down before the run: minimum AUROC, maximum calibration error after temperature fitting,
   and the largest acceptable accuracy drop on the adversarial subset.
5. Run `entailment-check` over the set, save the report with the prompt-set hash and model hash, and compare.
   Enable the advisory role only if every threshold passes on the declared fixture scope. `semantic_grounding_verified` stays false either
   way.

## L-7 (MNN-Pocket-0.3B): measured runtime block

The official Apache-2.0 checkpoint `taobao-mnn/MNN-Pocket-0.3B` was pinned to revision
`48fae9c0be6ec505e80f36f69b8ba21097f9f822`. Its 723,137,248-byte safetensors file matched SHA-256
`24e182cebe433e9354dc35567d66c655888e7577ca7f6f71cea196a5b7da6276`.
Standard Transformers loaded it without remote code, using CPU SDPA after eager attention exceeded memory.

The existing 30-case evaluator, original catalogue prompts, baseline and thresholds were frozen unchanged
(prompt-set SHA-256 `f75032084391e433c9cb535bde1bda64970be41da74f532fbab30cd0f985d05a`).
Case 00 contained 6,995 input tokens and took 64.94 seconds to produce one token before stopping.
It failed the declared 60-second limit; cooperative generation timeouts cannot interrupt prefill.
The remaining 29 cases were not run, so no complete comparison or adoption is claimed.

A separate short-message gateway diagnostic failed during isolated-state Windows ACL initialization,
before an HTTP model request. Gateway connection remains unverified; no ACL check was bypassed.
Receipts, raw response, assets and protocol are retained under
`.pi/qualification/generative-pilot-20261111/`. All owned processes are stopped and the experiment role is disabled.
Requalification needs a runtime that handles the unchanged prompts within budget and a working protected gateway state.
Persian capability remains unqualified.

## Feed-anomaly classifier v1 (M-2 step 2): built and evaluated

`gymctl feed-anomaly train|scan` (`services/feed_anomaly.py`). A logistic regression over five point-in-time features
(spread, return size, time gap, depth change, order-of-magnitude jump), trained in pure Python on faults injected
into real clean quotes plus rows the collector already flagged. It is advisory: it never trades, sizes or edits data,
and no order, sizing or strategy module imports it. Each fit is recorded as a `model-fit` trial before the artifact is
registered; scanning ABSTAINs on a missing, corrupt, expired or incompatible artifact.

First fit, 2026-11-10, 20 busiest markets on 2026-11-08 (first 70% of the day to train, last 30% held out):

| | AUROC | Precision | Recall |
|---|---|---|---|
| Model (artifact `bc0eebaa…cce0cb`) | 0.995 | 0.972 | 0.967 |
| No-model rule baseline | 0.959 | 0.695 | 0.997 |

Held-out rows: 74,600, of which 11,480 anomalies. Scanning USDTTMN on 2026-11-10 flagged 9 of 3,827 quotes, all in a
real dislocation at 15:59 UTC (bid 200,000 against ask 218,900). The meta-labeller (the second model) still waits for
300 verified closed trades.
