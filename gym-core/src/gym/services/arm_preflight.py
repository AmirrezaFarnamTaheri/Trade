"""Standing arm-ready preflight (owner decision OD-2): READY or BLOCKED with reasons. It never arms anything.

Arming itself does not exist yet: it needs the privileged executor path and an owner-set policy. This report is
the checklist that path will require, computed from evidence available today, so the gap is always visible.
A READY result is not permission; only the future privileged approval can arm, and only against a policy file
whose hash is bound into the arm record.

Policy file (written by the owner, never by this code): <data root>/live/arm-policy.json
    {"schema": 1, "loss_cap_quote": "<decimal>", "quote_asset": "USDT|TMN", "venue": "wallex",
     "symbols": ["BTCUSDT", ...], "kill": {"max_loss_quote": "<decimal>", "stale_data_seconds": <int>,
     "max_open_orders": <int>}, "expires_days": <int 1..30>}
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

POLICY = "arm-policy.json"
OBSERVATION_FRESH = timedelta(minutes=5)


def _item(name, ok, detail):
    return {"item": name, "ok": bool(ok), "detail": detail}


def _positive(value) -> bool:
    try:
        number = Decimal(value) if isinstance(value, str) else None
    except InvalidOperation:
        return False
    return number is not None and number.is_finite() and number > 0


def validate_policy(policy: object) -> list[str]:
    """Problems with an owner policy; empty when it is complete and coherent."""
    if not isinstance(policy, dict):
        return ["policy must be a JSON object"]
    problems = []
    expected = {"schema", "loss_cap_quote", "quote_asset", "venue", "symbols", "kill", "expires_days"}
    if set(policy) != expected:
        problems.append(f"policy keys must be exactly {sorted(expected)}")
        return problems
    if policy["schema"] != 1 or policy["venue"] != "wallex" or policy["quote_asset"] not in ("USDT", "TMN"):
        problems.append("schema 1, venue wallex, quote_asset USDT or TMN")
    if not _positive(policy["loss_cap_quote"]):
        problems.append("loss_cap_quote must be a positive decimal string")
    symbols = policy["symbols"]
    if not (isinstance(symbols, list) and 1 <= len(symbols) <= 20
            and all(isinstance(s, str) and re.fullmatch(r"[A-Z0-9]{2,24}", s) for s in symbols)):
        problems.append("symbols must list 1..20 market symbols")
    elif not all(s.endswith(policy["quote_asset"]) for s in symbols):
        problems.append("every symbol must be quoted in quote_asset")
    kill = policy["kill"]
    if not (isinstance(kill, dict) and set(kill) == {"max_loss_quote", "stale_data_seconds", "max_open_orders"}):
        problems.append("kill must have max_loss_quote, stale_data_seconds, max_open_orders")
    else:
        if not _positive(kill["max_loss_quote"]) or (_positive(policy["loss_cap_quote"])
                                                     and Decimal(kill["max_loss_quote"]) > Decimal(policy["loss_cap_quote"])):
            problems.append("kill.max_loss_quote must be positive and at most loss_cap_quote")
        if type(kill["stale_data_seconds"]) is not int or not 1 <= kill["stale_data_seconds"] <= 300:
            problems.append("kill.stale_data_seconds must be 1..300")
        if type(kill["max_open_orders"]) is not int or not 1 <= kill["max_open_orders"] <= 10:
            problems.append("kill.max_open_orders must be 1..10")
    if type(policy["expires_days"]) is not int or not 1 <= policy["expires_days"] <= 30:
        problems.append("expires_days must be 1..30 (arming always expires on its own)")
    return problems


def _policy(root: Path):
    path = root / POLICY
    if not path.is_file():
        return _item("owner_policy", False, f"no {POLICY}: the owner has not set a loss cap and kill rules"), None
    raw = path.read_bytes()
    try:
        policy = json.loads(raw)
    except ValueError:
        return _item("owner_policy", False, f"{POLICY} is not valid JSON"), None
    problems = validate_policy(policy)
    digest = hashlib.sha256(raw).hexdigest()
    return _item("owner_policy", not problems, "; ".join(problems) or f"complete; sha256 {digest[:16]}"), digest


def _executor_service():
    if os.name != "nt":
        return _item("executor_service", False, "the executor runs only on Windows")
    try:
        out = subprocess.run(["sc", "query", "TradingGYMExecutor"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return _item("executor_service", False, "service state unreadable")
    if "RUNNING" in out:
        return _item("executor_service", True, "installed and running")
    return _item("executor_service", False, "not installed" if "1060" in out else "installed but not running")


def _account(root: Path, now: datetime):
    path = root / "external_journal.db"
    if not path.is_file():
        return _item("fresh_account_observation", False, "no account observation recorded")
    from .external_journal import ExternalJournal
    try:
        with ExternalJournal(path) as journal:
            snapshot = journal.latest_snapshot()
    except (ValueError, OSError):
        return _item("fresh_account_observation", False, "account journal unreadable")
    if not snapshot:
        return _item("fresh_account_observation", False, "no account observation recorded")
    at = datetime.fromisoformat(str(snapshot.get("observed_at")))
    age = now - at
    return _item("fresh_account_observation", age <= OBSERVATION_FRESH,
                 f"newest observation {age.total_seconds() / 60:.0f} min old (needs <= {OBSERVATION_FRESH.seconds // 60})")


def preflight(root: Path, now: datetime) -> dict:
    from .doctor import diagnose
    health = {c["check"]: c for c in diagnose(root, now, quick=True)["checks"]}
    policy_item, policy_digest = _policy(root)
    feed = health.get("collector_feed", {})
    backup = health.get("backup_receipts", {})
    items = [
        policy_item,
        _executor_service(),
        _item("stop_gate_responsive", False, "not probed from the unprivileged workspace; the privileged arm path must ping it"),
        _item("credentials_present", (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TradingGYM" / "keys" /
                                      "wallex-trade.dpapi").is_file(), "a stored trade key (gymctl key set trade)"),
        _account(root, now),
        _item("reconciliation_clean", False, "no executor reconciliation record exists yet"),
        _item("collector_feed_fresh", feed.get("status") == "PASS", feed.get("detail", "no quote store")),
        _item("recent_backup", backup.get("status") == "PASS", backup.get("detail", "no backup receipts")),
        _item("no_open_incident", all(c["status"] != "FAIL" for c in health.values()),
              "no failing health check" if all(c["status"] != "FAIL" for c in health.values()) else "a health check fails"),
    ]
    blocked = [i["item"] for i in items if not i["ok"]]
    return {"as_of": now.isoformat(), "state": "BLOCKED" if blocked else "READY", "blocked_by": blocked,
            "items": items, "policy_sha256": policy_digest, "arms": False, "funded_authority": False,
            "note": "READY is a checklist result, not permission. Arming needs the privileged path and an owner click."}
