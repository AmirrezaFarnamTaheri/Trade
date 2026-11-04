"""Bounded native decision-prefix and prehistory sensitivity diagnostics."""
from datetime import timedelta
import re

from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .collector import now_utc
from .data_portal import DataPortal
from .paper import run
from .rules import RuleService
from .session import ENGINE_VERSION


class _PrefixPortal(DataPortal):
    def __init__(self, db, cutoff):
        super().__init__(db)
        self.cutoff = cutoff

    def tops(self, symbol, start, end):
        end = min(end, self.cutoff)
        return super().tops(symbol, start, end) if start < end else []


def _known(decisions, cutoff):
    # Outcome marks are later evaluation evidence, not decision-time state.
    return [{k: v for k, v in row.items() if k != "marks"}
            for row in decisions if instant(row["t"]) < cutoff]


def _compare(expected, actual):
    differences = []
    for i in range(max(len(expected), len(actual))):
        left = expected[i] if i < len(expected) else None
        right = actual[i] if i < len(actual) else None
        if left != right:
            differences.append({"index": i, "expected_at": left and left["t"], "actual_at": right and right["t"],
                                "expected_digest": digest(left), "actual_digest": digest(right)})
    return {"status": "DIFFERENT" if differences else "MATCH" if expected else "NO_COMPARABLE_DECISIONS",
            "compared_decisions": min(len(expected), len(actual)), "expected_decisions": len(expected),
            "actual_decisions": len(actual), "difference_count": len(differences), "differences": differences[:10]}


def audit_strategy(db, request, *, store):
    fields(request, "symbol strategy params from to resolution cash fee_rate latency_ms checkpoints history_starts")
    symbol = request["symbol"]
    if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol) or store not in ("live", "demo"):
        raise ValueError("invalid market or selected store")
    start, end = instant(request["from"]), instant(request["to"])
    spec = BarSpec(request["resolution"])
    if not start < end <= now_utc() or end - start > timedelta(days=31) or spec.resolution == "session":
        raise ValueError("need a past fixed-bar window of at most 31 days")
    if (end - start) // spec.step > 1440:
        raise ValueError("audit is limited to 1440 bars per replay")
    checkpoints, histories = request["checkpoints"], request["history_starts"]
    if type(checkpoints) is not list or not 1 <= len(checkpoints) <= 8 or type(histories) is not list or len(histories) > 4:
        raise ValueError("need 1..8 checkpoints and at most four prehistory starts")
    checkpoints = [instant(t) for t in checkpoints]
    histories = [instant(t) for t in histories]
    if (len(set(checkpoints)) != len(checkpoints) or any(not start < t < end for t in checkpoints)
            or len(set(histories)) != len(histories) or any(not start < t < end for t in histories)):
        raise ValueError("checkpoints and prehistory starts must be distinct and inside the window")
    latency = request["latency_ms"]
    if type(latency) is not int or not 0 <= latency <= 60000:
        raise ValueError("latency must be 0..60000ms")
    cash = decimal(request["cash"], "cash", positive=True)
    cost = CostModel(fee_rate=rate(request["fee_rate"]), latency=timedelta(milliseconds=latency))
    selected = create_strategy(request["strategy"], request["params"])
    if db.c.in_transaction:
        raise ValueError("strategy audit requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        # Include auxiliary markets: reference strategies may read their quotes too.
        count = db.c.execute("SELECT count(*) FROM book_top WHERE ts_avail>=? AND ts_avail<?", (iso(start - timedelta(seconds=120)), iso(end))).fetchone()[0]
        if count * (1 + len(checkpoints) + len(histories)) > 500000:
            raise ValueError("audit observation budget exceeded")
        rules = RuleService(db)

        def replay(a, b):
            return run(_PrefixPortal(db, b), lambda t: rules.load(min(t, b))[1],
                       create_strategy(request["strategy"], selected.params), symbol, a, b,
                       spec.resolution, cash, cost)

        full = replay(start, end)
        checks = []
        for cutoff in sorted(checkpoints):
            prefix = replay(start, cutoff)
            checks.append({"cutoff_exclusive": iso(cutoff), "prefix_data_digest": prefix["data_digest"],
                           **_compare(_known(full["decisions"], cutoff), _known(prefix["decisions"], cutoff))})
        full_rows = _known(full["decisions"], end)
        last = full_rows[-1] if full_rows else None
        history_checks = []
        for a in sorted(histories):
            rows = _known(replay(a, end)["decisions"], end)
            row = rows[-1] if rows else None
            comparable = bool(last and row and row["t"] == last["t"])
            left, right = (last or {}).get("feature_values"), (row or {}).get("feature_values")
            comparable = comparable and isinstance(left, dict) and bool(left) and isinstance(right, dict) and bool(right)
            history_checks.append({"from": iso(a), "at": row and row["t"],
                "status": "NOT_COMPARABLE" if not comparable else "EXACT_MATCH" if left == right else "HISTORY_SENSITIVE",
                "baseline_features": left if comparable else None, "variant_features": right,
                "holdings_and_actions_compared": False})
    finally:
        db.c.rollback()
    result = {"schema": "strategy-audit/1", "engine": ENGINE_VERSION, "store": store, "synthetic": store == "demo",
              "symbol": symbol, "strategy": request["strategy"], "params": selected.params, "request": request,
              "decision_digest": digest(full_rows), "data_digest": full["data_digest"], "last_decision_at": last and last["t"],
              "prefix_checks": checks, "history_checks": history_checks,
              "proves_absence_of_bias": False, "funded_authority": False,
              "status": "PREFIX_DIFFERENCE" if any(r["status"] == "DIFFERENT" for r in checks)
              else "CHECKED_PREFIXES_MATCH" if all(r["status"] == "MATCH" for r in checks) else "NO_COMPARABLE_DECISIONS",
              "limits": ["Only selected checkpoints and the registered native strategy were checked.",
                         "History sensitivity is descriptive; different prehistory can legitimately change recursive indicators.",
                         "Market-source authenticity, future profitability and untriggered branches are not established."]}
    result["report_id"] = digest(result)[:16]
    return result
