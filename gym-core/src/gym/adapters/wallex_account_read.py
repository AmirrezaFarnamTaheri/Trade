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
                return json.loads(data.decode("utf-8"))
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadUncertain("venue read failed or returned unreadable data") from None

    async def balances(self) -> dict[str, dict[str, str]]:
        # The venue's shape is validated before any value becomes visible.
        return parse_wallex_balances(await self._get("/v1/account/balances"))

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
        filled = order.get("filled")
        if filled is not None:
            if isinstance(filled, (bool, float)) or not isinstance(filled, (int, str, Decimal)):
                raise ReadUncertain("invalid filled quantity")
            try:
                amount = Decimal(str(filled))
            except InvalidOperation:
                raise ReadUncertain("invalid filled quantity") from None
            if not amount.is_finite() or amount < 0:
                raise ReadUncertain("invalid filled quantity")
            filled = str(amount)
        # Never return unknown fields or secrets, even on a nominal success.
        return {"client_id": client_id, "status": status, "filled": filled,
                "symbol": symbol.upper() if symbol is not None else None}
