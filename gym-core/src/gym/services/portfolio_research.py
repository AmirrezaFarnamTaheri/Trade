"""Bounded portfolio workflows over the same native replay used by the CLI."""
import json
import math
import re
from datetime import timedelta

from ..adapters.run_store import list_runs, load_verified_run, save_run
from ..adapters.store import MarketDB
from ..domain.market_models import decimal, fields, instant
from ..domain.sim import CostModel
from .collector import now_utc
from .portfolio import portfolio


def portfolio_action(root, action, value, *, store):
    runs = root / "runs" / "portfolios"
    if action == "portfolio-list":
        if value is not None:
            raise ValueError("portfolio-list takes no input")
        return {"authority": "PAPER_ONLY", "runs": list_runs(runs, limit=100)}
    if action == "portfolio-read":
        fields(value, "run_id")
        out = load_verified_run(runs, value["run_id"], store=store)
        if out["inputs"].get("kind") != "portfolio" or out.get("mode") != "PORTFOLIO":
            raise ValueError("source is not a portfolio replay")
        return out
    fields(value, "symbols from to resolution cash strategy params rules_mode cost")
    symbols = value["symbols"]
    if (type(symbols) is not list or not 2 <= len(symbols) <= 8
            or any(type(s) is not str or not re.fullmatch("[A-Z0-9]{2,24}", s) for s in symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError("a portfolio needs 2..8 distinct market symbols")
    start, end = instant(value["from"]), instant(value["to"])
    if not start < end <= now_utc() or end - start > timedelta(days=31):
        raise ValueError("portfolio window must be historical, positive and at most 31 days")
    if type(value["resolution"]) is not str:
        raise ValueError("portfolio resolution must be a string")
    description = value["cost"]
    base = {"fee_rate", "latency_ms", "max_wait_s", "fee_assumption"}
    optional = {"max_participation", "walk_depth", "carry_remainder", "max_fraction", "vol_target",
                "vol_lookback", "order_type", "maker_fee_rate", "limit_fill_model"}
    if type(description) is not dict or not base <= description.keys() or description.keys() - base - optional:
        raise ValueError("invalid portfolio cost fields")
    if "limit_fill_model" in description and description["limit_fill_model"] != "queue-capacity/2":
        raise ValueError("unsupported limit fill model")
    if (type(description["latency_ms"]) is not int or not 0 <= description["latency_ms"] <= 60000
            or type(description["max_wait_s"]) not in (int, float)
            or not 0 <= description["max_wait_s"] <= 600 or not math.isfinite(description["max_wait_s"])
            or description["fee_assumption"] != "fee-in-received-asset"
            or any(type(description[k]) is not bool for k in ("walk_depth", "carry_remainder") if k in description)):
        raise ValueError("invalid portfolio execution assumptions")
    for key in ("fee_rate", "max_participation", "max_fraction", "vol_target", "maker_fee_rate"):
        if key in description:
            decimal(description[key], key)
    cost = CostModel.from_description(description)
    cash = decimal(value["cash"], "cash", positive=True)
    path = root / "market.db"
    if not path.is_file():
        raise ValueError("portfolio requires an existing market store")
    db = MarketDB(path, readonly=True)
    try:
        if any(not db.c.execute("SELECT 1 FROM book_top WHERE instrument_id=? LIMIT 1", ("wallex:" + s,)).fetchone() for s in symbols):
            raise ValueError("portfolio requires observed markets")
        out = portfolio(db, symbols, start, end, resolution=value["resolution"], cash=cash, cost=cost,
                        strategy_id=value["strategy"], params=value["params"], rules_mode=value["rules_mode"], store=store)
        size = 0
        for chunk in json.JSONEncoder(default=str, ensure_ascii=False, indent=1).iterencode(out):
            size += len(chunk.encode("utf-8"))
            if size > 16 * 1024 * 1024:
                raise ValueError("portfolio artifact exceeds 16 MiB; narrow the window")
        save_run(out, runs)
        return {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"], "authority": "PAPER_ONLY"}
    finally:
        db.c.close()
