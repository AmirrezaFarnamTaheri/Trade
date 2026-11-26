"""Validated paths, run artifacts and immutable operator-decision storage."""
import json
import os
import re
import tempfile
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..domain.model import iso, strict_loads
from ..domain.strategy import digest


def run_path(root, run_id):
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        raise ValueError("run id must be 16 lowercase hex digits")
    return Path(root) / (run_id + ".json")


def _same_run(path, text):
    stored = path.read_text("utf-8")
    if stored == text:
        return True
    # Direct and scheduled workflows can serialize the same mapping in different key orders.
    try:
        return json.dumps(strict_loads(stored), sort_keys=True, allow_nan=False) == json.dumps(
            strict_loads(text), sort_keys=True, allow_nan=False)
    except ValueError:
        return False


def save_run(out: dict, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = run_path(root, out["run_id"])
    text = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    if path.exists():
        if not _same_run(path, text):
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
            if not _same_run(path, text):
                raise ValueError(f"run {out['run_id']} already exists with different results") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


_RUN_FILE = re.compile(r"[0-9a-f]{16}\.json")
_SUMMARIES: dict[str, tuple[int, dict, dict]] = {}  # run rows and filter metadata, valid while mtime matches
_SUMMARY_LOCK = threading.Lock()
RUN_FILTER_FIELDS = ("date_from", "date_to", "model", "fee_rate", "evidence_stage", "benchmark", "data_gaps", "status")


def _run_filter_metadata(record):
    inputs, result = record["inputs"], record["result"]
    end = result.get("end") or {}
    cost = inputs.get("cost") or {}
    evidence = record.get("evidence") or {}
    return {
        "date": (inputs.get("from") or "")[:10],
        "model": inputs.get("position_model") or (inputs.get("params") or {}).get("position_model") or inputs.get("engine"),
        "fee_rate": cost.get("fee_rate", inputs.get("fee_rate")),
        "evidence_stage": evidence.get("evidence_tier") or record.get("evidence_tier"),
        "benchmark": tuple((record.get("baselines") or {}).keys()),
        "data_gaps": evidence.get("data_gap_status") or result.get("data_gap_status"),
        "status": end.get("valuation_status") or result.get("status"),
    }


def _matches_run_filters(metadata, filters):
    for field, value in filters.items():
        if field == "date_from":
            if not metadata["date"] or metadata["date"] < value:
                return False
        elif field == "date_to":
            if not metadata["date"] or metadata["date"] > value:
                return False
        elif field == "benchmark":
            if value.casefold() not in {str(name).casefold() for name in metadata["benchmark"] or ("UNKNOWN",)}:
                return False
        elif field == "fee_rate" and metadata[field] is not None:
            try:
                if Decimal(str(metadata[field])) != Decimal(value):
                    return False
            except InvalidOperation:
                return False
        elif str(metadata[field] if metadata[field] is not None else "UNKNOWN").casefold() != value.casefold():
            return False
    return True


def list_runs(root: Path, limit: int = 50, offset: int = 0, symbol: str | None = None, strategy: str | None = None,
              filters: dict | None = None) -> list[dict]:
    """Newest runs first, optionally filtered. Polled every few seconds: only changed files are parsed."""
    try:
        with os.scandir(root) as scan:  # DirEntry.stat() comes from the directory listing on Windows
            entries = [entry for entry in scan if _RUN_FILE.fullmatch(entry.name)]
    except FileNotFoundError:
        return []
    entries.sort(key=lambda entry: entry.stat().st_mtime_ns, reverse=True)
    if symbol is None and strategy is None and not filters:
        entries = entries[offset:offset + limit]
        offset = 0
    rows = []
    with _SUMMARY_LOCK:
        for entry in entries:
            stamp, cached = entry.stat().st_mtime_ns, _SUMMARIES.get(entry.path)
            if cached is None or cached[0] != stamp:
                record = json.loads(Path(entry.path).read_text("utf-8"))
                cached = (stamp, {"run_id": record["run_id"], "inputs": record["inputs"], "end": record["result"]["end"]},
                          _run_filter_metadata(record))
                _SUMMARIES[entry.path] = cached
            inputs = cached[1]["inputs"]
            if ((symbol is None or inputs.get("symbol") == symbol or symbol in (inputs.get("symbols") or ()))
                    and (strategy is None or inputs.get("strategy") == strategy)
                    and _matches_run_filters(cached[2], filters or {})):
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
        portfolio = out["inputs"].get("kind") == "portfolio"
        if portfolio and (out.get("mode") != "PORTFOLIO" or any(k in out for k in ("baselines", "ranking", "fx"))):
            raise ValueError("portfolio cannot contain independent replay comparisons")
        if live_session and (out["baselines"] != {} or out["fx"] is not None or "ranking" in out):
            raise ValueError("live session cannot contain replay comparisons")
        outputs = out["result"] if live_session or portfolio else {k: out[k] for k in ("result", "baselines", "ranking", "fx")}
        if (out["run_id"] != run_id or digest(out["inputs"])[:16] != run_id
                or digest(outputs)[:16] != out["outputs_digest"]):
            raise ValueError("run digest mismatch")
        if out["inputs"]["store"] != store:
            raise ValueError("run source store mismatch")
        if portfolio:
            from ..domain.performance import performance, sampled_drawdown
            out["performance"] = {k: v for k, v in performance(out, sampled_drawdown(out)).items() if k not in ("ledger", "trades")}
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
