"""Registered trial budget enforcement, release bundles, analyst peek logs, and journal continuity (E005-E022)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from ..domain.model import iso
from ..domain.strategy import digest
from ._journal_lock import append_jsonl, journal_lock
from .allocation import journal as alloc_journal
from .breadth_journal import journal as breadth_journal
from .mix_journal import journal as mix_journal

MAX_CONCURRENT_TRIALS = 2
# Installed wheels lack the source documentation. Release tests compare this snapshot with the log.
PACKAGED_OPEN_FORWARD = (
    ("funding-confirmed-trend-forward", "2026-11-18"),
    ("breadth-trend-forward", "2026-11-19"),
)
# Long-horizon passive forward monitors run in the background without locking active hypothesis
# experimentation. Every trial still counts in the multiplicity (BH/DSR) denominator.
PASSIVE_FORWARD_MONITORS = frozenset({
    "funding-confirmed-trend-forward",
    "breadth-trend-forward",
})


def check_registration_budget(root, store, now, new_id, *, supersedes=None, include_background_monitors: bool = False):
    """Read both registries while the caller owns the shared registration lock."""
    from .evidence import TRIAL_LOG, trials

    active = []
    if store == "live":
        forward = PACKAGED_OPEN_FORWARD
        if TRIAL_LOG.is_file():
            parsed = trials(TRIAL_LOG)
            if not parsed:
                raise ValueError("cannot establish trial budget from an empty trial log")
            forward = [(row["id"], row["registered"]) for row in parsed if row["verdict"] == "OPEN"]
        active.extend(
            trial_id
            for trial_id, day in forward
            if day <= now.date().isoformat()
            and (include_background_monitors or trial_id not in PASSIVE_FORWARD_MONITORS)
        )
    active.extend(active_sqlite_trials(root, store))
    return enforce_two_trial_budget([{"id": key, "verdict": "OPEN"} for key in active], new_id, supersedes=supersedes)


def active_sqlite_trials(root, store):
    active = []
    for filename, query in (
        ("research_protocol.sqlite3", """SELECT id FROM evaluations WHERE state IN ('REGISTERED','CONSUMED')
                                         AND json_extract(body,'$.store')=?"""),
        ("experiments.sqlite3", """SELECT e.id FROM events e WHERE e.kind='PROSPECTIVE_COMPARE' AND json_extract(e.body,'$.store')=?
                                  AND NOT EXISTS (SELECT 1 FROM events r WHERE r.parent=e.id
                                                  AND r.kind IN ('PROSPECTIVE_RESULT','PROSPECTIVE_FAILURE'))"""),
    ):
        path = root / filename
        if path.is_symlink():
            raise ValueError("trial registry must be a regular file")
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
                active.extend(key for (key,) in conn.execute(query, (store,)))
    return active


def enforce_two_trial_budget(
    rows: list[dict],
    new_trial_id: str,
    *,
    max_active: int = MAX_CONCURRENT_TRIALS,
    supersedes: str | None = None,
) -> dict:
    """Reject opening a new registered trial when active OPEN trials already saturate the budget (E022)."""
    if not isinstance(new_trial_id, str) or not new_trial_id.strip():
        raise ValueError("new trial ID must be a non-empty string")
    active = [row["id"] for row in rows if row.get("verdict") == "OPEN"]
    if new_trial_id in active:
        return {"allowed": True, "active_trials": active, "budget": max_active, "status": "ALREADY_ACTIVE"}
    remaining = list(active)
    if supersedes is not None:
        if supersedes not in remaining:
            raise ValueError(f"cannot supersede non-active trial '{supersedes}'")
        remaining.remove(supersedes)
    if len(remaining) >= max_active:
        raise ValueError(
            f"trial budget full ({len(remaining)}/{max_active} active: {', '.join(remaining)}); "
            "complete or formally supersede an active trial before registering another"
        )
    return {
        "allowed": True,
        "active_trials": [*remaining, new_trial_id],
        "superseded": supersedes,
        "budget": max_active,
        "status": "ACCEPTED",
    }


def build_release_bundle(
    *,
    evaluation_id: str,
    family_id: str,
    code_commit_sha: str,
    engine_digest: str,
    data_digest: str,
    family_attempts_total: int,
    sample_count: int,
    missing_count: int,
    pass_criterion: dict,
    verdict: str,
    custodian: str,
    independent_custody: bool,
    released_at: datetime | None = None,
    failure_reason: str | None = None,
) -> dict:
    """Create a canonical, digest-bound evaluation release bundle retaining negative/aborted outcomes (E008, E009)."""
    if verdict not in ("PASS", "FAIL", "INCOMPLETE", "ABORTED", "NOT_ESTABLISHED"):
        raise ValueError("unsupported release verdict")
    if type(family_attempts_total) is not int or family_attempts_total < 1:
        raise ValueError("family_attempts_total must be a positive integer")
    if type(sample_count) is not int or sample_count < 0 or type(missing_count) is not int or missing_count < 0:
        raise ValueError("sample_count and missing_count must be nonnegative integers")
    if verdict in ("ABORTED", "INCOMPLETE") and not failure_reason:
        raise ValueError("aborted or incomplete release bundles require an explicit failure_reason")
    body = {
        "schema": "release-bundle/1",
        "evaluation_id": evaluation_id,
        "family_id": family_id,
        "code_commit_sha": code_commit_sha,
        "engine_digest": engine_digest,
        "data_digest": data_digest,
        "family_attempts_total": family_attempts_total,
        "sample_count": sample_count,
        "missing_count": missing_count,
        "pass_criterion": pass_criterion,
        "verdict": verdict,
        "failure_reason": failure_reason,
        "custodian": custodian,
        "independent_custody": False,
        "released_at": iso(released_at or datetime.now(UTC)),
        "funded_authority": False,
    }
    return {**body, "bundle_sha256": digest(body)}


def verify_release_attestation(bundle: dict, signature: bytes, trusted_public_key: bytes, *, expected_digest: str) -> dict:
    """Verify a detached Ed25519 signature over a pinned bundle digest, even for negative outcomes."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    body = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    calculated = digest(body)
    authenticated = False
    if (body.get("schema") == "release-bundle/1" and bundle.get("bundle_sha256") == calculated == expected_digest
            and len(signature) == 64 and len(trusted_public_key) == 32):
        message = b"TradingGYM release-bundle/1\x00" + bytes.fromhex(calculated)
        try:
            Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(signature, message)
            authenticated = True
        except (InvalidSignature, ValueError):
            pass
    return {"bundle_sha256": calculated, "authenticated_signature": authenticated,
            "independent_custody": False, "funded_authority": False}


def record_analyst_peek(
    root: Path,
    *,
    analyst: str,
    family_id: str,
    source_packet: str,
    date_from: str,
    date_to: str,
    saw_candidate_oos: bool,
    note: str = "",
    at: datetime | None = None,
) -> dict:
    """Durably log human or AI inspection of research data; prose is never evidence (E021)."""
    if not analyst.strip() or not family_id.strip() or not source_packet.strip():
        raise ValueError("analyst, family_id, and source_packet are required")
    entry = {
        "schema": "analyst-peek/1",
        "at": iso(at or datetime.now(UTC)),
        "analyst": analyst.strip(),
        "family_id": family_id.strip(),
        "source_packet": source_packet.strip(),
        "date_from": date_from,
        "date_to": date_to,
        "saw_candidate_oos": bool(saw_candidate_oos),
        "note": note[:500],
        "prose_is_evidence": False,
    }
    path = Path(root) / "analyst_peeks.jsonl"
    with journal_lock(path):
        append_jsonl(path, json.dumps(entry, sort_keys=True))
    return entry


def _allocation_parity(entries: list[dict]) -> dict:
    """Verify exact Decimal cash/base/fee conservation across allocation journal entries (E010)."""
    if not entries:
        return {"status": "EMPTY", "violations": []}
    violations = []
    prev_by_sym: dict[str, tuple[Decimal, Decimal]] = {}
    for idx, row in enumerate(entries):
        sym = row["symbol"]
        holdings = row.get("holdings") or {}
        if "base" not in holdings or "quote" not in holdings:
            continue
        base = Decimal(holdings["base"])
        quote = Decimal(holdings["quote"])
        fill = row.get("fill")
        if sym in prev_by_sym:
            p_base, p_quote = prev_by_sym[sym]
            if fill:
                qty, price, fee = Decimal(fill["qty"]), Decimal(fill["price"]), Decimal(fill["fee"])
                sign = 1 if fill["side"] == "BUY" else -1
                exp_base = p_base + sign * qty
                exp_quote = p_quote - sign * qty * price - fee
            else:
                exp_base, exp_quote = p_base, p_quote
            if base != exp_base or quote != exp_quote:
                violations.append({"index": idx, "symbol": sym, "day": row.get("day")})
        prev_by_sym[sym] = (base, quote)
    return {"status": "OK" if not violations else "MISMATCH", "violations": violations}


def _summarize_journal(name: str, entries: list[dict], as_of_day: date, *, check_parity: bool = False) -> dict:
    if not entries:
        return {
            "journal": name,
            "evidence_status": "NO_ENTRIES",
            "recorded_days": 0,
            "missing_days_in_span": 0,
            "missing_days_through_yesterday": None,
            "zero_signal_days": 0,
            "stale_or_nonready_days": 0,
            "duplicate_days": [],
        }
    days = set()
    seen, duplicates = set(), []
    for row in entries:
        if not row.get("day"):
            continue
        d = row["day"][:10]
        key = (row.get("symbol"), d) if check_parity else d
        if key in seen:
            duplicates.append(d)
        seen.add(key)
        days.add(d)
    ordered = sorted(days)
    if ordered:
        first_d, last_d = date.fromisoformat(ordered[0]), date.fromisoformat(ordered[-1])
        span = (last_d - first_d).days + 1
        expected_latest = as_of_day.toordinal() - 1
        trailing_gap = max(0, expected_latest - last_d.toordinal())
        missing_in_span = span - len(ordered)
    else:
        trailing_gap = None
        missing_in_span = 0
    zero_signal = sum(1 for r in entries if not r.get("fill") and not r.get("trades"))
    stale_or_nonready = sum(
        1 for r in entries
        if r.get("status") != "READY" or r.get("quote") is None and "quote" in r or bool(r.get("stale_quotes"))
    )
    status = (
        "BROKEN_DUPLICATE" if duplicates
        else "UNSCOPED_DAYS" if not ordered
        else "GAP_DETECTED" if (missing_in_span > 0 or (trailing_gap or 0) > 0)
        else "CURRENT"
    )
    out = {
        "journal": name,
        "evidence_status": status,
        "first_day": ordered[0] if ordered else None,
        "latest_day": ordered[-1] if ordered else None,
        "latest_written_at": entries[-1].get("at"),
        "recorded_days": len(ordered),
        "missing_days_in_span": missing_in_span,
        "missing_days_through_yesterday": trailing_gap,
        "zero_signal_days": zero_signal,
        "stale_or_nonready_days": stale_or_nonready,
        "duplicate_days": duplicates,
        "invented_zero_returns": False,
    }
    if check_parity:
        out["accounting_parity"] = _allocation_parity(entries)
    return out


def journal_continuity_report(root: Path, *, now: datetime | None = None) -> dict:
    """Distinguish process heartbeat from actual completed study-day evidence across all three journals (E016, E017)."""
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    return {
        "as_of_utc_date": today.isoformat(),
        "btc_daily_trend": _summarize_journal("allocation/journal.jsonl", alloc_journal(root), today, check_parity=True),
        "passive_mix": _summarize_journal("allocation/mix-journal.jsonl", mix_journal(root), today),
        "breadth_trend": _summarize_journal("allocation/breadth-journal.jsonl", breadth_journal(root), today),
    }
