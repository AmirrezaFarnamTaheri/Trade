"""Bounded portfolio workflows over the same native replay used by the CLI."""
import json
import math
import re
from datetime import timedelta

from ..adapters.run_store import list_runs, load_verified_run, save_run
from ..adapters.store import MarketDB
from ..domain.market_models import decimal, fields, instant
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .attribution import toman_attribution
from .collector import now_utc
from .data_quality_gate import recorded_bar_coverage
from .portfolio import MAX_MARKETS, portfolio
from .trial_ledger import TrialLedger


def portfolio_action(root, action, value, *, store):
    """Validate and persist a reproducible paper-only portfolio research request."""
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
        out["observed_bar_coverage"] = recorded_bar_coverage(out)
        out["return_attribution"] = toman_attribution(out)
        return out
    required = {"symbols", "from", "to", "resolution", "cash", "strategy", "params", "rules_mode", "cost"}
    if (type(value) is not dict or not required <= value.keys()
            or value.keys() - required - {"policy", "top_n", "quote_currency", "lookback_hours", "quality_max_bad_share", "hypothesis"}):
        raise ValueError("invalid portfolio replay fields")
    symbols = value["symbols"]
    as_of_request = "top_n" in value
    if (type(symbols) is not list or (not as_of_request and not 2 <= len(symbols) <= MAX_MARKETS)
            or (as_of_request and symbols != [])
            or any(type(s) is not str or not re.fullmatch("[A-Z0-9]{2,24}", s) for s in symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError(f"a portfolio needs 2..{MAX_MARKETS} distinct market symbols")
    start, end = instant(value["from"]), instant(value["to"])
    if not start < end <= now_utc() or end - start > timedelta(days=31):
        raise ValueError("portfolio window must be historical, positive and at most 31 days")
    if type(value["resolution"]) is not str:
        raise ValueError("portfolio resolution must be a string")
    description = value["cost"]
    base = {"fee_rate", "latency_ms", "max_wait_s", "fee_assumption"}
    optional = {"max_participation", "walk_depth", "carry_remainder", "max_fraction", "vol_target",
                "vol_lookback", "volatility_model", "order_type", "maker_fee_rate", "limit_fill_model",
                "impact_models", "hourly_costs", "fractional_sizing_report_id"}
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
    cost_inputs = dict(description)
    if "fractional_sizing_report_id" in cost_inputs:
        if as_of_request or "max_fraction" in cost_inputs:
            raise ValueError("fractional report reference needs a fixed universe and no competing fraction")
        from .fractional_sizing import load_fractional_report

        report = load_fractional_report(
            root, cost_inputs.pop("fractional_sizing_report_id"), store=store,
            as_of=start, strategy=value["strategy"], params=value["params"],
            resolution=value["resolution"], symbols=symbols, fee_rate=description["fee_rate"])
        cost_inputs["max_fraction"] = report["fraction"]
        cost_inputs["calibration"] = {
            "fractional_sizing_report_id": report["report_id"],
            "source_run_id": report["source_run_id"],
            "source_outputs_digest": report["source_outputs_digest"],
            "source_test_to": report["source_test_to"],
            "authority": "PAPER_ONLY"}
    cost = CostModel.from_description(cost_inputs)
    cash = decimal(value["cash"], "cash", positive=True)
    path = root / "market.db"
    if not path.is_file():
        raise ValueError("portfolio requires an existing market store")
    db = MarketDB(path, readonly=True)
    try:
        selection = None
        if as_of_request:
            from .historical_universe import select_universe

            selection = select_universe(db, start, quote_currency=value.get("quote_currency"),
                                        top_n=value["top_n"], lookback_hours=value.get("lookback_hours", 24))
            if selection["status"] != "AVAILABLE" or len(selection["symbols"]) < 2:
                raise ValueError("historical top-N portfolio lacks sufficient prior volume evidence")
            symbols = selection["symbols"]
        if any(not db.c.execute("SELECT 1 FROM book_top WHERE instrument_id=? LIMIT 1", ("wallex:" + s,)).fetchone() for s in symbols):
            raise ValueError("portfolio requires observed markets")
        if "quality_max_bad_share" in value:
            if len(symbols) > 20:
                raise ValueError("quality-gated portfolios require at most 20 markets")
            threshold = decimal(value["quality_max_bad_share"], "maximum bad share")
            if threshold > 1:
                raise ValueError("maximum bad share exceeds one")
        with TrialLedger(root) as ledger:
            ledger.record(symbol=",".join(symbols), start=start, end=end,
                          hypothesis=value.get("hypothesis", "ad-hoc"), source="portfolio",
                          config_hash=digest({"replay": value, "selected_symbols": symbols}))
        quality_gate = None
        if "quality_max_bad_share" in value:
            from .data_quality_gate import quote_coverage

            quality_gate = {symbol: quote_coverage(db, symbol, start, end, value["resolution"],
                            max_bad_share=value["quality_max_bad_share"]) for symbol in symbols}
            if any(row["status"] == "INSUFFICIENT_DATA" for row in quality_gate.values()):
                return {"status": "INSUFFICIENT_DATA", "quality_gate": quality_gate,
                        "authority": "PAPER_ONLY", "funded_authority": False, "run_saved": False}
        out = portfolio(db, symbols, start, end, resolution=value["resolution"], cash=cash, cost=cost,
                        strategy_id=value["strategy"], params=value["params"], rules_mode=value["rules_mode"], store=store,
                        policy=value.get("policy"), universe_selection=selection)
        size = 0
        for chunk in json.JSONEncoder(default=str, ensure_ascii=False, indent=1).iterencode(out):
            size += len(chunk.encode("utf-8"))
            if size > 16 * 1024 * 1024:
                raise ValueError("portfolio artifact exceeds 16 MiB; narrow the window")
        save_run(out, runs)
        return {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"], "authority": "PAPER_ONLY",
                "return_attribution": toman_attribution(out),
                "observed_bar_coverage": recorded_bar_coverage(out),
                **({"universe_selection": selection} if selection is not None else {}),
                **({"quality_gate": quality_gate} if quality_gate is not None else {})}
    finally:
        db.c.close()
