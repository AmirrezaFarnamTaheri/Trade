"""Durable public Wallex terms and causal, currency-aware margin paper replay."""
import json
from datetime import timedelta
from pathlib import Path

from ..adapters.run_store import run_path, save_run
from ..adapters.store import MarketDB
from ..adapters.wallex_margin import LOAN, MARKETS, ORIGIN, PREVIEW, public_margin
from ..domain.margin import margin_request, market_rule, preview_terms, replay_margin
from ..domain.market_models import decimal, fields
from ..domain.model import iso, parse_ts
from ..domain.rules import is_closed
from ..domain.strategy import digest
from .collector import now_utc
from .data_portal import DataPortal
from .rules import RuleService

LIMITATIONS = [
    "Paper simulation only; no position, loan, order, transfer or wallet change is submitted.",
    "Credit ratio is Wallex risk_coef, not a generic futures leverage switch. Loan and fees retain their returned currencies.",
    "Entry fills at the requested limit only after an observed qualified quote crosses it with sufficient top quantity; price improvement is omitted.",
    "Initial preview warning/liquidation prices use bid/ask trigger proxies. Venue mark rules, funding repricing, protection and execution are not certified.",
    "Opening fee is charged once; extension fees accrue at each returned extend_time boundary. Base fees on shorts are modeled as additional base debt.",
    "Exit fee rate is an explicit paper assumption. A closed-market trigger or insufficient observed depth cannot settle a position.",
    "Unobserved intraperiod excursions and missed liquidations are unknown. Paper results do not establish venue settlement or profitability.",
    "Saved receipt hashes identify local copies; they are not independent authentication of venue terms or account eligibility.",
]


def _save(root, report):
    record = {"schema": "wallex-margin/1", "funded_authority": False, "order_submitted": False, **report}
    record["run_id"] = digest(record)[:16]
    save_run(record, Path(root) / "margin")
    return record


def load_receipt(root, receipt_id, kind):
    if type(receipt_id) is not str:
        raise ValueError("margin receipt id must be a string")
    path = run_path(Path(root) / "margin", receipt_id)
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 2 * 1024 * 1024:
        raise ValueError("margin receipt unavailable or exceeds bound")
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("margin receipt exceeds bound")
    try:
        record = json.loads(raw)
        if type(record) is not dict:
            raise ValueError("invalid margin receipt object")
        body = {key: value for key, value in record.items() if key != "run_id"}
        if (record["run_id"] != receipt_id or digest(body)[:16] != receipt_id or record["schema"] != "wallex-margin/1"
                or record["kind"] != kind or record["funded_authority"] is not False or record["order_submitted"] is not False):
            raise ValueError("margin receipt identity or integrity mismatch")
        return record
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid margin receipt") from None


def margin_action(root, action, value, *, store):
    if store != "live":
        raise ValueError("public margin terms and replay use the live observation store only")
    if action == "margin-markets":
        if value is not None:
            raise ValueError("margin-markets accepts no inputs")
        result, body_hash = public_margin(MARKETS)
        at = now_utc()
        if type(result) is not list or not 1 <= len(result) <= 1000:
            raise ValueError("invalid margin market catalogue")
        markets = [market_rule(row) for row in result]
        if len({row["symbol"] for row in markets}) != len(markets):
            raise ValueError("duplicate margin market identity")
        return _save(root, {"kind": "MARKETS", "received_at": iso(at), "source_url": ORIGIN + MARKETS,
                            "body_sha256": body_hash, "markets": sorted(markets, key=lambda row: row["symbol"])})
    if action == "margin-preview":
        if type(value) is not dict or set(value) != {"catalogue_id", "request"}:
            raise ValueError("margin preview requires catalogue_id and request")
        catalogue = load_receipt(root, value["catalogue_id"], "MARKETS")
        age = now_utc() - parse_ts(catalogue["received_at"])
        if not timedelta(0) <= age <= timedelta(minutes=5):
            raise ValueError("refresh margin market rules; catalogue is not current")
        request = value["request"]
        rule = next((row for row in catalogue["markets"] if type(request) is dict and row["symbol"] == request.get("market")), None)
        if rule is None:
            raise ValueError("market absent from this margin catalogue")
        request = margin_request(request, rule)
        loan_request = {key: val for key, val in request.items() if key not in ("stop_loss", "take_profit")}
        loan, loan_hash = public_margin(LOAN, loan_request)
        if type(loan) is not dict or type(loan.get("collateral")) is not dict:
            raise ValueError("loan calculator returned no collateral limits")
        limits = loan["collateral"]
        lo, hi = decimal(limits.get("min"), "minimum collateral", positive=True), decimal(limits.get("max"), "maximum collateral", positive=True)
        if lo > hi:
            raise ValueError("loan calculator returned inverted collateral limits")
        if not lo <= decimal(request["collateral"]) <= hi:
            return _save(root, {"kind": "COLLATERAL_LIMITS", "state": "OUTSIDE_LIMITS", "received_at": iso(now_utc()),
                                "catalogue_id": catalogue["run_id"], "request": request, "source_url": ORIGIN + LOAN,
                                "collateral_limits": {"min": str(lo), "max": str(hi), "currency": rule["quote"]}, "body_sha256": loan_hash})
        result, body_hash = public_margin(PREVIEW, request)
        terms = preview_terms(result, request, rule)
        if (type(loan.get("loan")) is not dict or loan["loan"].get("currency") != terms["loan"]["currency"]
                or decimal(loan["loan"].get("value"), "calculated loan", positive=True) != decimal(terms["loan"]["value"])):
            raise ValueError("loan calculator and preview disagree; refresh terms")
        return _save(root, {"kind": "PREVIEW", "received_at": iso(now_utc()), "source_url": ORIGIN + PREVIEW,
                            "catalogue_id": catalogue["run_id"], "request": request, "rule": rule, "terms": terms,
                            "collateral_limits": {"min": str(lo), "max": str(hi)},
                            "body_sha256": body_hash, "loan_body_sha256": loan_hash, "limitations": LIMITATIONS})
    if action != "margin-replay":
        raise ValueError("unknown margin action")
    required = {"preview_id", "from", "to", "exit_fee_rate", "holding_seconds"}
    if (type(value) is not dict or not required <= value.keys()
            or value.keys() - required - {"depth_valuation"}
            or type(value.get("depth_valuation", False)) is not bool):
        raise ValueError("margin replay requires known fields and a boolean depth valuation")
    preview = load_receipt(root, value["preview_id"], "PREVIEW")
    start, end = parse_ts(value["from"]), parse_ts(value["to"])
    if not parse_ts(preview["received_at"]) <= start < end <= now_utc() or end - start > timedelta(days=31):
        raise ValueError("margin replay requires a past window after preview receipt, at most 31 days; no future terms in past runs")
    path = Path(root) / "market.db"
    if not path.is_file():
        raise ValueError("margin replay requires recorded public quotes")
    db = MarketDB(path, readonly=True)
    try:
        symbol = preview["rule"]["symbol"]
        db.c.execute("BEGIN")
        count = db.c.execute("SELECT count(*) FROM book_top WHERE instrument_id=? AND ts_avail>=? AND ts_avail<?",
                             ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0]
        if count > 10000:
            raise ValueError("too many margin observations; narrow the window")
        portal, rules = DataPortal(db), RuleService(db)
        tops = portal.tops(symbol, start, end)
        instrument = portal.instrument(symbol)
        points = [(top, is_closed(rules.load(top.ts_avail)[1], instrument, top.ts_avail)) for top in tops]
        opt_in_depth = value.get("depth_valuation", False)
        result = replay_margin(preview["terms"], preview["rule"], points, end,
                               value["exit_fee_rate"], value["holding_seconds"],
                               depth_valuation=opt_in_depth)
        data_hash = digest([(iso(top.ts_avail), top.bid, top.ask, top.bid_qty, top.ask_qty, sorted(top.flags), closed,
                             *((top.depth,) if opt_in_depth else ())) for top, closed in points])
    finally:
        db.c.close()
    return _save(root, {"kind": "REPLAY", "inputs": value, "data_digest": data_hash, "observations": len(tops),
                        **({"margin_replay_version": 2} if value.get("depth_valuation", False) else {}),
                        "result": result, "limitations": LIMITATIONS})
