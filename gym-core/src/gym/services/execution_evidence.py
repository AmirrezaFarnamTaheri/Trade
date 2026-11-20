"""Audit historical paper fill inputs without changing saved runs or granting authority."""
from decimal import Decimal, InvalidOperation

from ..domain.model import parse_ts


def _positive(value):
    try:
        number = Decimal(str(value))
        return number.is_finite() and number > 0
    except InvalidOperation:
        return False


def historical_execution_evidence(portal, record):
    inputs = record["inputs"]
    symbol = inputs.get("symbol")
    if not symbol or inputs.get("store") == "demo" or inputs.get("rules_mode") != "point-in-time":
        return {"status": "UNQUALIFIED", "reason": "POINT_IN_TIME_LIVE_STORE_REPLAY_REQUIRED", "fills": []}
    fills = []
    for order in record["result"].get("orders", []):
        if order.get("status") != "FILLED":
            continue
        at = parse_ts(order["fill_time"])
        metadata = portal.metadata_at(symbol, at)
        raw = metadata["raw"] if metadata else {}
        precision = str(raw.get("stepSize", ""))
        missing = [key for key in ("tickSize", "minQty", "minNotional") if not _positive(raw.get(key))]
        if not precision.isascii() or not precision.isdigit():
            missing.append("stepSize")
        eligibility = raw.get("isMarketTypeEnable", raw.get("is_market_type_enable"))
        if type(eligibility) is not bool:
            missing.append("market_order_eligibility")
        missing.extend(("verified_account_fee", "verified_venue_status"))
        fills.append({"ref": order["ref"], "at": order["fill_time"], "missing": missing,
                      "metadata_digest": metadata["raw_digest"] if metadata else None})
    return {"status": "UNQUALIFIED", "reason": "PAPER_FILLS_ARE_NOT_EXECUTABLE_EVIDENCE", "fills": fills}
