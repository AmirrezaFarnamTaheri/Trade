"""Shared bounded research actions for the CLI and local web workbench."""
import re
from datetime import timedelta
from pathlib import Path

from ..adapters.store import MarketDB
from ..domain.market_models import decimal, evaluate_artifact, fields
from ..domain.model import iso, parse_ts
from ..domain.portfolio import rebalance_preview
from .collector import now_utc
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
from .research_grounding import check_claims
from .research_ledger import ResearchLedger
from .research_market import (
    coverage_timeline,
    market_breadth,
    return_correlations,
    screen_markets,
)
from .research_notes import prepare_packet, save_notes
from .research_protocol import ResearchProtocol
from .research_review import review_runs
from .research_series import convert_series, derived_series
from .return_bootstrap import return_bootstrap
from .strategy_audit import audit_strategy
from .technical_analysis import technical_reports

PROTOCOL_ACTIONS = frozenset(("outcome-add", "outcomes", "final-register", "final-run",
                              "final-status", "observe-import", "screen", "derived", "unit-convert"))
WORKSPACE_ACTIONS = (*OPERATOR_ACTIONS, "premium-research", "lead-lag-research", "twap-preview", "prospective-register", "prospective-status", "prospective-evaluate", "experiment-scorecard", "fractional-sizing", "campaign-status", "market-products", "robustness", "execution-calibration", "walk-forward", "portfolio-replay", "portfolio-read", "portfolio-list", "margin-markets", "margin-preview", "margin-replay", "news-fetch", "unit-convert", "market-breadth", "depth-audit", "entry-lock-add", "entry-locks", "replay-checkpoint", "replay-resume", "registry-page", "annotation-add", "annotation-list", "coverage", "market-screen", "return-correlations", "replay", "rebalance", "execution-quality", "experiment-run",
                     "experiment-list", "experiment-status", "research-packet", "research-notes", "job-recover", "job-catch-up", "job-interrupt", "strategy-audit", "return-bootstrap")
OBJECT_ACTIONS = frozenset(("register", "shadow-open", "shadow-close", "schedule", "review",
                           "claim-check", "final-register", "observe-import", "screen", "derived", "diagnostic", "candles",
                           *OPERATOR_ACTIONS, *[a for a in WORKSPACE_ACTIONS if a not in ("portfolio-list", "experiment-list", "experiment-status", "entry-locks", "margin-markets", "prospective-status", "prospective-evaluate")]))


def _market_db(root):
    path = root / "market.db"
    if not path.is_file():
        raise ValueError("research requires an existing market store")
    return MarketDB(path, readonly=True)


def research_action(root, action, value=None, *, store="live", at=None):
    root = Path(root)
    if not isinstance(action, str):
        raise ValueError("invalid research action")
    if store not in ("live", "demo"):
        raise ValueError("invalid research store")
    if at is not None and action not in ("review", "outcomes", "tick"):
        raise ValueError("protocol mutations use the actual clock, without --at overrides")
    if action in ("premium-research", "lead-lag-research"):
        from .premium_lead_lag import analyze_lead_lag, analyze_quotes
        from .research_market import _read_quotes, _symbol, _window
        if action == "premium-research":
            fields(value, "base from to resolution max_age_seconds max_skew_seconds fee_rate")
            base = value["base"]
            if type(base) is not str or not re.fullmatch(r"[A-Z0-9]{2,16}", base) or base == "USDT":
                raise ValueError("invalid premium base")
            symbols = (base + "TMN", base + "USDT", "USDTTMN")
        else:
            fields(value, "primary leader from to resolution max_age_seconds max_skew_seconds min_overlap")
            symbols = (_symbol(value["primary"]), _symbol(value["leader"]))
            if symbols[0] == symbols[1] or symbols[0][-4:] != symbols[1][-4:]:
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
                                        min_overlap=value["min_overlap"], store=store)
        finally:
            db.c.close()
    if action == "twap-preview":
        from ..domain.market_models import instant
        from .paper_twap import simulate_twap
        fields(value, "symbol from to side quantity slices participation fee_rate available_quote available_base max_delay_seconds")
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
            return simulate_twap(instrument, quotes, spec, start, end,
                                 side=value["side"], quantity=decimal(value["quantity"], "quantity", positive=True),
                                 slices=value["slices"], participation=decimal(value["participation"], "participation", positive=True),
                                 fee_rate=value["fee_rate"],
                                 available_quote=decimal(value["available_quote"], "available_quote"),
                                 available_base=decimal(value["available_base"], "available_base"),
                                 max_delay_seconds=value["max_delay_seconds"], store=store)
        finally:
            db.c.rollback()
            db.c.close()
    if action in ("prospective-register", "prospective-status", "prospective-evaluate"):
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
    if action in OPERATOR_ACTIONS:
        return operator_action(root, action, value, store=store)
    if action == "fractional-sizing":
        from .fractional_sizing import fractional_sizing
        with ResearchProtocol(root, store=store) as protocol:
            return fractional_sizing(protocol, value)
    if action == "experiment-scorecard":
        from .experiment_scorecard import experiment_scorecard
        with ExperimentRegistry(root, store=store) as registry:
            return experiment_scorecard(registry, value)
    if action == "market-products":
        from .product_capabilities import market_products
        db = _market_db(root)
        try:
            return market_products(root, db, value, store=store)
        finally:
            db.c.close()
    if action == "execution-calibration":
        from .execution_calibration import calibration_report
        db = _market_db(root)
        try:
            return calibration_report(db, value, store=store)
        finally:
            db.c.close()
    if action == "walk-forward":
        from .walk_forward import walk_forward
        db = _market_db(root)
        try:
            with ExperimentRegistry(root, store=store) as registry:
                return walk_forward(registry, db, value)
        finally:
            db.c.close()
    if action in ("portfolio-replay", "portfolio-read", "portfolio-list"):
        from .portfolio_research import portfolio_action
        return portfolio_action(root, action, value, store=store)
    if action in ("margin-markets", "margin-preview", "margin-replay"):
        from .margin import margin_action
        return margin_action(root, action, value, store=store)
    if action == "news-fetch":
        from .news_feed import fetch_news
        return fetch_news(root, value, store=store)
    if action == "depth-audit":
        return audit_depth(value)
    if action == "diagnostic":
        return evaluate_artifact(value)
    if action == "robustness":
        from .robustness import robustness
        return robustness(root / "runs", value, store=store)
    if action == "return-bootstrap":
        return return_bootstrap(root / "runs", value, store=store)
    if action in ("replay", "execution-quality"):
        return (replay_decisions if action == "replay" else execution_quality)(root / "runs", value, store=store)
    if action == "rebalance":
        return rebalance_preview(value)
    if action in ("entry-lock-add", "entry-locks"):
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
    if action in ("replay-checkpoint", "replay-resume"):
        db = _market_db(root)
        try:
            with ExperimentRegistry(root, store=store) as registry:
                return checkpoint_replay(registry, db, value, resume=action == "replay-resume")
        finally:
            db.c.close()
    if action in ("coverage", "market-screen", "market-breadth", "return-correlations", "experiment-run", "strategy-audit"):
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
    if action in ("campaign-status", "experiment-list", "experiment-status", "research-packet", "research-notes", "registry-page", "annotation-add", "annotation-list"):
        with ExperimentRegistry(root, store=store) as registry:
            if action == "campaign-status":
                return registry.progress(value)
            if action == "registry-page":
                return registry.page(value)
            if action in ("annotation-add", "annotation-list"):
                return annotations(registry, value, save=action == "annotation-add")
            if action == "experiment-list":
                return registry.listing()
            if action == "experiment-status":
                return registry.read(value)
            return (prepare_packet if action == "research-packet" else save_notes)(registry, value)
    if action in ("job-recover", "job-catch-up", "job-interrupt"):
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
    if action in ("technicals", "spreads", "trade-flow", "candles"):
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
    if action == "claim-check":
        return check_claims(root / "runs", value, store=store)
    if action == "review":
        fields(value, "run_ids")
        return review_runs(root / "runs", value["run_ids"], as_of=parse_ts(at) if at else now_utc(), store=store)
    if action in PROTOCOL_ACTIONS:
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
