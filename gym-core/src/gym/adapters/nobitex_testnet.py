"""Nobitex Testnet-only Ed25519 signing, order-envelope builder, and HTTP-200 failure parser.

STRICT SAFETY BOUNDARY:
- Hard-locked to https://testnetapiv2.nobitex.ir (production apiv2.nobitex.ir is rejected).
- Enforces least-privilege API scopes: only READ and TRADE are allowed; WITHDRAW, DEPOSIT,
  ADDRESS_BOOK, and OTP are explicitly forbidden.
- Defaults to dry_run=True so no network write can happen accidentally.
- Completely isolated from TradingGYMExecutor (which remains DISARMED / zero funded authority).
"""
from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import aiohttp
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .nobitex import NOBITEX_BOT_USER_AGENT, parse_nobitex_orderbook

NOBITEX_TESTNET_HOST = "testnetapiv2.nobitex.ir"
NOBITEX_TESTNET_BASE_URL = f"https://{NOBITEX_TESTNET_HOST}"
ALLOWED_TESTNET_SCOPES: frozenset[str] = frozenset({"READ", "TRADE"})
FORBIDDEN_SCOPES: frozenset[str] = frozenset({"WITHDRAW", "DEPOSIT", "ADDRESS_BOOK", "OTP"})

_CLIENT_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def validate_testnet_base_url(base_url: str) -> str:
    """Ensure every request is strictly pinned to the Nobitex testnet HTTPS host."""
    parsed = urlparse(base_url.strip())
    if parsed.scheme != "https" or parsed.hostname != NOBITEX_TESTNET_HOST or parsed.port not in (None, 443):
        raise ValueError(
            f"NobitexTestnetClient is strictly restricted to {NOBITEX_TESTNET_BASE_URL}; got {base_url!r}"
        )
    return NOBITEX_TESTNET_BASE_URL


def validate_api_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    """Reject empty, unknown, or high-privilege scopes (WITHDRAW, DEPOSIT, ADDRESS_BOOK, OTP)."""
    normalized = tuple(sorted({s.strip().upper() for s in scopes if s and s.strip()}))
    if not normalized:
        raise ValueError("At least one least-privilege scope (READ or TRADE) is required")
    forbidden = [s for s in normalized if s in FORBIDDEN_SCOPES]
    if forbidden:
        raise ValueError(f"Forbidden Nobitex API scope(s) rejected: {forbidden}")
    unknown = [s for s in normalized if s not in ALLOWED_TESTNET_SCOPES]
    if unknown:
        raise ValueError(f"Unsupported Nobitex API scope(s): {unknown}")
    return normalized


def _dec_str(val: Decimal | str | int | float, name: str) -> tuple[Decimal, str]:
    d = Decimal(str(val))
    if not d.is_finite() or d <= 0:
        raise ValueError(f"{name} must be a positive finite decimal; got {val!r}")
    return d, format(d.normalize(), "f")


def make_client_order_id(prefix: str, symbol: str, side: str, ts_ms: int) -> str:
    """Build a deterministic, URL-safe, open-order-unique clientOrderId."""
    raw = f"{prefix}-{symbol.upper()}-{side.lower()}-{int(ts_ms)}"
    cleaned = _CLIENT_ID_SAFE.sub("", raw)[:64]
    if not cleaned:
        raise ValueError("clientOrderId cannot be empty")
    return cleaned


def canonical_json_body(payload: Mapping[str, Any] | None) -> str:
    """Serialize POST JSON payloads deterministically so signed bytes match wire bytes exactly."""
    if not payload:
        return ""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def build_signing_message(timestamp: int, method: str, full_path: str, raw_body: str = "") -> bytes:
    """OpenAPI 3.0.3 Ed25519 preimage: timestamp + METHOD + full_path + raw_body (omit body for GET)."""
    method_u = method.strip().upper()
    if not full_path.startswith("/"):
        raise ValueError(f"full_path must start with '/': {full_path!r}")
    body_part = "" if method_u == "GET" else raw_body
    return f"{int(timestamp)}{method_u}{full_path}{body_part}".encode()


def sign_nobitex_request(
    private_key_bytes: bytes,
    api_key: str,
    method: str,
    full_path: str,
    raw_body: str = "",
    *,
    timestamp: int | None = None,
    user_agent: str = NOBITEX_BOT_USER_AGENT,
) -> dict[str, str]:
    """Produce Nobitex Ed25519 KeyAuth headers (Nobitex-Key, Nobitex-Timestamp, Nobitex-Signature)."""
    if not api_key or not api_key.strip():
        raise ValueError("api_key is required for signed requests")
    ts = int(time.time()) if timestamp is None else int(timestamp)
    priv = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    msg = build_signing_message(ts, method, full_path, raw_body)
    sig_b64 = base64.urlsafe_b64encode(priv.sign(msg)).decode("ascii")
    headers = {
        "Nobitex-Key": api_key.strip(),
        "Nobitex-Timestamp": str(ts),
        "Nobitex-Signature": sig_b64,
        "User-Agent": user_agent,
    }
    if method.strip().upper() != "GET":
        headers["Content-Type"] = "application/json"
    return headers


def verify_nobitex_signature(
    public_key_bytes: bytes,
    headers: Mapping[str, str],
    method: str,
    full_path: str,
    raw_body: str = "",
) -> bool:
    """Verify a signed Nobitex Ed25519 request envelope against its raw 32-byte public key."""
    ts_str = headers.get("Nobitex-Timestamp")
    sig_str = headers.get("Nobitex-Signature")
    if not ts_str or not sig_str:
        return False
    try:
        msg = build_signing_message(int(ts_str), method, full_path, raw_body)
        sig = base64.urlsafe_b64decode(sig_str.encode("ascii"))
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(sig, msg)
        return True
    except (InvalidSignature, ValueError):
        return False


def _validate_side_and_pair(side: str, src_currency: str, dst_currency: str) -> tuple[str, str, str]:
    side_l = side.strip().lower()
    if side_l not in {"buy", "sell"}:
        raise ValueError(f"side must be 'buy' or 'sell'; got {side!r}")
    src_l = src_currency.strip().lower()
    dst_l = dst_currency.strip().lower()
    if not src_l or not dst_l or src_l == dst_l:
        raise ValueError(f"Invalid currency pair: {src_currency!r}/{dst_currency!r}")
    return side_l, src_l, dst_l


def build_limit_order_payload(
    *,
    side: str,
    src_currency: str,
    dst_currency: str,
    amount: Decimal | str | float,
    price: Decimal | str | float,
    client_order_id: str,
) -> dict[str, Any]:
    """Build a Spot Limit order payload for POST /market/orders/add."""
    side_l, src_l, dst_l = _validate_side_and_pair(side, src_currency, dst_currency)
    _, amt_s = _dec_str(amount, "amount")
    _, px_s = _dec_str(price, "price")
    return {
        "type": side_l,
        "execution": "limit",
        "mode": "default",
        "srcCurrency": src_l,
        "dstCurrency": dst_l,
        "amount": amt_s,
        "price": px_s,
        "clientOrderId": client_order_id,
    }


def build_stop_market_order_payload(
    *,
    side: str,
    src_currency: str,
    dst_currency: str,
    amount: Decimal | str | float,
    stop_price: Decimal | str | float,
    client_order_id: str,
) -> dict[str, Any]:
    """Build a Spot Stop-Market order payload for POST /market/orders/add."""
    side_l, src_l, dst_l = _validate_side_and_pair(side, src_currency, dst_currency)
    _, amt_s = _dec_str(amount, "amount")
    _, stop_s = _dec_str(stop_price, "stop_price")
    return {
        "type": side_l,
        "execution": "stop_market",
        "mode": "default",
        "srcCurrency": src_l,
        "dstCurrency": dst_l,
        "amount": amt_s,
        "stopPrice": stop_s,
        "clientOrderId": client_order_id,
    }


def build_stop_limit_order_payload(
    *,
    side: str,
    src_currency: str,
    dst_currency: str,
    amount: Decimal | str | float,
    price: Decimal | str | float,
    stop_price: Decimal | str | float,
    client_order_id: str,
) -> dict[str, Any]:
    """Build a Spot Stop-Limit order payload with Nobitex BadPrice direction check."""
    side_l, src_l, dst_l = _validate_side_and_pair(side, src_currency, dst_currency)
    _, amt_s = _dec_str(amount, "amount")
    px_d, px_s = _dec_str(price, "price")
    stop_d, stop_s = _dec_str(stop_price, "stop_price")
    if side_l == "buy" and px_d < stop_d:
        raise ValueError("Buy stop_limit requires price >= stop_price to avoid Nobitex BadPrice rejection")
    if side_l == "sell" and px_d > stop_d:
        raise ValueError("Sell stop_limit requires price <= stop_price to avoid Nobitex BadPrice rejection")
    return {
        "type": side_l,
        "execution": "stop_limit",
        "mode": "default",
        "srcCurrency": src_l,
        "dstCurrency": dst_l,
        "amount": amt_s,
        "price": px_s,
        "stopPrice": stop_s,
        "clientOrderId": client_order_id,
    }


def build_oco_order_payload(
    *,
    side: str,
    src_currency: str,
    dst_currency: str,
    amount: Decimal | str | float,
    price: Decimal | str | float,
    stop_price: Decimal | str | float,
    stop_limit_price: Decimal | str | float,
    reference_price: Decimal | str | float,
    client_order_id: str,
) -> dict[str, Any]:
    """Build a Spot OCO order payload enforcing Nobitex's documented price inequalities."""
    side_l, src_l, dst_l = _validate_side_and_pair(side, src_currency, dst_currency)
    _, amt_s = _dec_str(amount, "amount")
    px_d, px_s = _dec_str(price, "price")
    stop_d, stop_s = _dec_str(stop_price, "stop_price")
    sl_d, sl_s = _dec_str(stop_limit_price, "stop_limit_price")
    ref_d, _ = _dec_str(reference_price, "reference_price")
    if side_l == "buy":
        if not (px_d < ref_d < stop_d and sl_d >= stop_d):
            raise ValueError("Buy OCO requires price < reference_price < stop_price <= stop_limit_price")
    else:
        if not (px_d > ref_d > stop_d and sl_d <= stop_d):
            raise ValueError("Sell OCO requires price > reference_price > stop_price >= stop_limit_price")
    return {
        "type": side_l,
        "mode": "oco",
        "srcCurrency": src_l,
        "dstCurrency": dst_l,
        "amount": amt_s,
        "price": px_s,
        "stopPrice": stop_s,
        "stopLimitPrice": sl_s,
        "clientOrderId": client_order_id,
    }


def build_order_status_payload(*, order_id: int | None = None, client_order_id: str | None = None) -> dict[str, Any]:
    """Build POST /market/orders/status body (at least one identifier required)."""
    if order_id is None and not client_order_id:
        raise ValueError("order_id or client_order_id is required")
    body: dict[str, Any] = {}
    if order_id is not None:
        body["id"] = int(order_id)
    if client_order_id:
        body["clientOrderId"] = client_order_id
    return body


def build_order_cancel_payload(*, order_id: int | None = None, client_order_id: str | None = None) -> dict[str, Any]:
    """Build POST /market/orders/update-status cancel body."""
    if order_id is None and not client_order_id:
        raise ValueError("order_id or client_order_id is required")
    body: dict[str, Any] = {"status": "canceled"}
    if order_id is not None:
        body["order"] = int(order_id)
    if client_order_id:
        body["clientOrderId"] = client_order_id
    return body


@dataclass(frozen=True)
class NobitexOrderRecord:
    order_id: int | None
    side: str
    execution: str
    market: str
    status: str
    price: str
    amount: str
    matched_amount: str
    unmatched_amount: str
    client_order_id: str | None = None
    pair_id: int | None = None


@dataclass(frozen=True)
class NobitexApiResult:
    ok: bool
    http_status: int
    venue_status: str
    error_code: str | None = None
    error_message: str | None = None
    updated_status: str | None = None
    client_order_id: str | None = None
    orders: tuple[NobitexOrderRecord, ...] = ()


def _parse_order_record(raw: Mapping[str, Any]) -> NobitexOrderRecord:
    return NobitexOrderRecord(
        order_id=int(raw["id"]) if raw.get("id") is not None else None,
        side=str(raw.get("type", "")),
        execution=str(raw.get("execution", "")),
        market=str(raw.get("market", "")),
        status=str(raw.get("status", "")),
        price=str(raw.get("price", "")),
        amount=str(raw.get("amount", "")),
        matched_amount=str(raw.get("matchedAmount", "0")),
        unmatched_amount=str(raw.get("unmatchedAmount", "0")),
        client_order_id=str(raw["clientOrderId"]) if raw.get("clientOrderId") is not None else None,
        pair_id=int(raw["pairId"]) if raw.get("pairId") is not None else None,
    )


def parse_nobitex_response(http_status: int, payload: Mapping[str, Any]) -> NobitexApiResult:
    """Inspect both HTTP status AND body['status'] == 'ok' (Nobitex returns HTTP 200 on business failures)."""
    venue_status = str(payload.get("status", "")).lower()
    parsed_orders: list[NobitexOrderRecord] = []
    if isinstance(payload.get("order"), Mapping):
        parsed_orders.append(_parse_order_record(payload["order"]))
    elif isinstance(payload.get("orders"), list):
        parsed_orders.extend(_parse_order_record(o) for o in payload["orders"] if isinstance(o, Mapping))

    is_ok = http_status == 200 and venue_status == "ok"
    err_code = None if is_ok else str(payload.get("code") or f"HTTP_{http_status}")
    err_msg = None if is_ok else str(payload.get("message") or payload.get("detail") or venue_status or "request failed")
    return NobitexApiResult(
        ok=is_ok,
        http_status=http_status,
        venue_status=venue_status or "unknown",
        error_code=err_code,
        error_message=err_msg,
        updated_status=str(payload["updatedStatus"]) if payload.get("updatedStatus") is not None else None,
        client_order_id=str(payload["clientOrderId"]) if payload.get("clientOrderId") is not None else None,
        orders=tuple(parsed_orders),
    )


class NobitexTestnetClient:
    """Testnet-only dry-run harness for Nobitex Ed25519 signed requests (never targets production)."""

    def __init__(
        self,
        *,
        base_url: str = NOBITEX_TESTNET_BASE_URL,
        scopes: Iterable[str] = ("READ",),
        api_key: str | None = None,
        private_key_bytes: bytes | None = None,
        dry_run: bool = True,
        user_agent: str = NOBITEX_BOT_USER_AGENT,
    ) -> None:
        self.base_url = validate_testnet_base_url(base_url)
        self.scopes = validate_api_scopes(scopes)
        self.api_key = api_key
        self._private_key_bytes = private_key_bytes
        self.dry_run = bool(dry_run)
        self.user_agent = user_agent

    def prepare_signed_request(
        self,
        method: str,
        full_path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Build a complete signed request envelope without transmitting it."""
        if not self.api_key or not self._private_key_bytes:
            raise ValueError("api_key and private_key_bytes are required to sign requests")
        method_u = method.strip().upper()
        if method_u != "GET" and "TRADE" not in self.scopes:
            raise PermissionError("Mutating testnet requests require declared TRADE scope")
        raw_body = "" if method_u == "GET" else canonical_json_body(payload)
        headers = sign_nobitex_request(
            self._private_key_bytes,
            self.api_key,
            method_u,
            full_path,
            raw_body,
            timestamp=timestamp,
            user_agent=self.user_agent,
        )
        return {
            "url": f"{self.base_url}{full_path}",
            "method": method_u,
            "full_path": full_path,
            "headers": headers,
            "raw_body": raw_body,
            "dry_run": self.dry_run,
        }

    async def send_signed_request(
        self,
        method: str,
        full_path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_s: float = 10.0,
    ) -> NobitexApiResult:
        """Transmit to testnetapiv2.nobitex.ir ONLY when dry_run=False; otherwise refuse locally."""
        env = self.prepare_signed_request(method, full_path, payload)
        if self.dry_run:
            return NobitexApiResult(
                ok=False,
                http_status=0,
                venue_status="dry_run_blocked",
                error_code="DRY_RUN_ONLY",
                error_message=f"Dry-run mode blocked outbound {env['method']} {env['url']}",
                client_order_id=(payload or {}).get("clientOrderId") if isinstance(payload, Mapping) else None,
            )
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            data = env["raw_body"].encode("utf-8") if env["method"] != "GET" else None
            async with session.request(env["method"], env["url"], headers=env["headers"], data=data) as resp:
                body = await resp.json(content_type=None)
                return parse_nobitex_response(resp.status, body if isinstance(body, Mapping) else {})

    async def fetch_public_orderbook(self, symbol: str = "BTCUSDT", *, timeout_s: float = 10.0) -> dict[str, Any]:
        """Read-only public reachability check against testnet /v3/orderbook/{symbol}."""
        url = f"{self.base_url}/v3/orderbook/{symbol.upper()}"
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(url, headers={"User-Agent": self.user_agent}) as resp:
                raw = await resp.json(content_type=None)
                snap = parse_nobitex_orderbook(
                    symbol.upper(), raw if isinstance(raw, dict) else {}, datetime.now(UTC)
                )
                return {
                    "url": url,
                    "http_status": resp.status,
                    "symbol": symbol.upper(),
                    "parsed": snap is not None,
                    "best_bid": str(snap.bid) if snap else None,
                    "best_ask": str(snap.ask) if snap else None,
                    "spread_bps": round(float(snap.spread_bps), 2) if snap else None,
                }
