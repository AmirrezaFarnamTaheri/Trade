"""Content-addressed model artifacts bound to recorded trials and schemas.

- Every fit is a trial: `register` requires a trial-ledger attempt recorded with source "model-fit" for the same
  question, so the fit raises that question's trial count and the deflated-Sharpe N.
- An artifact is plain JSON (a logistic baseline or a tree dump); its SHA-256 is its id. The feature-schema and
  cost-model digests are bound at registration, and `identity` returns the three digests for a run's inputs.
- `load` never raises for a bad artifact: it returns ABSTAIN with the reason (missing, corrupt, expired,
  incompatible schema or cost model), so a caller falls back to the base strategy. A model never places orders.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ..domain.model import iso, parse_ts
from ..domain.strategy import digest

MAX_ARTIFACT_BYTES = 512 * 1024  # A 300 KB tree dump is the target; this is the hard ceiling
KINDS = frozenset(("logistic", "tree-dump"))


class ArtifactRegistry:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.dir = self.root / "models"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.root / "models.sqlite3", isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS artifacts(sha256 TEXT PRIMARY KEY, kind TEXT NOT NULL, "
            "schema_digest TEXT NOT NULL, cost_digest TEXT NOT NULL, trial_attempt TEXT NOT NULL, "
            "registered_at TEXT NOT NULL, expires_at TEXT NOT NULL)")
        self.conn.execute("CREATE TRIGGER IF NOT EXISTS artifacts_no_update BEFORE UPDATE ON artifacts "
                          "BEGIN SELECT RAISE(ABORT, 'artifacts are immutable'); END")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def register(self, artifact: dict, *, kind: str, feature_schema: dict, cost_digest: str, trial_ledger,
                 trial_attempt: str, now: datetime, expires_at: datetime) -> str:
        """Store an artifact whose fit was already recorded as a trial; returns its SHA-256 id."""
        if kind not in KINDS:
            raise ValueError(f"artifact kind must be one of {sorted(KINDS)}")
        if not re.fullmatch(r"[0-9a-f]{16,64}", cost_digest or ""):
            raise ValueError("cost model digest required")
        if expires_at <= now:
            raise ValueError("an artifact must expire after it is registered")
        row = trial_ledger.conn.execute("SELECT source FROM trial_attempts WHERE attempt_id=?",
                                        (trial_attempt,)).fetchone()
        if row is None or row[0] != "model-fit":
            raise ValueError("record the fit in the trial ledger (source model-fit) before registering it")
        raw = json.dumps(artifact, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds the size ceiling")
        sha = hashlib.sha256(raw).hexdigest()
        target = self.dir / f"{sha}.json"
        if not target.exists():
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(raw)
            tmp.replace(target)
        self.conn.execute("INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?,?)",
                          (sha, kind, digest(feature_schema), cost_digest, trial_attempt, iso(now),
                           iso(expires_at)))
        return sha

    def load(self, sha: str, *, feature_schema: dict, cost_digest: str, now: datetime) -> dict:
        """{"status": "READY", "artifact": ...} or {"status": "ABSTAIN", "reason": ...}; never raises for bad data."""
        row = self.conn.execute("SELECT kind, schema_digest, cost_digest, expires_at FROM artifacts WHERE sha256=?",
                                (sha,)).fetchone()
        if row is None:
            return {"status": "ABSTAIN", "reason": "unregistered"}
        kind, schema, cost, expires = row
        try:
            raw = (self.dir / f"{sha}.json").read_bytes()
        except OSError:
            return {"status": "ABSTAIN", "reason": "missing"}
        if hashlib.sha256(raw).hexdigest() != sha:
            return {"status": "ABSTAIN", "reason": "corrupt"}
        if now >= parse_ts(expires):
            return {"status": "ABSTAIN", "reason": "expired"}
        if schema != digest(feature_schema):
            return {"status": "ABSTAIN", "reason": "incompatible feature schema"}
        if cost != cost_digest:
            return {"status": "ABSTAIN", "reason": "incompatible cost model"}
        return {"status": "READY", "kind": kind, "artifact": json.loads(raw)}

    def identity(self, sha: str) -> dict:
        """The digests a run binds into its inputs when a model overlay is used (absent otherwise)."""
        row = self.conn.execute("SELECT schema_digest, cost_digest FROM artifacts WHERE sha256=?", (sha,)).fetchone()
        if row is None:
            raise ValueError("unregistered artifact")
        return {"model_artifact": sha, "model_feature_schema": row[0], "model_cost_model": row[1]}
