"""Read-only venue observations. NEVER spendable Executor money authority.

Raw venue states and foreign/manual orders are displayed with provenance.
Unknown status, missing order and positive filled quantity never prove settlement.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_ASSET = re.compile(r"[A-Z0-9]{1,20}\Z")  # live Wallex lists 1-letter assets (A, G, S, T, W, X)


def _name(v: object, label: str) -> str:
    if not isinstance(v, str) or not _NAME.fullmatch(v):
        raise ValueError(f"invalid {label}")
    return v


def _amount(v: object, label: str) -> str:
    if isinstance(v, (bool, float)) or not isinstance(v, (Decimal, int, str)):
        raise TypeError(f"{label} must be an exact decimal, not float")
    try:
        value = Decimal(str(v))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return format(value, "f")


def _time(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value
    ):
        raise ValueError("observation time must be zoned ISO")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid observation timestamp") from exc
    if stamp.utcoffset() is None:
        raise ValueError("observation time requires a zone")
    return value


def parse_wallex_balances(payload: object) -> dict[str, dict[str, str]]:
    """Only a confirmed result of documented asset → value/locked shape.

    Unknown fields are dropped; undocumented shapes fail rather than imply zero.
    """
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("balance response did not confirm success")
    # Documented and live-verified shape: result.balances.<ASSET>.{value, locked, ...}
    result = payload.get("result")
    body = result.get("balances") if isinstance(result, dict) else None
    if not isinstance(body, dict):
        raise ValueError("unrecognized Wallex balance result")
    out = {}
    for asset, item in body.items():
        if not isinstance(item, dict) or "value" not in item or "locked" not in item:
            raise ValueError("incomplete balance item")
        out[asset] = {
            "value": _amount(item["value"], "value"),
            "locked": _amount(item["locked"], "locked"),
        }
    return out


def project_account(account_id: str, observed_at: str, *,
                    balances: dict | None = None, orders: list[dict] | None = None,
                    exposure: list[dict] | None = None) -> dict:
    """A sanitized snapshot. 'value' and 'locked' are NOT assumed spendable."""
    account_id = _name(account_id, "account")
    if account_id != "main" and not account_id.startswith("subaccount:"):
        raise ValueError("unsupported account scope")
    _time(observed_at)
    balances = {} if balances is None else balances
    orders = [] if orders is None else orders
    exposure = [] if exposure is None else exposure
    if not isinstance(balances, dict) or not isinstance(orders, list) or not isinstance(exposure, list):
        raise TypeError("invalid account collection shapes")
    bal, seen = [], set()
    for asset, row in balances.items():
        if not isinstance(asset, str) or not _ASSET.fullmatch(asset.upper()):
            raise ValueError("invalid asset")
        if asset.upper() in seen or not isinstance(row, dict) or "value" not in row or "locked" not in row:
            raise ValueError("duplicate or incomplete asset")
        seen.add(asset.upper())
        bal.append({
            "asset": asset.upper(),
            "venue_value": _amount(row["value"], "value"),
            "venue_locked": _amount(row["locked"], "locked"),
            "spendable": None, "protectable": None,
        })
    bal.sort(key=lambda x: x["asset"])
    out_orders, seen_orders = [], set()
    for row in orders:
        if not isinstance(row, dict) or not isinstance(row.get("status"), str) or not row["status"]:
            raise ValueError("order requires raw status")
        cid = _name(row.get("client_id"), "client ID")
        if cid in seen_orders:
            raise ValueError("duplicate order ID")
        seen_orders.add(cid)
        symbol = row.get("symbol")
        out_orders.append({
            "account_id": account_id, "client_id": cid,
            "symbol": None if symbol is None else _name(symbol, "symbol").upper(),
            "raw_status": row["status"],
            "filled_observed": None if row.get("filled") is None else _amount(row["filled"], "filled"),
            "origin": "EXTERNAL_MANUAL_UNVERIFIED", "settlement": "UNKNOWN",
            "economic_effect": "UNVERIFIED", "funded_trade": False,
        })
    out_orders.sort(key=lambda x: x["client_id"])
    out_exposure = []
    for row in exposure:
        if not isinstance(row, dict) or not isinstance(row.get("product"), str) or not row["product"]:
            raise ValueError("external exposure requires product")
        raw_product = row["product"]
        asset = row.get("obligation_asset")
        if asset and (not isinstance(asset, str) or not _ASSET.fullmatch(asset.upper())):
            raise ValueError("invalid obligation asset")
        if row.get("obligation") is not None and not asset:
            raise ValueError("obligation requires asset")
        out_exposure.append({
            "account_id": _name(row.get("account_id"), "external account"),
            "product": raw_product if raw_product in ("MARGIN", "TRADE_CREDIT") else "OTHER",
            "raw_product": raw_product, "managed": False,
            "spendable": None, "protectable": None,
            "obligation_asset": asset.upper() if asset else None,
            "obligation": _amount(row["obligation"], "obligation") if row.get("obligation") is not None else None,
            "status": "UNVERIFIED",
        })
    return {
        "state": "OBSERVED", "source": "VENUE_EXTERNAL", "authority": "READ_ONLY",
        "account_id": account_id,
        "account_scope": "MAIN" if account_id == "main" else "TRADE_CREDIT",
        "observed_at": observed_at, "balances": bal, "orders": out_orders,
        "exposure": out_exposure,
    }


def journal_changes(before: dict, after: dict) -> list[dict]:
    """Only observed changes, never invented fills from missing list rows."""
    if before["account_id"] != after["account_id"]:
        raise ValueError("cannot merge different accounts")
    old = {row["client_id"]: row for row in before["orders"]}
    return [
        {
            "kind": "EXTERNAL_ORDER_OBSERVED", "account_id": after["account_id"],
            "observed_at": after["observed_at"], "client_id": row["client_id"],
            "raw_status": row["raw_status"], "settlement": "UNKNOWN",
            "economic_effect": "UNVERIFIED", "source": "VENUE_EXTERNAL",
        }
        for row in after["orders"]
        if old.get(row["client_id"]) != row
    ]
