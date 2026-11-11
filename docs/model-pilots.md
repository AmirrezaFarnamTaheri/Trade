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

## L-8 pilot (recommended first)

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

## L-7 (MNN-Pocket-0.3B): deferred

Pilot only after L-8, through the loopback connection with a pinned GGUF on a llama.cpp server, using the L-6 set
against the no-model baseline. Persian is unsupported until the pilot shows otherwise.

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
