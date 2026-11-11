"""Strict observation of one Wallex order, never fill/settlement authority.

Only the documented order-detail GET shape is accepted. Returned identifiers
must match the requested identity. Amounts are exact lexical decimals, not
Python floats; raw status names are intentionally not mapped to economic truth.
No API key, raw headers, undocumented fields or active order operations here.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_ASSET = re.compile(r"[A-Z0-9]{1,20}\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{3,32}\Z")
_STATUS = re.compile(r"[A-Za-z0-9_ .:-]{1,128}\Z")


class InvalidOrderEvidence(ValueError):
    """Incomplete or inconsistent private GET evidence; never imply absence."""


def _decimal(value: object, *, label: str, zero: bool = True) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise InvalidOrderEvidence(f"invalid {label} decimal type")
    if len(str(value)) > 80:
        raise InvalidOrderEvidence(f"unbounded {label}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise InvalidOrderEvidence(f"invalid {label} decimal") from None
    if not number.is_finite() or number < 0 or (not zero and number == 0):
        raise InvalidOrderEvidence(f"invalid {label} decimal")
    if number.adjusted() > 79 or number.as_tuple().exponent < -24:
        raise InvalidOrderEvidence(f"unsupported {label} decimal precision")
    # Fixed-point up to 24 decimals (no exponent/floating-binary promotion).
    normalized = format(number, "f")
    if len(normalized) > 80 or (
        "." in normalized and len(normalized.split(".", 1)[1]) > 24
    ):
        raise InvalidOrderEvidence(f"unsupported {label} decimal precision")
    return number


def _format(value: Decimal) -> str:
    # A decimal's str() may use exponent form; never expose scientific money.
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


# The shared fill-timestamp profile in contracts/v1/fixtures/fill-timestamps.json, also enforced by the executor.
_FILL_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})")


def _timestamp(value: object) -> str | int:
    if type(value) is int and 946_684_800 <= value <= 4_102_444_800_000:
        return value
    if isinstance(value, str) and _FILL_TIME.fullmatch(value):
        zone = value[-6:] if value[-6] in "+-" else None
        try:
            datetime.fromisoformat(value[:19])  # calendar date and time; the fraction is checked by the pattern
        except ValueError:
            raise InvalidOrderEvidence("invalid fill timestamp") from None
        if zone is None or (int(zone[1:3]) <= 23 and int(zone[4:6]) <= 59):
            return value
    raise InvalidOrderEvidence("invalid fill timestamp")


def parse_manual_order_evidence(payload: object, requested_id: str) -> dict:
    """Return sanitized, identity-bound order/fill evidence only.

    Repeated, absent or inconsistent fill detail stays UNKNOWN or fails closed;
    a quantity match is *not* proof of the venue's cash/fee settlement.
    """
    if not isinstance(requested_id, str) or not _ID.fullmatch(requested_id):
        raise InvalidOrderEvidence("invalid requested identity")
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise InvalidOrderEvidence("unconfirmed order response")
    order = payload.get("result")
    if not isinstance(order, dict) or order.get("clientOrderId") != requested_id:
        raise InvalidOrderEvidence("unverified order identity")
    status = order.get("status")
    if not isinstance(status, str) or not _STATUS.fullmatch(status):
        raise InvalidOrderEvidence("invalid raw order status")
    symbol = order.get("symbol")
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise InvalidOrderEvidence("invalid order symbol")
    side = order.get("side")
    if side not in ("BUY", "SELL"):
        raise InvalidOrderEvidence("invalid order side")
    requested_qty = _decimal(order.get("origQty"), label="requested quantity", zero=False)
    executed_qty = _decimal(order.get("executedQty"), label="executed quantity")
    if executed_qty > requested_qty:
        raise InvalidOrderEvidence("executed quantity exceeds request")

    fills_raw = order.get("fills")
    fills: list[dict] = []
    fill_coverage = "UNVERIFIED"
    if fills_raw is not None:
        if not isinstance(fills_raw, list) or len(fills_raw) > 256:
            raise InvalidOrderEvidence("unbounded fill list")
        total = Decimal(0)
        for fill in fills_raw:
            if not isinstance(fill, dict):
                raise InvalidOrderEvidence("invalid fill object")
            quantity = _decimal(fill.get("quantity"), label="fill quantity", zero=False)
            price = _decimal(fill.get("price"), label="fill price", zero=False)
            fee = _decimal(fill.get("fee"), label="fill fee")
            fee_asset = fill.get("feeAsset")
            if not isinstance(fee_asset, str) or not _ASSET.fullmatch(fee_asset):
                raise InvalidOrderEvidence("invalid fee asset")
            with localcontext() as exact:
                exact.prec = 256  # Preserve all digits across up to 256 bounded fills.
                total += quantity
            if total > requested_qty:
                raise InvalidOrderEvidence("total fills exceed order quantity")
            coefficients = ("feeCoefficient", "makerFeeCoefficient", "takerFeeCoefficient")
            observed = [field in fill for field in coefficients]
            measured = {}
            if any(observed):
                if not all(observed) or type(fill.get("isBuyer")) is not bool:
                    raise InvalidOrderEvidence("incomplete fill maker/taker coefficients")
                values = [_decimal(fill[key], label=key) for key in coefficients]
                if any(value >= 1 for value in values):
                    raise InvalidOrderEvidence("invalid fill fee coefficient")
                applied, maker_rate, taker_rate = values
                if applied == maker_rate == taker_rate:
                    role = "AMBIGUOUS_RATE_MATCH"
                elif applied == maker_rate:
                    role = "MAKER_RATE_MATCH"
                elif applied == taker_rate:
                    role = "TAKER_RATE_MATCH"
                else:
                    raise InvalidOrderEvidence("reported fee rate disagrees with maker/taker coefficients")
                measured = {"fee_coefficient": _format(applied),
                            "maker_fee_coefficient": _format(maker_rate),
                            "taker_fee_coefficient": _format(taker_rate),
                            "maker_taker_attribution": role,
                            "is_buyer": fill["isBuyer"]}
            fills.append({
                "quantity": _format(quantity), "price": _format(price),
                "fee": _format(fee), "fee_asset": fee_asset,
                "timestamp": _timestamp(fill.get("timestamp")),
                **measured,
            })
        if fills:
            if total != executed_qty:
                raise InvalidOrderEvidence("inconsistent executed quantity and fills")
            fill_coverage = "REPORTED_QUANTITY_MATCHES"
        elif executed_qty > 0:
            # Empty filled list for positive execution cannot demonstrate
            # fee postings or establish which asset incurred the fee.
            fill_coverage = "UNVERIFIED"

    return {
        "client_id": requested_id, "raw_status": status, "symbol": symbol,
        "side": side, "requested_qty": _format(requested_qty),
        "executed_qty": _format(executed_qty), "fills": fills,
        "fill_coverage": fill_coverage,
        "settlement": "UNKNOWN", "money_authority": False,
    }


def parse_order_page(payload, *, kind, page, per_page):
    """Map-of-order-arrays only; a page never proves collection completeness.

    developers.wallex.ir documents both reads (spot Swagger, 2026-11-08): GET /v1/account/openOrders and
    GET /v1/account/orders, each with page/per_page (history: at most 100) and a result map of order arrays.
    """
    if kind not in ("OPEN", "HISTORY") or type(page) is not int or not 1 <= page <= 1000 or type(per_page) is not int or not 1 <= per_page <= 100:
        raise InvalidOrderEvidence("invalid bounded order page request")
    result = payload.get("result") if type(payload) is dict and payload.get("success") is True else None
    if type(result) is not dict or len(result) > 100 or any(type(rows) is not list for rows in result.values()):
        raise InvalidOrderEvidence("unverified order collection contract")
    orders, seen = [], set()
    for group in result.values():
        for row in group:
            if len(orders) >= per_page or type(row) is not dict:
                raise InvalidOrderEvidence("order page exceeds request bound or contains invalid rows")
            evidence = parse_manual_order_evidence({"success": True, "result": row}, row.get("clientOrderId"))
            if evidence["client_id"] in seen:
                raise InvalidOrderEvidence("duplicate order identity in page")
            seen.add(evidence["client_id"])
            orders.append(evidence)
    info = payload.get("result_info")
    echoed = type(info) is dict and "page" in info and "per_page" in info
    if echoed and (type(info["page"]) is not int or type(info["per_page"]) is not int or info["page"] != page or info["per_page"] != per_page):
        raise InvalidOrderEvidence("order page identity differs from request")
    return {"kind": kind, "requested_page": page, "requested_per_page": per_page, "orders": orders,
            "pagination_echo": "MATCHED" if echoed else "UNVERIFIED", "collection_complete": False,
            "snapshot_atomic": False, "absence_proven": False, "settlement": "UNKNOWN", "funded_authority": False}


def validate_order_evidence(value):
    """Validate stored sanitized evidence with the same parser used for actual GETs."""
    if not isinstance(value, list) or len(value) > 1000:
        raise InvalidOrderEvidence("invalid stored order evidence collection")
    clean, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("fills"), list) or len(row["fills"]) > 256 or row.get("money_authority") is not False:
            raise InvalidOrderEvidence("invalid stored order evidence")
        try:
            fills = [{"quantity": fill["quantity"], "price": fill["price"], "fee": fill["fee"],
                      "feeAsset": fill["fee_asset"], "timestamp": fill["timestamp"],
                      **({"feeCoefficient": fill["fee_coefficient"],
                          "makerFeeCoefficient": fill["maker_fee_coefficient"],
                          "takerFeeCoefficient": fill["taker_fee_coefficient"],
                          "isBuyer": fill["is_buyer"]}
                         if "fee_coefficient" in fill else {})}
                     for fill in row["fills"]]
            parsed = parse_manual_order_evidence({"success": True, "result": {
                "clientOrderId": row["client_id"], "status": row["raw_status"], "symbol": row["symbol"],
                "side": row["side"], "origQty": row["requested_qty"], "executedQty": row["executed_qty"],
                "fills": fills,
            }}, row["client_id"])
        except (KeyError, TypeError):
            raise InvalidOrderEvidence("invalid stored order evidence") from None
        if parsed != row or parsed["client_id"] in seen:
            raise InvalidOrderEvidence("changed or duplicate stored order evidence")
        seen.add(parsed["client_id"])
        clean.append(parsed)
    return clean


def validate_order_pages(value):
    """Recheck stored pages without inferring completeness from empty results."""
    if not isinstance(value, list) or len(value) > 2:
        raise InvalidOrderEvidence("invalid stored order page collection")
    clean, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or any(row.get(key) is not False for key in (
            "collection_complete", "snapshot_atomic", "absence_proven", "funded_authority"
        )) or row.get("pagination_echo") not in ("MATCHED", "UNVERIFIED"):
            raise InvalidOrderEvidence("invalid stored order page")
        try:
            payload = {"success": True, "result": {}}
            if row["pagination_echo"] == "MATCHED":
                payload["result_info"] = {"page": row["requested_page"], "per_page": row["requested_per_page"]}
            parsed = parse_order_page(payload, kind=row["kind"], page=row["requested_page"], per_page=row["requested_per_page"])
            parsed["orders"] = validate_order_evidence(row["orders"])
            identity = parsed["kind"], parsed["requested_page"], parsed["requested_per_page"]
            if len(parsed["orders"]) > parsed["requested_per_page"] or parsed != row or identity in seen:
                raise InvalidOrderEvidence("changed or duplicate stored order page")
        except (KeyError, TypeError):
            raise InvalidOrderEvidence("invalid stored order page") from None
        seen.add(identity)
        clean.append(parsed)
    return clean
