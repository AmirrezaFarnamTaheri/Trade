"""Per-provider token and cost ledger for model completions (advisory research only)."""
import sqlite3
from decimal import Decimal
from pathlib import Path

from ..domain.model import iso
from .collector import now_utc


class ModelUsage:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS usage(at TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            preset TEXT, input_tokens INTEGER, output_tokens INTEGER, cost TEXT, cost_source TEXT)""")

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
        return {"by_model": out, "note": "Costs are provider-reported or SDK catalog estimates; check the provider's bill."}
