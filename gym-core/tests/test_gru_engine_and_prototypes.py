"""Tests for pure-NumPy CompactGRU exact BPTT gradients, learning sanity, and JSON weight round-trip."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from gym.services.experiments.gru_engine import CompactGRU


def test_compact_gru_bptt_matches_finite_differences_for_both_tasks() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(0.0, 1.0, (4, 5, 3))
    eps = 1e-6

    for task, y in (("regression", rng.normal(0.0, 1.0, 4)), ("binary", np.array([0.0, 1.0, 1.0, 0.0]))):
        gru = CompactGRU(input_dim=3, hidden_dim=4, task=task, seed=11)
        _, grads = gru._loss_and_grads(x, y, l2_reg=1e-3)
        for name, param in gru.params.items():
            # Spot-check first 3 elements of every parameter tensor
            flat_p = param.reshape(-1)
            flat_g = grads[name].reshape(-1)
            for idx in range(min(3, len(flat_p))):
                orig = flat_p[idx]
                flat_p[idx] = orig + eps
                lp, _ = gru._loss_and_grads(x, y, l2_reg=1e-3)
                flat_p[idx] = orig - eps
                lm, _ = gru._loss_and_grads(x, y, l2_reg=1e-3)
                flat_p[idx] = orig
                num_g = (lp - lm) / (2.0 * eps)
                assert abs(num_g - flat_g[idx]) < 1e-5, f"{task} {name}[{idx}]: num={num_g} vs ana={flat_g[idx]}"


def test_compact_gru_learns_sequential_pattern_and_roundtrips_json(tmp_path: Path) -> None:
    rng = np.random.default_rng(42)
    x = rng.normal(0.0, 1.0, (120, 6, 2))
    # Target depends on cumulative sum of feature 0 across the sequence
    y = (np.sum(x[:, :, 0], axis=1) > 0.0).astype(np.float64)

    gru = CompactGRU(input_dim=2, hidden_dim=8, task="binary", seed=42)
    losses = gru.fit(x, y, epochs=35, batch_size=32, lr=1e-2, l2_reg=1e-4)
    assert losses[-1] < losses[0] * 0.5

    preds = gru.predict(x)
    acc = float(np.mean((preds > 0.5) == (y > 0.5)))
    assert acc > 0.90

    wpath = tmp_path / "gru_weights.json"
    gru.save_json(wpath)
    loaded = CompactGRU.from_dict(__import__("json").loads(wpath.read_text(encoding="utf-8")))
    assert np.allclose(preds, loaded.predict(x), atol=1e-12)
