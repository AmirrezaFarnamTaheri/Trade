"""Shared bounded research actions for the CLI and local web workbench."""
import re
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

from ..adapters.store import MarketDB
from ..domain.market_models import decimal, evaluate_artifact, fields
from ..domain.model import iso, now_utc, parse_ts
from ..domain.periods import instant
from ..domain.portfolio import rebalance_preview
from ..domain.strategy import digest
from .data_portal import DataPortal
from .entry_locks import add_entry_lock
from .experiment_registry import ExperimentRegistry
from .feed_crosscheck import candle_crosscheck
from .liquidity import audit_depth
from .market_statistics import spread_report, trade_flow_report
from .operator_actions import OPERATOR_ACTIONS, operator_action
from .replay_annotations import annotations
from .replay_checkpoint import checkpoint_replay
from .replay_debugger import execution_quality, replay_decisions
from .research_grounding import (
    MetricUnavailable,
    _number,
    check_claims,
    resolve_run_metric,
)
from .research_ledger import ResearchLedger
from .research_market import (
    coverage_timeline,
    market_breadth,
    return_correlations,
    screen_markets,
)
from .research_protocol import ResearchProtocol
from .return_bootstrap import return_bootstrap
from .strategy_audit import audit_strategy
from .technical_analysis import technical_reports

PROTOCOL_ACTIONS = frozenset(("outcome-add", "outcomes", "final-register", "final-run",
                              "final-status", "observe-import", "screen", "derived", "unit-convert"))
WORKSPACE_ACTIONS = (*OPERATOR_ACTIONS, "premium-research", "lead-lag-research", "twap-preview", "stop-preview", "execution-choice-preview", "adaptive-twap-preview", "postfill-check", "shadow-drift-screen", "paper-promotion-screen", "feed-divergence-screen", "feed-divergence-lock", "fairprice-observe", "fairprice-read", "prospective-register", "prospective-status", "prospective-evaluate", "experiment-scorecard", "fractional-sizing", "campaign-status", "market-products", "robustness", "execution-calibration", "execution-model-calibrate", "walk-forward", "portfolio-replay", "portfolio-read", "portfolio-list", "margin-markets", "margin-preview", "margin-replay", "margin-pairs-replay", "combine-oos", "strategy-retirement-screen", "meta-label-eligibility", "unit-convert", "market-breadth", "depth-audit", "entry-lock-add", "entry-locks", "replay-checkpoint", "replay-resume", "registry-page", "annotation-add", "annotation-list", "coverage", "market-screen", "return-correlations", "replay", "rebalance", "execution-quality", "experiment-run",
                     "experiment-list", "experiment-status", "job-recover", "job-catch-up", "job-interrupt", "strategy-audit", "return-bootstrap")
# One action table: `gymctl research` choices come from CLI_ACTIONS; WORKSPACE_ACTIONS is the
# browser allowlist; CLI_ONLY_ACTIONS names every CLI action with no browser form, with the reason.
LEDGER_ACTIONS = ("register", "shadow-open", "shadow-close", "schedule", "tick", "start", "pause", "resume", "list",
                  "mcp", "claim-check", "review")
MARKET_REPORT_ACTIONS = ("candles", "technicals", "spreads", "trade-flow", "diagnostic")
CLI_ACTIONS = tuple(dict.fromkeys((*LEDGER_ACTIONS, *sorted(PROTOCOL_ACTIONS), *MARKET_REPORT_ACTIONS,
                                   *WORKSPACE_ACTIONS)))
CLI_ONLY_ACTIONS = {
    "tick": "scheduler step; the browser uses the dedicated research runner",
    "start": "long-running scheduler process",
    "mcp": "read-only MCP server over stdio",
    "pause": "browser pauses jobs through /api/research/jobs/{id}/pause",
    "resume": "browser resumes jobs through /api/research/jobs/{id}/resume",
    "adaptive-twap-preview": "no browser form yet",
    "fairprice-observe": "no browser form yet",
    "fairprice-read": "no browser form yet",
    "feed-divergence-lock": "no browser form yet",
    "feed-divergence-screen": "no browser form yet",
    "paper-promotion-screen": "no browser form yet",
    "postfill-check": "no browser form yet",
    "shadow-drift-screen": "no browser form yet",
}
OBJECT_ACTIONS = frozenset(("register", "shadow-open", "shadow-close", "schedule", "review",
                           "claim-check", "final-register", "observe-import", "screen", "derived", "diagnostic", "candles",
                           *OPERATOR_ACTIONS, *[a for a in WORKSPACE_ACTIONS if a not in ("portfolio-list", "experiment-list", "experiment-status", "entry-locks", "margin-markets", "prospective-status", "prospective-evaluate")]))


def _market_db(root):
    """Open the existing research market store read-only without creating a new root."""
    path = root / "market.db"
    if not path.is_file():
        raise ValueError("research requires an existing market store")
    return MarketDB(path, readonly=True)


def _research_action_premium_research(root, action, value, store, at):
    from .premium_lead_lag import analyze_lead_lag, analyze_quotes
    from .research_market import _read_quotes, _symbol, _window
    if action == "premium-research":
        fields(value, "base from to resolution max_age_seconds max_skew_seconds fee_rate")
        base = value["base"]
        if type(base) is not str or not re.fullmatch(r"[A-Z0-9]{2,16}", base) or base == "USDT":
            raise ValueError("invalid premium base")
        symbols = (base + "TMN", base + "USDT", "USDTTMN")
    else:
        if type(value) is not dict:
            raise ValueError("lead-lag requires a request object")
        fields({key: item for key, item in value.items() if key != "max_delay_bars"},
               "primary leader from to resolution max_age_seconds max_skew_seconds min_overlap")
        symbols = (_symbol(value["primary"]), _symbol(value["leader"]))
        quote_assets = [next((q for q in ("USDT", "TMN") if len(symbol) > len(q) and symbol.endswith(q)), None)
                        for symbol in symbols]
        if symbols[0] == symbols[1] or quote_assets[0] is None or quote_assets[0] != quote_assets[1]:
            raise ValueError("lead-lag needs distinct same-quote markets")
    start, end, _ = _window(value)
    db = _market_db(root)
    try:
        with _read_quotes(db, symbols, start, end) as books:
            if action == "premium-research":
                return analyze_quotes(base, books, start, end, resolution=value["resolution"],
                                      max_age_seconds=value["max_age_seconds"],
                                      max_skew_seconds=value["max_skew_seconds"],
                                      fee_rate=value["fee_rate"], store=store)
            return analyze_lead_lag(books[symbols[0]], books[symbols[1]], start, end,
                                    resolution=value["resolution"], max_age_seconds=value["max_age_seconds"],
                                    max_skew_seconds=value["max_skew_seconds"],
                                    min_overlap=value["min_overlap"], store=store,
                                    max_delay_bars=value.get("max_delay_bars", 1))
    finally:
        db.c.close()


def _research_action_twap_preview(root, action, value, store, at):
    from ..domain.market_models import instant
    from .paper_twap import simulate_twap
    if type(value) is not dict:
        raise ValueError("TWAP preview requires an object")
    adaptive = action == "adaptive-twap-preview"
    extra = " volume_lookback_seconds max_spread_bps urgency" if adaptive else ""
    fields({k: v for k, v in value.items() if k != "cost_models"},
           "symbol from to side quantity slices participation fee_rate available_quote available_base max_delay_seconds" + extra)
    if action == "execution-choice-preview" and (
        type(value["slices"]) is not int or not 2 <= value["slices"] <= 100
    ):
        raise ValueError("execution-choice requires 2..100 TWAP slices")
    cost_model = None
    if "cost_models" in value:
        from ..domain.sim import CostModel

        definitions = value["cost_models"]
        if type(definitions) is not dict or definitions.keys() - {"impact_models", "hourly_costs", "postfill_costs"}:
            raise ValueError("invalid TWAP cost-model profiles")
        cost_model = CostModel(fee_rate=decimal(value["fee_rate"], "fee rate"),
                               **definitions)
    symbol = value["symbol"]
    if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid TWAP market")
    start, end = instant(value["from"]), instant(value["to"])
    if not start < end <= now_utc():
        raise ValueError("TWAP requires an observed past window")
    db = _market_db(root)
    try:
        db.c.execute("BEGIN")
        portal = DataPortal(db)
        count = db.c.execute("SELECT count(*) FROM book_top WHERE instrument_id=? AND ts_avail>=? AND ts_avail<?",
                             ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0]
        if count > 100000:
            raise ValueError("too many TWAP observations")
        instrument = portal.instrument(symbol)
        spec = portal.spec_at(symbol, start)
        quotes = portal.tops(symbol, start, end)
        if adaptive:
            from .adaptive_twap import adaptive_twap

            lookback = value["volume_lookback_seconds"]
            if type(lookback) is not int or not 60 <= lookback <= 3600:
                raise ValueError("invalid volume observation lookback")
            earliest = start - timedelta(seconds=lookback)
            count = db.c.execute(
                "SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id=? "
                "AND ts_avail>=? AND ts_avail<? LIMIT 100001)",
                ("wallex:" + symbol, iso(earliest), iso(end))).fetchone()[0]
            if count > 100000:
                raise ValueError("too many adaptive TWAP quotes")
            trade_count = db.c.execute(
                "SELECT count(*) FROM (SELECT 1 FROM trades WHERE instrument_id=? "
                "AND ts_event>=? AND ts_event<? LIMIT 100001)",
                ("wallex:" + symbol, iso(earliest), iso(end))).fetchone()[0]
            if trade_count > 100000:
                raise ValueError("too many adaptive TWAP prints")
            prior_quotes = portal.tops(symbol, earliest, end)
            trades = sorted((t for t in portal.trades_by_event(symbol, earliest, end)
                             if earliest <= t.ts_avail < end), key=lambda t: t.ts_avail)
            return adaptive_twap(instrument, prior_quotes, trades, spec, start, end,
                side=value["side"], quantity=decimal(value["quantity"], "quantity", positive=True),
                slices=value["slices"], participation=decimal(value["participation"], "participation", positive=True),
                fee_rate=value["fee_rate"],
                available_quote=decimal(value["available_quote"], "available_quote"),
                available_base=decimal(value["available_base"], "available_base"),
                max_delay_seconds=value["max_delay_seconds"], store=store, cost=cost_model,
                volume_lookback_seconds=lookback,
                max_spread_bps=decimal(value["max_spread_bps"], "max_spread_bps"),
                urgency=value["urgency"])
        # Both candidates use one read snapshot and the same explicit budget,
        # spread/fee model, participation and post-slot observed top quotes.
        shared = {"side": value["side"],
                  "quantity": decimal(value["quantity"], "quantity", positive=True),
                  "participation": decimal(value["participation"], "participation", positive=True),
                  "fee_rate": value["fee_rate"],
                  "available_quote": decimal(value["available_quote"], "available_quote"),
                  "available_base": decimal(value["available_base"], "available_base"),
                  "max_delay_seconds": value["max_delay_seconds"],
                  "store": store, "cost": cost_model}
        sliced = simulate_twap(instrument, quotes, spec, start, end,
                               slices=value["slices"], **shared)
        if action == "twap-preview":
            return sliced
        from .execution_choice import compare_execution_previews

        immediate = simulate_twap(instrument, quotes, spec, start, end,
                                  slices=1, **shared)
        return compare_execution_previews(immediate, sliced)
    finally:
        db.c.rollback()
        db.c.close()


def _research_action_fairprice_observe(root, action, value, store, at):
    from .fair_price import fairprice_action

    return fairprice_action(root, action, value, received_at=now_utc())


def _research_action_feed_divergence_screen(root, action, value, store, at):
    from .feed_divergence import evaluate_divergence, persist_paper_feed_lock

    lock = action == "feed-divergence-lock"
    fields(value, "symbol wallex reference as_of training_samples alert_sigma"
           + (" duration_seconds" if lock else ""))
    when, now = parse_ts(value["as_of"]), now_utc()
    if when > now or (lock and now - when > timedelta(minutes=5)):
        raise ValueError("feed reference check requires a recent past observation")
    result = evaluate_divergence(
        value["wallex"], value["reference"], symbol=value["symbol"],
        as_of=when, training_samples=value["training_samples"],
        alert_sigma=value["alert_sigma"])
    if not lock:
        return result
    if not result["block_entry"]:
        return {**result, "status": "PAPER_LOCK_NOT_TRIGGERED"}
    if not (root / "market.db").is_file():
        raise ValueError("paper feed lock requires existing market rules")
    db = MarketDB(root / "market.db")
    try:
        receipt = persist_paper_feed_lock(
            db, result, now=now, duration_seconds=value["duration_seconds"])
        return {**result, **receipt}
    finally:
        db.c.close()


def _research_action_paper_promotion_screen(root, action, value, store, at):
    from .promotion_gates import promotion_screen

    return promotion_screen(value)


def _research_action_shadow_drift_screen(root, action, value, store, at):
    from ..adapters.run_store import load_verified_run
    from .shadow_drift import shadow_drift

    fields(value, "historical_run_id shadow_run_id")
    historical = load_verified_run(root / "runs", value["historical_run_id"], store=store)
    shadow = load_verified_run(root / "runs", value["shadow_run_id"], store=store)
    return shadow_drift(historical, shadow, observed_at=now_utc())


def _research_action_postfill_check(root, action, value, store, at):
    from ..adapters.run_store import load_verified_run
    from .postfill import post_fill_checks

    fields(value, "run_id")
    native = load_verified_run(root / "runs", value["run_id"], store=store)
    if native["inputs"].get("kind") in ("portfolio", "live-session"):
        raise ValueError("postfill-check requires one immutable historical paper market")
    end = parse_ts(native["inputs"]["to"])
    cutoff = min(now_utc(), end + timedelta(minutes=32))
    start = parse_ts(native["inputs"]["from"])
    symbol = native["inputs"]["symbol"]
    if not start < cutoff:
        raise ValueError("postfill-check requires an elapsed historical evaluation")
    db = _market_db(root)
    try:
        db.c.execute("BEGIN")
        count = db.c.execute(
            "SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id=? "
            "AND ts_avail>=? AND ts_avail<? LIMIT 100001)",
            ("wallex:" + symbol, iso(start), iso(cutoff))).fetchone()[0]
        if count > 100000:
            raise ValueError("postfill-check quote budget exceeded")
        portal = DataPortal(db)
        tops = portal.tops(symbol, start, cutoff)
        result = post_fill_checks(native["result"]["orders"], tops, symbol=symbol,
                                  strategy=native["inputs"]["strategy"],
                                  order_type=native["inputs"]["cost"].get("order_type", "market"),
                                  cutoff=cutoff)
        result["source_run_id"] = native["run_id"]
        result["source_outputs_digest"] = native["outputs_digest"]
        return result
    finally:
        db.c.rollback()
        db.c.close()


def _research_action_prospective_register(root, action, value, store, at):
    from .prospective_comparisons import evaluate_comparison, register_comparison
    with ExperimentRegistry(root, store=store) as registry:
        if action == "prospective-register":
            return register_comparison(registry, value, now=now_utc())
        if action == "prospective-status":
            return registry.read(value)
        db = _market_db(root)
        try:
            return evaluate_comparison(registry, value, db, now=now_utc())
        finally:
            db.c.close()


def _research_action_operator_actions(root, action, value, store, at):
    return operator_action(root, action, value, store=store)


def _research_action_fractional_sizing(root, action, value, store, at):
    from ..adapters.run_store import save_run
    from .fractional_sizing import fractional_sizing
    with ResearchProtocol(root, store=store) as protocol:
        report = fractional_sizing(protocol, value)
    # Research receipts are immutable. A later portfolio can only
    # reference the same verified prior evaluation, not pasted numbers.
    save_run({"run_id": report["report_id"], "report": report},
             root / "runs" / "fractional_sizing")
    return report


def _research_action_experiment_scorecard(root, action, value, store, at):
    from .experiment_scorecard import experiment_scorecard
    with ExperimentRegistry(root, store=store) as registry:
        return experiment_scorecard(registry, value)


def _research_action_market_products(root, action, value, store, at):
    from .capabilities import market_products
    db = _market_db(root)
    try:
        return market_products(root, db, value, store=store)
    finally:
        db.c.close()


def _research_action_execution_model_calibrate(root, action, value, store, at):
    from .execution_market_models import market_execution_model_report

    db = _market_db(root)
    try:
        return market_execution_model_report(root, db, value, store=store)
    finally:
        db.c.close()


def _research_action_execution_calibration(root, action, value, store, at):
    from .execution_calibration import calibration_report
    db = _market_db(root)
    try:
        return calibration_report(db, value, store=store)
    finally:
        db.c.close()


def _research_action_walk_forward(root, action, value, store, at):
    from .walk_forward import walk_forward
    db = _market_db(root)
    try:
        with ExperimentRegistry(root, store=store) as registry:
            return walk_forward(registry, db, value)
    finally:
        db.c.close()


def _research_action_portfolio_replay(root, action, value, store, at):
    from .portfolio_research import portfolio_action
    return portfolio_action(root, action, value, store=store)


def _research_action_combine_oos(root, action, value, store, at):
    from .oos_combination import combine_verified_oos

    return combine_verified_oos(root, value, store=store)


def _research_action_strategy_retirement_screen(root, action, value, store, at):
    from .strategy_retirement import screen_verified_retirement

    return screen_verified_retirement(root, value, store=store)


def _research_action_meta_label_eligibility(root, action, value, store, at):
    from .strategy_retirement import meta_label_eligibility

    fields(value, "closed_trades")
    return meta_label_eligibility(value["closed_trades"])


def _research_action_margin_pairs_replay(root, action, value, store, at):
    from .margin_pairs import margin_pairs_research

    return margin_pairs_research(root, value, store=store)


def _research_action_margin_markets(root, action, value, store, at):
    from .margin import margin_action
    return margin_action(root, action, value, store=store)


def _research_action_depth_audit(root, action, value, store, at):
    return audit_depth(value)


def _research_action_diagnostic(root, action, value, store, at):
    return evaluate_artifact(value)


def _research_action_robustness(root, action, value, store, at):
    from .robustness import robustness
    return robustness(root / "runs", value, store=store)


def _research_action_return_bootstrap(root, action, value, store, at):
    return return_bootstrap(root / "runs", value, store=store)


def _research_action_replay(root, action, value, store, at):
    return (replay_decisions if action == "replay" else execution_quality)(root / "runs", value, store=store)


def _research_action_rebalance(root, action, value, store, at):
    return rebalance_preview(value)


def _research_action_entry_lock_add(root, action, value, store, at):
    from .rules import RuleService
    if not (root / "market.db").is_file():
        raise ValueError("entry locks require an existing market store")
    db = MarketDB(root / "market.db", readonly=action == "entry-locks")
    try:
        if action == "entry-lock-add":
            return add_entry_lock(root, db, value, store=store)
        return {"rules": [r for r in RuleService(db).listing(now_utc(), [])["rules"] if r["body"]["params"].get("entry_lock")],
                "funded_authority": False}
    finally:
        db.c.close()


def _research_action_replay_checkpoint(root, action, value, store, at):
    db = _market_db(root)
    try:
        with ExperimentRegistry(root, store=store) as registry:
            return checkpoint_replay(registry, db, value, resume=action == "replay-resume")
    finally:
        db.c.close()


def _research_action_coverage(root, action, value, store, at):
    db = _market_db(root)
    try:
        if action == "strategy-audit":
            return audit_strategy(db, value, store=store)
        if action == "return-correlations":
            return return_correlations(db, value, store=store)
        if action == "market-breadth":
            return market_breadth(db, value, store=store)
        if action != "experiment-run":
            return (coverage_timeline if action == "coverage" else screen_markets)(db, value, store=store)
        with ExperimentRegistry(root, store=store) as registry:
            return registry.run(db, value)
    finally:
        db.c.close()


def _research_action_campaign_status(root, action, value, store, at):
    with ExperimentRegistry(root, store=store) as registry:
        if action == "campaign-status":
            return registry.progress(value)
        if action == "registry-page":
            return registry.page(value)
        if action in ("annotation-add", "annotation-list"):
            return annotations(registry, value, save=action == "annotation-add")
        if action == "experiment-list":
            return registry.listing()
        return registry.read(value)


def _research_action_job_recover(root, action, value, store, at):
    with ResearchLedger(root / "research.sqlite3") as ledger:
        if action == "job-interrupt":
            return ledger.interrupt(value, at=now_utc())
        if action == "job-recover":
            return ledger.recover(value, at=now_utc())
        fields(value, "job_id limit")
        if type(value["limit"]) is not int or not 1 <= value["limit"] <= 10:
            raise ValueError("catch-up limit must be 1..10")
        db = _market_db(root)
        try:
            return ledger.run_due(db, iso(now_utc()), store=store, limit=value["limit"], job_id=value["job_id"])
        finally:
            db.c.close()


def _research_action_technicals(root, action, value, store, at):
    fields(value, {"technicals": "symbol from to resolutions", "candles": "symbol from to as_of tolerance_bps"}.get(action, "symbol from to"))
    if not isinstance(value["from"], str) or not isinstance(value["to"], str):
        raise ValueError("report bounds must be zoned timestamps")
    start, end = parse_ts(value["from"]), parse_ts(value["to"])
    if not start < end or end - start > timedelta(days=31):
        raise ValueError("report window must be positive and at most 31 days")
    if not isinstance(value["symbol"], str) or not re.fullmatch(r"[A-Z0-9]{2,24}", value["symbol"]):
        raise ValueError("report requires one market symbol")
    db = _market_db(root)
    try:
        if action == "technicals":
            return technical_reports(db, value["symbol"], start, end, resolutions=value["resolutions"], store=store)
        db.c.execute("BEGIN")
        table, timestamp = ("trades", "ts_event") if action in ("trade-flow", "candles") else ("book_top", "ts_avail")
        count = db.c.execute(f"SELECT count(*) FROM {table} WHERE instrument_id=? AND substr({timestamp},1,10)>=? AND substr({timestamp},1,10)<=?",
                            ("wallex:" + value["symbol"], start.date().isoformat(), end.date().isoformat())).fetchone()[0]
        if count > 100000:
            raise ValueError("too many observations; narrow the report window")
        if action == "candles":
            if not isinstance(value["as_of"], str) or not isinstance(value["tolerance_bps"], str):
                raise ValueError("candle cutoff and tolerance must be strings")
            cutoff = parse_ts(value["as_of"])
            if cutoff > now_utc():
                raise ValueError("candle cutoff cannot be in the future")
            report = candle_crosscheck(DataPortal(db), value["symbol"], start, end,
                                       tolerance_bps=decimal(value["tolerance_bps"], "tolerance_bps"), as_of=cutoff)
            return {**report, "store": store, "funded_authority": False, "order_submitted": False}
        return (trade_flow_report if action == "trade-flow" else spread_report)(db, start, end, symbol=value["symbol"], store=store)
    finally:
        db.c.close()


def _research_action_claim_check(root, action, value, store, at):
    return check_claims(root / "runs", value, store=store)


def _research_action_review(root, action, value, store, at):
    fields(value, "run_ids")
    return review_runs(root / "runs", value["run_ids"], as_of=parse_ts(at) if at else now_utc(), store=store)


def _research_action_protocol_actions(root, action, value, store, at):
    if action != "outcomes" and value is None:
        raise ValueError("this action requires an input file or ID")
    if action in ("outcomes", "final-run", "final-status", "screen", "derived", "unit-convert") and not (root / "research_protocol.sqlite3").is_file():
        raise ValueError("research protocol is not initialized")
    root.mkdir(parents=True, exist_ok=True)
    with ResearchProtocol(root, store=store) as protocol:
        if action == "outcomes":
            return protocol.outcomes(parse_ts(at) if at else now_utc())
        if action == "outcome-add":
            return protocol.record_outcome(value)
        if action == "final-register":
            return protocol.register(value)
        if action == "final-status":
            return protocol.evaluation(value)
        if action == "observe-import":
            return protocol.ingest_observations(value)
        if action == "screen":
            return protocol.screen(value)
        if action == "derived":
            return derived_series(protocol, value)
        if action == "unit-convert":
            return convert_series(protocol, value)
        db = _market_db(root)
        try:
            return protocol.consume(value, db)
        finally:
            db.c.close()


def _research_action_stop_preview(root, action, value, store, at):
    from ..domain.market_models import instant
    from .paper_stop import simulate_stop
    fields(value, "symbol from to side quantity stop_price type limit_price fee_rate")
    symbol = value["symbol"]
    if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid stop market")
    start, end = instant(value["from"]), instant(value["to"])
    if not start < end <= now_utc():
        raise ValueError("a stop replay requires an observed past window")
    db = _market_db(root)
    try:
        db.c.execute("BEGIN")
        portal, window = DataPortal(db), ("wallex:" + symbol, iso(start), iso(end))
        for table, column in (("book_top", "ts_avail"), ("trades", "ts_event")):
            if db.c.execute(f"SELECT count(*) FROM {table} WHERE instrument_id=? AND {column}>=? AND {column}<?", window).fetchone()[0] > 100000:
                raise ValueError("too many stop replay observations")
        last = db.c.execute("SELECT price FROM trades WHERE instrument_id=? AND ts_event<? ORDER BY ts_event DESC, rowid DESC LIMIT 1",
                            window[:2]).fetchone()
        if last is None:
            raise ValueError("no trade was recorded before the order time")
        limit = value["limit_price"]
        return simulate_stop(portal.instrument(symbol), decimal(last[0], "last trade", positive=True),
                             portal.trades_by_event(symbol, start, end), portal.tops(symbol, start, end),
                             portal.spec_at(symbol, start), start, end, side=value["side"],
                             quantity=decimal(value["quantity"], "quantity", positive=True),
                             stop_price=decimal(value["stop_price"], "stop price", positive=True), order_type=value["type"],
                             limit_price=None if limit is None else decimal(limit, "limit price", positive=True),
                             fee_rate=decimal(value["fee_rate"], "fee rate"), store=store)
    finally:
        db.c.rollback()
        db.c.close()


_RESEARCH_HANDLERS = (
    (frozenset(('premium-research', 'lead-lag-research')), _research_action_premium_research),
    (frozenset(('twap-preview', 'execution-choice-preview', 'adaptive-twap-preview')), _research_action_twap_preview),
    (frozenset(('stop-preview',)), _research_action_stop_preview),
    (frozenset(('fairprice-observe', 'fairprice-read')), _research_action_fairprice_observe),
    (frozenset(('feed-divergence-screen', 'feed-divergence-lock')), _research_action_feed_divergence_screen),
    (frozenset(('paper-promotion-screen',)), _research_action_paper_promotion_screen),
    (frozenset(('shadow-drift-screen',)), _research_action_shadow_drift_screen),
    (frozenset(('postfill-check',)), _research_action_postfill_check),
    (frozenset(('prospective-register', 'prospective-status', 'prospective-evaluate')), _research_action_prospective_register),
    (OPERATOR_ACTIONS, _research_action_operator_actions),
    (frozenset(('fractional-sizing',)), _research_action_fractional_sizing),
    (frozenset(('experiment-scorecard',)), _research_action_experiment_scorecard),
    (frozenset(('market-products',)), _research_action_market_products),
    (frozenset(('execution-model-calibrate',)), _research_action_execution_model_calibrate),
    (frozenset(('execution-calibration',)), _research_action_execution_calibration),
    (frozenset(('walk-forward',)), _research_action_walk_forward),
    (frozenset(('portfolio-replay', 'portfolio-read', 'portfolio-list')), _research_action_portfolio_replay),
    (frozenset(('combine-oos',)), _research_action_combine_oos),
    (frozenset(('strategy-retirement-screen',)), _research_action_strategy_retirement_screen),
    (frozenset(('meta-label-eligibility',)), _research_action_meta_label_eligibility),
    (frozenset(('margin-pairs-replay',)), _research_action_margin_pairs_replay),
    (frozenset(('margin-markets', 'margin-preview', 'margin-replay')), _research_action_margin_markets),
    (frozenset(('depth-audit',)), _research_action_depth_audit),
    (frozenset(('diagnostic',)), _research_action_diagnostic),
    (frozenset(('robustness',)), _research_action_robustness),
    (frozenset(('return-bootstrap',)), _research_action_return_bootstrap),
    (frozenset(('replay', 'execution-quality')), _research_action_replay),
    (frozenset(('rebalance',)), _research_action_rebalance),
    (frozenset(('entry-lock-add', 'entry-locks')), _research_action_entry_lock_add),
    (frozenset(('replay-checkpoint', 'replay-resume')), _research_action_replay_checkpoint),
    (frozenset(('coverage', 'market-screen', 'market-breadth', 'return-correlations', 'experiment-run', 'strategy-audit')), _research_action_coverage),
    (frozenset(('campaign-status', 'experiment-list', 'experiment-status', 'registry-page', 'annotation-add', 'annotation-list')), _research_action_campaign_status),
    (frozenset(('job-recover', 'job-catch-up', 'job-interrupt')), _research_action_job_recover),
    (frozenset(('technicals', 'spreads', 'trade-flow', 'candles')), _research_action_technicals),
    (frozenset(('claim-check',)), _research_action_claim_check),
    (frozenset(('review',)), _research_action_review),
    (PROTOCOL_ACTIONS, _research_action_protocol_actions),
)


def research_action(root, action, value=None, *, store="live", at=None):
    """Dispatch bounded paper-only research actions with strict store and clock rules."""
    root = Path(root)
    if not isinstance(action, str):
        raise ValueError("invalid research action")
    if store not in ("live", "demo"):
        raise ValueError("invalid research store")
    if at is not None and action not in ("review", "outcomes", "tick"):
        raise ValueError("protocol mutations use the actual clock, without --at overrides")
    for names, handler in _RESEARCH_HANDLERS:
        if action in names:
            return handler(root, action, value, store, at)
    actions = {"register": "register", "shadow-open": "open_shadow", "shadow-close": "settle_shadow",
               "schedule": "schedule", "pause": "pause", "resume": "resume", "list": "overview"}
    if action not in actions and action != "tick":
        raise ValueError("unknown research action")
    root.mkdir(parents=True, exist_ok=True)
    with ResearchLedger(root / "research.sqlite3") as ledger:
        if action == "tick":
            db = _market_db(root)
            try:
                return ledger.run_due(db, at or now_utc().isoformat(), store=store)
            finally:
                db.c.close()
        method = getattr(ledger, actions[action])
        return method() if action == "list" else method(value)


# Kept together with the only research action dispatcher to avoid pass-through modules.

def review_runs(root, run_ids, *, as_of, store="live"):
    """Check historical saved-run metrics as of one conservative availability cutoff."""
    as_of = instant(as_of)
    if type(run_ids) is not list or not 1 <= len(run_ids) <= 4 or any(type(key) is not str for key in run_ids) or len(set(run_ids)) != len(run_ids):
        raise ValueError("review requires 1..4 distinct saved run IDs")
    roles = {"performance": ("net_quote",), "risk": ("sampled_drawdown_percent",),
             "benchmark": ("net_quote", "hold_cash_net_quote")}
    reports = []
    with localcontext() as context:
        context.prec = 160
        for key in run_ids:
            _, _, source, _ = resolve_run_metric(root, {"run_id": key, "metric": "starting_cash_quote"}, store=store)
            if parse_ts(source["period"]["to"]) > as_of:
                raise ValueError("review cannot use a run ending after its availability cutoff")
            for role, metrics in roles.items():
                references = [{"run_id": key, "metric": metric} for metric in metrics]
                try:
                    values = [resolve_run_metric(root, ref, store=store)[0] for ref in references]
                except MetricUnavailable:
                    reports.append({"role": role, "run_id": key, "status": "UNAVAILABLE", "reason": "METRIC_NOT_OBSERVED"})
                    continue
                value = values[0] - values[1] if len(values) == 2 else values[0]
                claim = {"id": role, "operation": "DIFFERENCE" if len(values) == 2 else "VALUE", "sources": references,
                         "value": str(value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN)), "decimal_places": 8}
                checked = check_claims(root, {"claims": [claim]}, store=store)
                reports.append({"role": role, "run_id": key, "status": "MISMATCH" if not checked["all_matched"] else "VERIFIED_NUMERIC" if source["valuation"]["status"] == "CURRENT" else "STALE_VALUATION",
                                "evidence": checked["claims"][0]})
    result = {"schema": "research-review/1", "authority": "PAPER_ONLY", "funded_authority": False,
              "order_submitted": False, "as_of": as_of.isoformat(), "reports": reports,
              "synthesis": "REVIEW_REQUIRED", "semantic_grounding_verified": False,
              "tools": ["resolve_run_metric", "check_claims"], "tool_call_bound": 48,
              "limitation": "Deterministic performance, risk and cash-benchmark views. Numeric artifact checks do not authenticate feeds, "
                            "validate prose/causality, predict returns or create an execution proposal. No vote overrides hard rules."}
    result["review_id"] = digest(result)[:16]
    return result

def derived_series(protocol, request):
    """Compute point-in-time aligned series arithmetic without using future vintages."""
    fields(request, "left right operation as_of max_age_seconds max_skew_seconds")
    if request["operation"] not in ("RATIO", "DIFFERENCE"):
        raise ValueError("derived series supports RATIO or DIFFERENCE")
    for key, lower in (("max_age_seconds", 1), ("max_skew_seconds", 0)):
        if type(request[key]) is not int or not lower <= request[key] <= 2678400:
            raise ValueError("alignment/freshness bounds must be integer seconds up to 31 days")
    if type(request["as_of"]) is not str:
        raise ValueError("derived series requires a zoned cutoff")
    cutoff = parse_ts(request["as_of"])
    if protocol.conn.in_transaction:
        raise ValueError("derived series requires its own read snapshot")
    protocol.conn.execute("BEGIN")
    try:
        inputs = [protocol.observation(request[side], cutoff) for side in ("left", "right")]
    finally:
        protocol.conn.rollback()
    result = {"authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
              "as_of": iso(cutoff), "operation": request["operation"], "status": "UNAVAILABLE", "reason": None,
              "value": None, "unit": None, "inputs": inputs, "source_authenticity_verified": False,
              "alignment_basis": "MEASUREMENT_TIME", "max_age_seconds": request["max_age_seconds"],
              "decimal_precision": 160,
              "max_skew_seconds": request["max_skew_seconds"],
              "limitation": "Arithmetic over supplied vintages only. Release, receipt, revision and measurement clocks are distinct; "
                            "no missing series, source authenticity, causal effect or trading confidence is inferred."}
    if any(row is None for row in inputs):
        result["reason"] = "MISSING_INPUT"
    elif any(row["kind"] == "NEWS" for row in inputs):
        raise ValueError("derived series requires numeric observations")
    elif any("measured_at" not in row for row in inputs):
        result["reason"] = "MEASUREMENT_TIME_UNKNOWN"
    else:
        times = [parse_ts(row["measured_at"]) for row in inputs]
        left, right = inputs
        if any(not 0 <= (cutoff - at).total_seconds() <= request["max_age_seconds"] for at in times):
            result["reason"] = "STALE_MEASUREMENT"
        elif abs((times[0] - times[1]).total_seconds()) > request["max_skew_seconds"]:
            result["reason"] = "MISALIGNED_MEASUREMENTS"
        elif left["unit"] == right["unit"] and left.get("unit_epoch") != right.get("unit_epoch"):
            result["reason"] = "UNIT_EPOCH_MISMATCH_REQUIRES_EXPLICIT_CONVERSION"
        elif request["operation"] == "DIFFERENCE" and left["unit"] != right["unit"]:
            raise ValueError("difference requires identical explicit units")
        elif request["operation"] == "RATIO" and _number(right["value"]) == 0:
            result["reason"] = "ZERO_DENOMINATOR"
        else:
            with localcontext() as context:
                context.prec = 160
                context.rounding = ROUND_HALF_EVEN
                a, b = (_number(row["value"]) for row in inputs)
                result["value"] = str(a / b if request["operation"] == "RATIO" else a - b)
            result["unit"] = ("dimensionless" if left["unit"] == right["unit"] else left["unit"] + "/" + right["unit"]) if request["operation"] == "RATIO" else left["unit"]
            result["status"] = "AVAILABLE"
    result["report_id"] = digest(result)[:16]
    return result


def convert_series(protocol, request):
    """Convert an observation using an explicit, time-aligned unit-epoch factor."""
    fields(request, "value factor from_epoch to_epoch target_unit as_of max_age_seconds max_skew_seconds")
    for key in ("from_epoch", "to_epoch", "target_unit"):
        pattern = r"[A-Za-z0-9][A-Za-z0-9_.:/%-]{0,63}" if key == "target_unit" else r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}"
        if type(request[key]) is not str or not re.fullmatch(pattern, request[key]):
            raise ValueError("conversion units/epochs must be explicit bounded identifiers")
    if request["from_epoch"] == request["to_epoch"]:
        raise ValueError("conversion requires two distinct unit epochs")
    result = derived_series(protocol, {"left": request["value"], "right": request["factor"], "operation": "RATIO",
        **{k: request[k] for k in ("as_of", "max_age_seconds", "max_skew_seconds")}})
    value, factor = result["inputs"]
    if value is not None and value.get("unit_epoch") != request["from_epoch"]:
        raise ValueError("value does not declare the requested source epoch")
    if value is not None and factor is not None:
        if factor["unit"] != request["target_unit"] + "/" + value["unit"]:
            raise ValueError("factor unit must be exactly target_unit/source_unit")
        if _number(factor["value"]) <= 0:
            raise ValueError("unit conversion factor must be positive")
    if result["status"] == "AVAILABLE":
        with localcontext() as context:
            context.prec = 160
            result["value"] = str(_number(value["value"]) * _number(factor["value"]))
        result["unit"] = request["target_unit"]
    result.update(operation="EXPLICIT_UNIT_CONVERSION", from_epoch=request["from_epoch"], unit_epoch=request["to_epoch"],
                  limitation="Supplied vintage factor, measurement/knowledge cutoffs and declared units only. No raw row is relabeled or source authenticity certified.")
    result.pop("report_id")
    result["report_id"] = digest(result)[:16]
    return result


def action_catalog() -> list[dict]:
    """Every research action with where it can be used (CLI, browser) and how it takes input."""
    return [{"action": action, "cli": True, "browser": action not in CLI_ONLY_ACTIONS,
             "browser_note": CLI_ONLY_ACTIONS.get(action), "object_input": action in OBJECT_ACTIONS}
            for action in sorted(CLI_ACTIONS)]
