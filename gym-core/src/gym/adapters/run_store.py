"""Validated paths, run artifacts and immutable operator-decision storage."""
import json
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path

from ..domain.model import iso
from ..domain.strategy import digest


def run_path(root, run_id):
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        raise ValueError("run id must be 16 lowercase hex digits")
    return Path(root) / (run_id + ".json")


def save_run(out: dict, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = run_path(root, out["run_id"])
    text = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    if path.exists():
        if path.read_text("utf-8") != text:
            raise ValueError(f"run {out['run_id']} already exists with different results")
        return path
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as f:
            temporary = Path(f.name)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_text("utf-8") != text:
                raise ValueError(f"run {out['run_id']} already exists with different results") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def list_runs(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        if not re.fullmatch(r"[0-9a-f]{16}\.json", path.name):
            continue
        record = json.loads(path.read_text("utf-8"))
        rows.append({"run_id": record["run_id"], "inputs": record["inputs"], "end": record["result"]["end"]})
        if len(rows) == 50:
            break
    return rows


def load_run(root: Path, run_id: str) -> dict:
    path = run_path(root, run_id)
    record = json.loads(path.read_text("utf-8"))
    evidence_path = path.with_suffix(".evidence.json")
    record["evidence"] = json.loads(evidence_path.read_text("utf-8")) if evidence_path.exists() else None
    record["capital_decisions"] = [
        json.loads(decision.read_text("utf-8"))
        for decision in sorted(root.glob(run_id + "-*.decision.json"))
    ]
    return record


def load_verified_run(root, run_id, *, store):
    """Read one bounded native artifact once; fingerprints are integrity, not source authentication."""
    if type(run_id) is not str or store not in ("live", "demo"):
        raise ValueError("invalid run reference or store")
    path = run_path(root, run_id)
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 16 * 1024 * 1024:
        raise ValueError("run source must be a bounded regular artifact")
    try:
        with path.open("rb") as source:
            raw = source.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("run source exceeds size bound")
        out = json.loads(raw)
        live_session = out["inputs"].get("kind") == "live-session"
        if live_session and (out["baselines"] != {} or out["fx"] is not None or "ranking" in out):
            raise ValueError("live session cannot contain replay comparisons")
        outputs = out["result"] if live_session else {k: out[k] for k in ("result", "baselines", "ranking", "fx")}
        if (out["run_id"] != run_id or digest(out["inputs"])[:16] != run_id
                or digest(outputs)[:16] != out["outputs_digest"]):
            raise ValueError("run digest mismatch")
        if out["inputs"]["store"] != store:
            raise ValueError("run source store mismatch")
        return out
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, KeyError, TypeError, AttributeError):
        raise ValueError("invalid run artifact structure") from None

def record_decision(root, out, claim, cap, currency, note, now):
    cap = Decimal(cap)
    if not cap.is_finite() or cap < 0 or claim not in ("NONE", "EXPERIMENTAL"):
        raise ValueError("claim must be NONE/EXPERIMENTAL; cap must be finite and nonnegative")
    if currency not in ("USDT", "TMN") or not note.strip():
        raise ValueError("currency must be USDT/TMN and a decision note is required")
    if out["inputs"]["store"] == "demo" and claim != "NONE":
        raise ValueError("DEMO cannot support any strategy claim")
    if (out["inputs"]["store"] == "demo" or claim == "NONE") and cap:
        raise ValueError("DEMO/NONE cannot support any capital")
    rec = {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"], "at": iso(now),
           "claim": claim, "full_loss_ceiling": str(cap), "currency": currency, "note": note,
           "permission": "RECORD_ONLY_NOT_EXECUTION_AUTHORITY"}
    path = run_path(root, out["run_id"]).with_name(out["run_id"] + "-" + digest(rec)[:16] + ".decision.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Each decision is immutable; separate files avoid concurrent JSONL append corruption.
    with path.open("x", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return path
