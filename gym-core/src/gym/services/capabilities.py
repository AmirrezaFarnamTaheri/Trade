"""Current application capabilities, independent of any claimed venue/account permissions."""
from datetime import timedelta

from ..adapters.wallex import MAX_CHANNELS, UDF_RESOLUTIONS
from ..domain.bars import FIXED_RESOLUTIONS
from ..domain.margin import market_rule
from ..domain.market_models import fields
from ..domain.model import iso, parse_ts
from .collector import MAX_ASSETS, REST_REQUESTS_PER_SECOND, _value, now_utc
from .data_portal import DataPortal
from .margin import MARKETS, ORIGIN, load_receipt


def workspace_capabilities(col):
    return {
        "schema": "workspace-capabilities/1", "venue": "wallex",
        "funded_authority": False, "live_order_submission": False,
        "sides": {"BUY": "PAPER_SPOT", "SELL": "OWNED_ASSET_ONLY", "SHORT": "PAPER_MARGIN"},
        "products": {"SPOT": "PAPER_LONG_FLAT", "MARGIN": "VENUE_PREVIEW_AND_PAPER_REPLAY", "TRADE_CREDIT": "DIAGNOSTIC_ONLY"},
        "leverage": {"spot_paper": "1", "margin": "VENUE_CREDIT_RATIO_GRID", "financing": "SUPPLIED_DEBT_DIAGNOSTIC", "live": "NOT_IMPLEMENTED"},
        "resolutions": list(FIXED_RESOLUTIONS), "rule_session_bars": True,
        "venue_candle_fetch_resolutions": list(UDF_RESOLUTIONS),
        "bar_source": "RECEIVED_OBSERVATIONS", "collection": dict(col.universe),
        "catalog_received_at": iso(col.catalog_received_at) if col.catalog_received_at else None,
        "catalog_source": col.catalog_source,
        "catalog_markets": len(col.catalog), "asset_capacity": MAX_ASSETS,
        "websocket_channels_per_connection": MAX_CHANNELS,
        "rest_requests_per_second": REST_REQUESTS_PER_SECOND,
    }


def market_catalog(col):
    result = []
    for symbol, row in sorted(col.catalog.items()):
        base, quote = _value(row, "base_asset", "baseAsset"), _value(row, "quote_asset", "quoteAsset")
        flagged = "isRisky" in (row.get("flags") or [])
        observed = symbol in col.insts
        reason = ("OBSERVING" if observed else "REMOVED_BY_OPERATOR" if symbol in col.remove_symbols
                  else "NOT_SPOT" if row.get("is_spot") is not True
                  else "UNSUPPORTED_QUOTE" if quote not in ("TMN", "USDT")
                  else "RISK_FILTER" if flagged and col.asset_count is not None
                  else "NOT_SELECTED")
        result.append({"symbol": symbol, "base": base, "quote": quote,
                       "observed": observed, "risk_flagged": flagged, "reason": reason})
    return result


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
