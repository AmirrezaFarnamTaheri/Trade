"""Bounded OS-authenticated operator intent; never transports an exchange order."""

import asyncio
import re
import secrets
import subprocess

from ..contracts.review_wire import REPLY_SIZE, decode_reply, encode_request
from .service_account_read import _helper_path
from .wallex_account_read import ReadUncertain, parse_account_json


async def review(request):
    correlation = secrets.token_bytes(16)
    frame = encode_request(request, correlation)
    process = None
    try:
        helper = _helper_path("gym-review.exe")
        async with asyncio.timeout(6):
            process = await asyncio.create_subprocess_exec(
                str(helper),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=str(helper.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            process.stdin.write(frame)
            await process.stdin.drain()
            process.stdin.close()
            raw = bytearray()
            while chunk := await process.stdout.read(1024):
                if len(raw) + len(chunk) > 2048:
                    raise ReadUncertain(
                        "native review reply exceeds bound; inspect before retry"
                    )
                raw.extend(chunk)
            if await process.wait() != 0:
                raise ReadUncertain(
                    "native review unavailable; a change may have committed; inspect before retry"
                )
            envelope = parse_account_json(raw)
            if (
                type(envelope) is not dict
                or set(envelope)
                != {"source", "funded_authority", "order_submitted", "raw_reply_hex"}
                or envelope["source"] != "EXECUTOR_SERVICE_REVIEW"
                or envelope["funded_authority"] is not False
                or envelope["order_submitted"] is not False
            ):
                raise ReadUncertain("invalid native review envelope")
            value = envelope["raw_reply_hex"]
            if type(value) is not str or not re.fullmatch(
                rf"[0-9a-f]{{{REPLY_SIZE * 2}}}", value
            ):
                raise ReadUncertain("invalid native review body")
            return decode_reply(bytes.fromhex(value), correlation, request)
    except (OSError, TimeoutError):
        raise ReadUncertain(
            "native review unavailable or timed out; a change may have committed; inspect before retry"
        ) from None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                raise ReadUncertain(
                    "native review helper has not exited; inspect service state"
                ) from None
