"""Current application capabilities, independent of any claimed venue/account permissions."""
from ..adapters.wallex import MAX_CHANNELS, UDF_RESOLUTIONS
from ..domain.bars import FIXED_RESOLUTIONS
from ..domain.model import iso
from .collector import MAX_ASSETS, REST_REQUESTS_PER_SECOND, _value


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
