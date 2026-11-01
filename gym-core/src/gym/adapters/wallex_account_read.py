"""Fail-closed, bounded Wallex account GET adapter (read-only key ONLY).

A caller may supply a preconfigured authenticated aiohttp session restricted to
READ permissions. The adapter never obtains/exports secrets, logs headers,
or supports venue writes. Every outcome is observational, not money authority.
"""
from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal, InvalidOperation

import aiohttp

from ..domain.account_observations import parse_wallex_balances

BASE = "https://api.wallex.ir"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_SYMBOL = re.compile(r"[A-Za-z0-9]{3,32}\Z")


class ReadUncertain(RuntimeError):
    """A failed read never proves an order is missing, cancelled or settled."""


class WallexAccountReader:
    def __init__(self, session: aiohttp.ClientSession, *,
                 base_url: str = BASE, max_body: int = 1_048_576):
        if base_url != BASE:
            raise ValueError("only the pinned HTTPS Wallex origin is accepted")
        if not isinstance(max_body, int) or not 256 <= max_body <= 4_194_304:
            raise ValueError("invalid body limit")
        self._session = session
        self._limit = max_body

    async def _get(self, path: str) -> object:
        if path not in ("/v1/account/balances", "/v1/account/fee") and not (
            path.startswith("/v1/account/orders/")
            and _ID.fullmatch(path[len("/v1/account/orders/"):])
        ):
            raise ValueError("not in read-only allowlist")
        try:
            async with self._session.get(
                BASE + path, timeout=aiohttp.ClientTimeout(total=12),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise ReadUncertain("venue read did not return HTTP 200")
                data = bytearray()
                async for chunk in response.content.iter_chunked(16_384):
                    if len(data) + len(chunk) > self._limit:
                        raise ReadUncertain("venue read exceeded response size limit")
                    data.extend(chunk)
                # Duplicate keys can overwrite a failure indicator or an
                # identity, so do not accept Python's last-key-wins default.
                def unique_fields(pairs):
                    observed = {}
                    for key, value in pairs:
                        if key in observed:
                            raise ReadUncertain("duplicate JSON response key")
                        observed[key] = value
                    return observed

                def forbidden_constant(_value):
                    raise ReadUncertain("nonfinite venue JSON number")

                return json.loads(
                    data.decode("utf-8"),
                    object_pairs_hook=unique_fields,
                    parse_constant=forbidden_constant,
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadUncertain("venue read failed or returned unreadable data") from None

    async def balances(self) -> dict[str, dict[str, str]]:
        # The venue's shape is validated before any value becomes visible.
        return parse_wallex_balances(await self._get("/v1/account/balances"))

    async def fee_rates(self) -> dict[str, dict[str, str]]:
        """Documented per-symbol shape: result.<SYMBOL>.{makerFeeRate, takerFeeRate}."""
        payload = await self._get("/v1/account/fee")
        result = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(result, dict):
            raise ReadUncertain("unconfirmed account fee response")
        out = {}
        for symbol, row in result.items():
            # Live result also carries account-level entries (levels, coin_levels); skip non-fee rows.
            if not isinstance(row, dict) or "makerFeeRate" not in row:
                continue
            if not _SYMBOL.fullmatch(symbol):
                raise ReadUncertain("invalid fee row")
            rates = {}
            for side, key in (("maker", "makerFeeRate"), ("taker", "takerFeeRate")):
                v = row.get(key)
                try:
                    rate = Decimal(v) if isinstance(v, str) else None
                except InvalidOperation:
                    rate = None
                if rate is None or not rate.is_finite() or not 0 <= rate < 1:
                    raise ReadUncertain("invalid fee rate")
                rates[side] = format(rate, "f")
            out[symbol.upper()] = rates
        return out

    async def fee_observation(self) -> dict[str, object]:
        """Read but never *assume* the undocumented account-specific fee shape.

        A successful GET confirms connectivity, not the rate or fee asset.
        A separate dated VenueFacts/official-contract probe is needed before
        any live price envelope may rely on account-specific fees.
        """
        payload = await self._get("/v1/account/fee")
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ReadUncertain("unconfirmed account fee response")
        if not isinstance(payload.get("result"), dict):
            raise ReadUncertain("unsupported private fee contract")
        # Deliberately never return raw fee fields or credential-like extras.
        return {
            "resource": "FEES",
            "state": "UNVERIFIED_CONTRACT",
            "method_certified": False,
            "funded_authority": False,
        }

    async def manual_order(self, client_id: str) -> dict[str, str | None]:
        if not isinstance(client_id, str) or not _ID.fullmatch(client_id):
            raise ValueError("unsafe manual order ID")
        payload = await self._get("/v1/account/orders/" + client_id)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ReadUncertain("unconfirmed order response")
        order = payload.get("result")
        if not isinstance(order, dict):
            raise ReadUncertain("unrecognized order response")
        status = order.get("status")
        if not isinstance(status, str) or not status.strip() or len(status) > 128:
            raise ReadUncertain("unrecognized raw order state")
        symbol = order.get("symbol")
        if symbol is not None and (not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol)):
            raise ReadUncertain("invalid order symbol")
        # Official order-detail field (docs: executedQty, decimal string); "filled" is ours.
        filled = order.get("executedQty")
        if filled is not None:
            if isinstance(filled, (bool, float)) or not isinstance(filled, (int, str, Decimal)):
                raise ReadUncertain("invalid filled quantity")
            try:
                amount = Decimal(str(filled))
            except InvalidOperation:
                raise ReadUncertain("invalid filled quantity") from None
            if not amount.is_finite() or amount < 0:
                raise ReadUncertain("invalid filled quantity")
            filled = format(amount, "f")
        # Never return unknown fields or secrets, even on a nominal success.
        return {"client_id": client_id, "status": status, "filled": filled,
                "symbol": symbol.upper() if symbol is not None else None}

    async def manual_order_evidence(self, client_id: str) -> dict:
        """Fetch one explicit, ID-echoed order and its documented fill fees.

        This still uses an injected *read-only* session and is not the
        service-owned T2 credential path. No funding, settlement or order
        absence can be inferred from a single GET.
        """
        from .wallex_order_evidence import (
            InvalidOrderEvidence,
            parse_manual_order_evidence,
        )

        if not isinstance(client_id, str) or not _ID.fullmatch(client_id):
            raise ValueError("unsafe manual order ID")
        payload = await self._get("/v1/account/orders/" + client_id)
        try:
            return parse_manual_order_evidence(payload, client_id)
        except InvalidOrderEvidence as exc:
            # Exception types and messages are allowlisted static strings;
            # the untrusted venue body is never included.
            raise ReadUncertain(str(exc)) from None
