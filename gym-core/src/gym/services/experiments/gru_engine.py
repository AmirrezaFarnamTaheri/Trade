"""Compact pure-NumPy 1-layer GRU with exact analytic BPTT, Adam, multi-seed ensembling, and JSON weight export.

Lives in services/experiments/ (never imported by default app startup or domain/).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    xc = np.clip(x, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-xc))


class GRUArtifactError(ValueError):
    """Raised when a serialized GRU artifact or inference input fails structural/numeric validation."""


def _expected_param_shapes(input_dim: int, hidden_dim: int) -> dict[str, tuple[int, ...]]:
    return {
        "Wz": (input_dim, hidden_dim),
        "Uz": (hidden_dim, hidden_dim),
        "bz": (hidden_dim,),
        "Wr": (input_dim, hidden_dim),
        "Ur": (hidden_dim, hidden_dim),
        "br": (hidden_dim,),
        "Wh": (input_dim, hidden_dim),
        "Uh": (hidden_dim, hidden_dim),
        "bh": (hidden_dim,),
        "Wo": (hidden_dim, 1),
        "bo": (1,),
    }


def _validate_positive_int(val: object, name: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
        raise GRUArtifactError(f"{name} must be a positive integer")
    return val


def _validate_finite_array(val: object, shape: tuple[int, ...], name: str, *, positive: bool = False) -> np.ndarray:
    try:
        arr = np.asarray(val, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise GRUArtifactError(f"{name} is not numeric") from exc
    if arr.shape != shape:
        raise GRUArtifactError(f"{name} shape mismatch: expected {shape}, got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise GRUArtifactError(f"{name} contains non-finite values")
    if positive and not np.all(arr > 0.0):
        raise GRUArtifactError(f"{name} must be strictly positive")
    return arr


class CompactGRU:
    """1-layer Gated Recurrent Unit (many-to-one) with exact BPTT and z-score feature scaling."""

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 12,
        *,
        task: str = "regression",
        seed: int = 42,
    ) -> None:
        if task not in ("regression", "binary"):
            raise ValueError("task must be 'regression' or 'binary'")
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.task = task
        rng = np.random.default_rng(seed)
        s_in = 1.0 / np.sqrt(input_dim + hidden_dim)
        s_h = 1.0 / np.sqrt(hidden_dim)

        self.params: dict[str, np.ndarray] = {
            "Wz": rng.normal(0.0, s_in, (input_dim, hidden_dim)),
            "Uz": rng.normal(0.0, s_h, (hidden_dim, hidden_dim)),
            "bz": np.zeros(hidden_dim),
            "Wr": rng.normal(0.0, s_in, (input_dim, hidden_dim)),
            "Ur": rng.normal(0.0, s_h, (hidden_dim, hidden_dim)),
            "br": np.zeros(hidden_dim),
            "Wh": rng.normal(0.0, s_in, (input_dim, hidden_dim)),
            "Uh": rng.normal(0.0, s_h, (hidden_dim, hidden_dim)),
            "bh": np.zeros(hidden_dim),
            "Wo": rng.normal(0.0, s_h, (hidden_dim, 1)),
            "bo": np.zeros(1),
        }
        self.feat_mean = np.zeros(input_dim)
        self.feat_std = np.ones(input_dim)
        self.y_mean = 0.0
        self.y_std = 1.0

    def _scale_x(self, x: np.ndarray) -> np.ndarray:
        return np.clip((x - self.feat_mean) / self.feat_std, -8.0, 8.0)

    def _forward_batch(self, x_scaled: np.ndarray) -> tuple[np.ndarray, dict]:
        n, t_len, _ = x_scaled.shape
        h_dim = self.hidden_dim
        p = self.params
        hs = np.zeros((t_len + 1, n, h_dim))
        zs = np.zeros((t_len, n, h_dim))
        rs = np.zeros((t_len, n, h_dim))
        h_tildes = np.zeros((t_len, n, h_dim))

        for t in range(t_len):
            xt = x_scaled[:, t, :]
            hp = hs[t]
            zt = _sigmoid(xt @ p["Wz"] + hp @ p["Uz"] + p["bz"])
            rt = _sigmoid(xt @ p["Wr"] + hp @ p["Ur"] + p["br"])
            ht = np.tanh(xt @ p["Wh"] + (rt * hp) @ p["Uh"] + p["bh"])
            hs[t + 1] = (1.0 - zt) * hp + zt * ht
            zs[t], rs[t], h_tildes[t] = zt, rt, ht

        raw = (hs[t_len] @ p["Wo"] + p["bo"]).reshape(-1)
        out = _sigmoid(raw) if self.task == "binary" else raw
        cache = {"x": x_scaled, "hs": hs, "zs": zs, "rs": rs, "h_tildes": h_tildes, "raw": raw, "out": out}
        return out, cache

    def _loss_and_grads(self, x_scaled: np.ndarray, y_norm: np.ndarray, *, l2_reg: float = 1e-3) -> tuple[float, dict[str, np.ndarray]]:
        out, cache = self._forward_batch(x_scaled)
        n, t_len, _ = x_scaled.shape
        p = self.params

        if self.task == "binary":
            eps = 1e-7
            oc = np.clip(out, eps, 1.0 - eps)
            loss = float(-np.mean(y_norm * np.log(oc) + (1.0 - y_norm) * np.log(1.0 - oc)))
            d_raw = (out - y_norm) / n
        else:
            # Smooth Huber loss (delta = 1.5) for outlier resistance
            diff = out - y_norm
            abs_d = np.abs(diff)
            delta = 1.5
            huber = np.where(abs_d <= delta, 0.5 * diff * diff, delta * (abs_d - 0.5 * delta))
            loss = float(np.mean(huber))
            d_raw = np.where(abs_d <= delta, diff, delta * np.sign(diff)) / n

        grads = {k: np.zeros_like(v) for k, v in p.items()}
        hs, zs, rs, h_tildes = cache["hs"], cache["zs"], cache["rs"], cache["h_tildes"]

        d_raw_col = d_raw[:, None]
        grads["Wo"] = hs[t_len].T @ d_raw_col
        grads["bo"] = np.sum(d_raw_col, axis=0)
        dh = d_raw_col @ p["Wo"].T

        for t in range(t_len - 1, -1, -1):
            xt = x_scaled[:, t, :]
            hp = hs[t]
            zt, rt, ht = zs[t], rs[t], h_tildes[t]

            d_ht = dh * zt * (1.0 - ht * ht)
            d_zt = dh * (ht - hp) * zt * (1.0 - zt)
            d_rhp = d_ht @ p["Uh"].T
            d_rt = d_rhp * hp * rt * (1.0 - rt)

            grads["Wh"] += xt.T @ d_ht
            grads["Uh"] += (rt * hp).T @ d_ht
            grads["bh"] += np.sum(d_ht, axis=0)

            grads["Wz"] += xt.T @ d_zt
            grads["Uz"] += hp.T @ d_zt
            grads["bz"] += np.sum(d_zt, axis=0)

            grads["Wr"] += xt.T @ d_rt
            grads["Ur"] += hp.T @ d_rt
            grads["br"] += np.sum(d_rt, axis=0)

            dh = dh * (1.0 - zt) + d_zt @ p["Uz"].T + d_rt @ p["Ur"].T + d_rhp * rt

        if l2_reg > 0.0:
            for k in ("Wz", "Uz", "Wr", "Ur", "Wh", "Uh", "Wo"):
                loss += 0.5 * l2_reg * float(np.sum(p[k] * p[k]))
                grads[k] += l2_reg * p[k]

        return loss, grads

    def fit(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        *,
        epochs: int = 25,
        batch_size: int = 128,
        lr: float = 5e-3,
        l2_reg: float = 2e-3,
        seed: int = 42,
    ) -> list[float]:
        """Fit strictly on supplied training sequences using Adam + gradient clipping."""
        x_arr = np.asarray(x_train, dtype=np.float64)
        y_arr = np.asarray(y_train, dtype=np.float64).reshape(-1)
        flat = x_arr.reshape(-1, self.input_dim)
        self.feat_mean = np.mean(flat, axis=0)
        self.feat_std = np.maximum(np.std(flat, axis=0), 1e-6)
        x_scaled = self._scale_x(x_arr)

        if self.task == "regression":
            self.y_mean = float(np.mean(y_arr))
            self.y_std = max(float(np.std(y_arr)), 1e-6)
            y_norm = (y_arr - self.y_mean) / self.y_std
        else:
            self.y_mean, self.y_std = 0.0, 1.0
            y_norm = y_arr

        m = {k: np.zeros_like(v) for k, v in self.params.items()}
        v = {k: np.zeros_like(val) for k, val in self.params.items()}
        rng = np.random.default_rng(seed)
        n = len(x_scaled)
        step = 0
        losses: list[float] = []

        for _ in range(epochs):
            perm = rng.permutation(n)
            ep_loss = 0.0
            n_batches = 0
            for start in range(0, n, batch_size):
                idx = perm[start : start + batch_size]
                loss, grads = self._loss_and_grads(x_scaled[idx], y_norm[idx], l2_reg=l2_reg)
                ep_loss += loss
                n_batches += 1
                step += 1
                total_norm = np.sqrt(sum(float(np.sum(g * g)) for g in grads.values()))
                clip = min(1.0, 2.0 / max(total_norm, 1e-9))
                for k, g in grads.items():
                    gc = g * clip
                    m[k] = 0.9 * m[k] + 0.1 * gc
                    v[k] = 0.999 * v[k] + 0.001 * (gc * gc)
                    m_hat = m[k] / (1.0 - 0.9**step)
                    v_hat = v[k] / (1.0 - 0.999**step)
                    self.params[k] -= lr * m_hat / (np.sqrt(v_hat) + 1e-8)
            losses.append(ep_loss / max(1, n_batches))
        return losses

    def predict(self, x: np.ndarray) -> np.ndarray:
        try:
            x_arr = np.asarray(x, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise GRUArtifactError("predict input must be numeric") from exc
        if x_arr.ndim == 2:
            x_arr = x_arr[None, :, :]
        if x_arr.ndim != 3 or x_arr.shape[0] == 0 or x_arr.shape[1] == 0 or x_arr.shape[2] != self.input_dim:
            raise GRUArtifactError(f"predict input shape invalid for input_dim={self.input_dim}: {x_arr.shape}")
        if not np.all(np.isfinite(x_arr)):
            raise GRUArtifactError("predict input contains non-finite values")
        out, _ = self._forward_batch(self._scale_x(x_arr))
        res = out if self.task == "binary" else out * self.y_std + self.y_mean
        if not np.all(np.isfinite(res)):
            raise GRUArtifactError("model produced non-finite output")
        return res

    def to_dict(self) -> dict:
        return {
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "task": self.task,
            "feat_mean": self.feat_mean.tolist(),
            "feat_std": self.feat_std.tolist(),
            "y_mean": self.y_mean,
            "y_std": self.y_std,
            "params": {k: v.tolist() for k, v in self.params.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict) -> CompactGRU:
        if not isinstance(payload, dict):
            raise GRUArtifactError("model payload must be a JSON object")
        input_dim = _validate_positive_int(payload.get("input_dim"), "input_dim")
        hidden_dim = _validate_positive_int(payload.get("hidden_dim"), "hidden_dim")
        task = payload.get("task")
        if task not in ("regression", "binary"):
            raise GRUArtifactError(f"invalid task: {task!r}")
        feat_mean = _validate_finite_array(payload.get("feat_mean"), (input_dim,), "feat_mean")
        feat_std = _validate_finite_array(payload.get("feat_std"), (input_dim,), "feat_std", positive=True)
        try:
            y_mean = float(payload["y_mean"])
            y_std = float(payload["y_std"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GRUArtifactError("y_mean and y_std must be finite numbers") from exc
        if not np.isfinite(y_mean) or not np.isfinite(y_std) or y_std <= 0.0:
            raise GRUArtifactError("y_mean must be finite and y_std must be finite and > 0")
        raw_params = payload.get("params")
        if not isinstance(raw_params, dict):
            raise GRUArtifactError("params must be a JSON object")
        expected = _expected_param_shapes(input_dim, hidden_dim)
        if set(raw_params.keys()) != set(expected.keys()):
            raise GRUArtifactError("params keys do not match GRU specification")
        params = {k: _validate_finite_array(raw_params[k], shp, f"params.{k}") for k, shp in expected.items()}
        obj = cls(input_dim, hidden_dim, task=task)
        obj.feat_mean = feat_mean
        obj.feat_std = feat_std
        obj.y_mean = y_mean
        obj.y_std = y_std
        obj.params = params
        return obj

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")


class EnsembleGRU:
    """Multi-seed average of CompactGRU models to eliminate single-seed initialization variance."""

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 12,
        *,
        task: str = "regression",
        seeds: tuple[int, ...] = (42, 101, 202),
    ) -> None:
        self._seeds = tuple(seeds)
        self.models = [CompactGRU(input_dim, hidden_dim, task=task, seed=s) for s in self._seeds]

    def fit(self, x_train: np.ndarray, y_train: np.ndarray, *, epochs: int = 25, batch_size: int = 128, lr: float = 5e-3, l2_reg: float = 2e-3) -> None:
        seeds = getattr(self, "_seeds", tuple(42 + i * 31 for i in range(len(self.models))))
        for i, m in enumerate(self.models):
            m.fit(x_train, y_train, epochs=epochs, batch_size=batch_size, lr=lr, l2_reg=l2_reg, seed=seeds[i])

    def predict(self, x: np.ndarray) -> np.ndarray:
        if not self.models:
            raise GRUArtifactError("ensemble contains zero models")
        preds = [m.predict(x) for m in self.models]
        out = np.mean(preds, axis=0)
        if not np.all(np.isfinite(out)):
            raise GRUArtifactError("ensemble produced non-finite output")
        return out

    def predict_safe(self, x: np.ndarray) -> tuple[np.ndarray | None, str | None]:
        """Predict with structured abstention on invalid features or non-finite outputs."""
        try:
            return self.predict(x), None
        except GRUArtifactError as exc:
            return None, str(exc)

    def to_dict(self, *, metadata: dict | None = None) -> dict:
        return {
            "schema": "ensemble-gru-weights/1",
            "n_models": len(self.models),
            "metadata": metadata or {},
            "models": [m.to_dict() for m in self.models],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> EnsembleGRU:
        if not isinstance(payload, dict):
            raise GRUArtifactError("ensemble payload must be a JSON object")
        if payload.get("schema") != "ensemble-gru-weights/1":
            raise GRUArtifactError(f"unsupported ensemble schema: {payload.get('schema')!r}")
        raw_models = payload.get("models")
        if not isinstance(raw_models, list) or not raw_models:
            raise GRUArtifactError("ensemble models must be a non-empty list")
        n_models = payload.get("n_models")
        if n_models is not None and (isinstance(n_models, bool) or n_models != len(raw_models)):
            raise GRUArtifactError(f"n_models mismatch: declared {n_models!r}, found {len(raw_models)}")
        models = [CompactGRU.from_dict(m) for m in raw_models]
        spec = (models[0].input_dim, models[0].hidden_dim, models[0].task)
        if any((m.input_dim, m.hidden_dim, m.task) != spec for m in models[1:]):
            raise GRUArtifactError("ensemble member models have inconsistent shapes or tasks")
        obj = cls.__new__(cls)
        obj.models = models
        return obj

    def save_json(self, path: Path, *, metadata: dict | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(metadata=metadata), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load_json(
        cls,
        path: Path,
        *,
        now: object | None = None,
        enforce_expiry: bool = True,
    ) -> tuple[EnsembleGRU, dict]:
        from datetime import UTC, datetime

        from ...domain.model import parse_ts

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GRUArtifactError(f"failed to parse GRU artifact {path}: {exc}") from exc
        meta = payload.get("metadata") if isinstance(payload, dict) else None
        if meta is not None and not isinstance(meta, dict):
            raise GRUArtifactError("ensemble metadata must be a JSON object")
        meta_dict = dict(meta or {})
        if enforce_expiry and meta_dict.get("expires_at"):
            try:
                exp_dt = parse_ts(str(meta_dict["expires_at"]))
            except Exception as exc:
                raise GRUArtifactError(f"invalid expires_at timestamp: {meta_dict['expires_at']!r}") from exc
            ref_now = now if isinstance(now, datetime) else datetime.now(UTC)
            if ref_now > exp_dt:
                raise GRUArtifactError(f"GRU artifact expired at {meta_dict['expires_at']}")
        return cls.from_dict(payload), meta_dict
