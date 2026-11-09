"""Per-provider token and cost ledger for model completions (advisory research only)."""
import sqlite3
from decimal import Decimal
from pathlib import Path

from ..domain.model import iso
from .collector import now_utc

# A runaway loop or a misconfigured preset stops here, before the provider's own limit. Cost caps start unset
# because many completions report no cost; set them once a paid preset is in use.
DEFAULT_LIMITS = {"daily_calls": 200, "monthly_calls": 2000, "daily_cost": None, "monthly_cost": None}


class CapReached(ValueError):
    """A configured call or cost cap would be exceeded; nothing was sent."""


class ModelUsage:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS usage(at TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            preset TEXT, input_tokens INTEGER, output_tokens INTEGER, cost TEXT, cost_source TEXT)""")
        self.conn.execute("CREATE TABLE IF NOT EXISTS limits(name TEXT PRIMARY KEY, value TEXT)")

    def limits(self) -> dict:
        stored = dict(self.conn.execute("SELECT name, value FROM limits").fetchall())
        return {name: stored.get(name, default) for name, default in DEFAULT_LIMITS.items()}

    def set_limits(self, value: dict) -> dict:
        """Replace named caps; null removes a cap. Call caps are whole numbers, cost caps exact decimals."""
        if not isinstance(value, dict) or not value or set(value) - set(DEFAULT_LIMITS):
            raise ValueError(f"limits must name only {', '.join(DEFAULT_LIMITS)}")
        rows = []
        for name, cap in value.items():
            if cap is not None:
                if name.endswith("_calls") and (type(cap) is not int or not 0 <= cap <= 10**6):
                    raise ValueError(f"{name} must be a whole number 0..1000000 or null")
                if name.endswith("_cost"):
                    try:
                        cap = str(Decimal(str(cap)))
                    except ArithmeticError:
                        raise ValueError(f"{name} must be a decimal or null") from None
                    if not Decimal(cap).is_finite() or Decimal(cap) < 0:
                        raise ValueError(f"{name} must be a non-negative decimal or null")
            rows.append((name, None if cap is None else str(cap)))
        self.conn.executemany("INSERT OR REPLACE INTO limits VALUES(?,?)", rows)
        return self.limits()

    def check(self):
        """Raise CapReached before a completion would exceed a daily or monthly cap (UTC calendar periods)."""
        now = iso(now_utc())
        for period, prefix in (("daily", now[:10]), ("monthly", now[:7])):
            calls, costs = self.conn.execute("SELECT count(*), group_concat(cost, ' ') FROM usage WHERE at >= ?",
                                             (prefix,)).fetchone()
            limits = self.limits()
            call_cap, cost_cap = limits[f"{period}_calls"], limits[f"{period}_cost"]
            if call_cap is not None and calls >= int(call_cap):
                raise CapReached(f"{period} model call cap reached ({calls}/{call_cap}); raise it with the usage limits control")
            spent = sum((Decimal(c) for c in (costs or "").split()), Decimal(0))
            if cost_cap is not None and spent >= Decimal(cost_cap):
                raise CapReached(f"{period} model cost cap reached ({spent}/{cost_cap}); calls without a reported cost are not counted")

    def close(self):
        self.conn.close()

    def record(self, result: dict):
        """Store one completion's usage; missing figures stay NULL rather than zero."""
        model, usage = result.get("model") or {}, result.get("usage") or {}
        if not isinstance(model.get("provider"), str) or not isinstance(model.get("id"), str):
            return
        cost = (usage.get("cost") or {}).get("total")
        tokens = [usage.get(key) if isinstance(usage.get(key), int) else None for key in ("input", "output")]
        self.conn.execute("INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)",
                          (iso(now_utc()), model["provider"][:100], model["id"][:200], str(model.get("preset", ""))[:100],
                           *tokens, None if cost is None else str(Decimal(str(cost))), str(usage.get("costSource", "UNKNOWN"))[:40]))

    def summary(self) -> dict:
        rows = self.conn.execute("""SELECT provider, model, count(*), sum(input_tokens), sum(output_tokens),
            group_concat(cost, ' '), sum(cost IS NULL), min(at), max(at) FROM usage GROUP BY provider, model ORDER BY provider, model""").fetchall()
        out = []
        for provider, model, calls, tokens_in, tokens_out, costs, unknown, first, last in rows:
            total = sum((Decimal(c) for c in (costs or "").split()), Decimal(0))
            out.append({"provider": provider, "model": model, "calls": calls, "input_tokens": tokens_in, "output_tokens": tokens_out,
                        "cost": str(total), "calls_without_cost": unknown, "first": first, "last": last})
        return {"by_model": out, "limits": self.limits(),
                "note": "Costs are provider-reported or SDK catalog estimates; check the provider's bill."}
