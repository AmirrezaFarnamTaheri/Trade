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
3. The owner labels 100 to 300 claim and passage pairs from saved evidence packets, including an adversarial
   subset whose passage contains an instruction, and Persian pairs. Hold out a calibration split.
4. Write the thresholds down before the run: minimum AUROC, maximum calibration error after temperature fitting,
   and the largest acceptable accuracy drop on the adversarial subset.
5. Run `entailment-check` over the set, save the report with the prompt-set hash and model hash, and compare.
   Adopt for the advisory role only if every threshold passes. `semantic_grounding_verified` stays false either
   way.

## L-7 (MNN-Pocket-0.3B): deferred

Pilot only after L-8, through the loopback connection with a pinned GGUF on a llama.cpp server, using the L-6 set
against the no-model baseline. Persian is unsupported until the pilot shows otherwise.
