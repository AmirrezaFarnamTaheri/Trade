"""Read-only observations through the protected Executor service helper.

Python never loads the service credential. Helper bytes remain untrusted input;
permission restrictions and settlement are unverified even after a good read.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path

from ..domain.account_observations import parse_wallex_balances
from .wallex_account_read import ReadUncertain, parse_account_json, parse_fee_rates
from .wallex_order_evidence import InvalidOrderEvidence, parse_manual_order_evidence, parse_order_page

_BODY_LIMIT = 1_048_576
_OUTPUT_LIMIT = _BODY_LIMIT * 2 + 256
_TIMEOUT = 22  # The protected helper has its own 20-second deadline.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_HEX = re.compile(r"[0-9a-f]+\Z")


def _helper_path() -> Path:
    if os.name != "nt":
        raise ReadUncertain("Executor account reads require Windows")
    import ctypes
    from uuid import UUID

    # Ask Windows directly; a caller-controlled ProgramFiles/PATH is not trusted.
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    folder_id = (ctypes.c_byte * 16).from_buffer_copy(
        UUID("905e63b6-c1bf-494e-b29c-65b732d3d21a").bytes_le,
    )
    root = ctypes.c_void_p()
    try:
        if shell.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(root)) != 0 or not root:
            raise ReadUncertain("protected Executor helper unavailable")
        path = Path(ctypes.wstring_at(root)) / "TradingGYM" / "Executor" / "gym-account-read.exe"
    finally:
        if root:
            ole.CoTaskMemFree(root)
    try:
        if not path.is_file() or path.resolve(strict=True) != path:
            raise ReadUncertain("protected Executor helper unavailable")
    except OSError:
        raise ReadUncertain("protected Executor helper unavailable") from None
    return path


def _payload(raw: bytes) -> object:
    envelope = parse_account_json(raw)
    expected = {"source", "state", "permission_status", "funded_authority", "raw_body_hex"}
    if not isinstance(envelope, dict) or envelope.keys() != expected or (
        envelope["source"] != "EXECUTOR_SERVICE_WINHTTP"
        or envelope["state"] != "RAW_UNPARSED"
        or envelope["permission_status"] != "UNVERIFIED"
        or envelope["funded_authority"] is not False
    ):
        raise ReadUncertain("unverified Executor account envelope")
    body = envelope["raw_body_hex"]
    if not isinstance(body, str) or not 2 <= len(body) <= _BODY_LIMIT * 2 or len(body) % 2 or not _HEX.fullmatch(body):
        raise ReadUncertain("invalid Executor account body")
    return parse_account_json(bytes.fromhex(body))


class ServiceAccountReader:
    """Same sanitized observations as WallexAccountReader, without Python keys."""

    async def _get(self, *arguments: str) -> object:
        process = None
        try:
            helper = _helper_path()
            async with asyncio.timeout(_TIMEOUT):
                process = await asyncio.create_subprocess_exec(
                    str(helper), *arguments, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    cwd=str(helper.parent),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                raw = bytearray()
                while chunk := await process.stdout.read(16_384):
                    if len(raw) + len(chunk) > _OUTPUT_LIMIT:
                        raise ReadUncertain("Executor account response exceeded size limit")
                    raw.extend(chunk)
                if await process.wait() != 0:
                    raise ReadUncertain("Executor account observation unavailable")
                return _payload(raw)
        except (OSError, asyncio.TimeoutError):
            raise ReadUncertain("Executor account observation unavailable") from None
        finally:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    raise ReadUncertain("Executor account helper did not exit") from None

    async def balances(self) -> dict[str, dict[str, str]]:
        try:
            return parse_wallex_balances(await self._get("balances"))
        except (ValueError, TypeError):
            raise ReadUncertain("invalid Executor balance observation") from None

    async def fee_rates(self) -> dict[str, dict[str, str]]:
        return parse_fee_rates(await self._get("fees"))

    async def manual_order_evidence(self, client_id: str) -> dict:
        if not isinstance(client_id, str) or not _ID.fullmatch(client_id):
            raise ValueError("unsafe manual order ID")
        try:
            return parse_manual_order_evidence(await self._get("known-client-order", client_id), client_id)
        except InvalidOrderEvidence as exc:
            raise ReadUncertain(str(exc)) from None

    async def order_page(self, *, kind, page, per_page=100):
        # Validate before spawning the privileged helper, even for an empty page.
        parse_order_page({"success": True, "result": {}}, kind=kind, page=page, per_page=per_page)
        try:
            payload = await self._get("open-orders" if kind == "OPEN" else "order-history", str(page), str(per_page))
            return parse_order_page(payload, kind=kind, page=page, per_page=per_page)
        except InvalidOrderEvidence as error:
            raise ReadUncertain(str(error)) from None
