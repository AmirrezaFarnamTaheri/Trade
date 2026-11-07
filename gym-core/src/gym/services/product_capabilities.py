"""Observed market scope joined to an explicit saved public margin catalogue."""
from datetime import timedelta

from ..domain.margin import market_rule
from ..domain.market_models import fields
from ..domain.model import iso, parse_ts
from .collector import now_utc
from .data_portal import DataPortal
from .margin import MARKETS, ORIGIN, load_receipt


def market_products(root, db, value, *, store):
    fields(value, "margin_catalogue_id")
    now, catalogue, rules = now_utc(), None, {}
    if value["margin_catalogue_id"] is not None:
        if store != "live":
            raise ValueError("public margin catalogues cannot qualify a DEMO market")
        catalogue = load_receipt(root, value["margin_catalogue_id"], "MARKETS")
        if catalogue.get("source_url") != ORIGIN + MARKETS or type(catalogue.get("markets")) is not list or not 1 <= len(catalogue["markets"]) <= 1000:
            raise ValueError("invalid public margin catalogue")
        for raw in catalogue["markets"]:
            rule = market_rule(raw)
            if rule["symbol"] in rules:
                raise ValueError("duplicate margin markets")
            rules[rule["symbol"]] = rule
    fresh = catalogue is not None and timedelta(0) <= now - parse_ts(catalogue["received_at"]) <= timedelta(minutes=5)
    db.c.execute("BEGIN")
    try:
        symbols = [row[0].split(":", 1)[-1] for row in db.c.execute("SELECT DISTINCT instrument_id FROM book_top ORDER BY instrument_id LIMIT 1001")]
        if len(symbols) > 1000:
            raise ValueError("market capability observation budget exceeded")
        portal, rows = DataPortal(db), []
        for symbol in symbols:
            instrument = portal.instrument(symbol)
            rule = rules.get(symbol)
            rows.append({"symbol": symbol, "base": instrument.base, "quote": instrument.quote,
                "spot": {"status": "OBSERVED" if store == "live" else "SYNTHETIC", "buy": "PAPER_LONG", "sell": "OWNED_ASSET_ONLY", "leverage": "1"},
                "margin": {"status": "UNKNOWN" if catalogue is None else "STALE_CATALOGUE" if not fresh else "LISTED" if rule else "NOT_LISTED",
                    "directions": ["LONG", "SHORT"] if rule else [],
                    "credit_grid": {"minimum": rule["min_risk_coef"], "maximum": rule["max_risk_coef"], "step": rule["risk_coef_step"]} if rule else None,
                    "receipt_id": catalogue and catalogue["run_id"], "received_at": catalogue and catalogue["received_at"],
                    "paper_only": True}, "trade_credit": "ACCOUNT_ELIGIBILITY_UNVERIFIED", "funded_submission": "UNAVAILABLE"})
    finally:
        db.c.rollback()
    return {"schema": "market-products/1", "as_of": iso(now), "markets": rows, "store": store,
            "funded_authority": False, "scope": "Observed symbols, not a current listing census. Margin credit ratios come from the exact saved public grid; collateral still requires a current preview. Account permission, trade credit, borrowing and funded execution are not verified."}
