"""Validated paths, run artifacts and immutable operator-decision storage."""
import json
import os
import re
import tempfile
import threading
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


_RUN_FILE = re.compile(r"[0-9a-f]{16}\.json")
_SUMMARIES: dict[str, tuple[int, dict]] = {}  # run rows keyed by path, valid while mtime matches
_SUMMARY_LOCK = threading.Lock()


def list_runs(root: Path, limit: int = 50, offset: int = 0, symbol: str | None = None, strategy: str | None = None) -> list[dict]:
    """Newest runs first, optionally filtered. Polled every few seconds: only changed files are parsed."""
    try:
        with os.scandir(root) as scan:  # DirEntry.stat() comes from the directory listing on Windows
            entries = [entry for entry in scan if _RUN_FILE.fullmatch(entry.name)]
    except FileNotFoundError:
        return []
    entries.sort(key=lambda entry: entry.stat().st_mtime_ns, reverse=True)
    if symbol is None and strategy is None:
        entries = entries[offset:offset + limit]
        offset = 0
    rows = []
    with _SUMMARY_LOCK:
        for entry in entries:
            stamp, cached = entry.stat().st_mtime_ns, _SUMMARIES.get(entry.path)
            if cached is None or cached[0] != stamp:
                record = json.loads(Path(entry.path).read_text("utf-8"))
                cached = stamp, {"run_id": record["run_id"], "inputs": record["inputs"], "end": record["result"]["end"]}
                _SUMMARIES[entry.path] = cached
            inputs = cached[1]["inputs"]
            if (symbol is None or inputs.get("symbol") == symbol) and (strategy is None or inputs.get("strategy") == strategy):
                if offset:
                    offset -= 1
                elif len(rows) < limit:
                    rows.append(cached[1])
                else:
                    break
        if len(_SUMMARIES) > 4 * len(entries) + 1000:  # forget deleted runs once the cache clearly outgrows the folder
            for stale in _SUMMARIES.keys() - {entry.path for entry in entries}:
                del _SUMMARIES[stale]
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
