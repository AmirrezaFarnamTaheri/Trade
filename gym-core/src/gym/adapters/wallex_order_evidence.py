"""Strict observation of one Wallex order, never fill/settlement authority.

Only the documented order-detail GET shape is accepted. Returned identifiers
must match the requested identity. Amounts are exact lexical decimals, not
Python floats; raw status names are intentionally not mapped to economic truth.
No API key, raw headers, undocumented fields or active order operations here.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_ASSET = re.compile(r"[A-Z0-9]{2,20}\Z")
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


def _timestamp(value: object) -> str | int:
    if type(value) is int and 946_684_800 <= value <= 4_102_444_800_000:
        return value
    if isinstance(value, str) and len(value) <= 40 and (
        value.endswith("Z") or re.search(r"[+-][0-9]{2}:[0-9]{2}\Z", value)
    ):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise InvalidOrderEvidence("invalid fill timestamp") from None
        if parsed.utcoffset() is not None:
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
            total += quantity
            if total > requested_qty:
                raise InvalidOrderEvidence("total fills exceed order quantity")
            fills.append({
                "quantity": _format(quantity), "price": _format(price),
                "fee": _format(fee), "fee_asset": fee_asset,
                "timestamp": _timestamp(fill.get("timestamp")),
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
