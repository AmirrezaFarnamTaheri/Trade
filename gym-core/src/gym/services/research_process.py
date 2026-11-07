"""Bounded local paper calculations in a disposable process; no arbitrary commands."""
import asyncio
import json
import math
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from ..adapters.wallex_account_read import ReadUncertain, parse_account_json
from ..domain.market_models import fields

DEADLINE_SECONDS = 120
MAX_OUTPUT = 2 * 1024 * 1024
HEAVY_ACTIONS = frozenset(("tick", "job-catch-up", "experiment-run", "strategy-audit", "return-bootstrap",
                           "replay-checkpoint", "replay-resume", "final-run", "comparison", "validation", "news-fetch",
                           "margin-markets", "margin-preview", "margin-replay", "portfolio-replay"))


class ResearchProcessFailure(RuntimeError):
    def __init__(self, reason, *, terminated, status=503):
        self.status = status
        self.report = {"error": reason, "process_terminated": terminated,
                       "result_delivered": False, "operation_may_have_committed": True,
                       "automatic_retry_allowed": False}
        super().__init__(reason)


async def calculate(root, action, value=None, *, store="live", at=None, timeout_seconds=DEADLINE_SECONDS):
    if action not in HEAVY_ACTIONS or store not in ("live", "demo"):
        raise ValueError("unsupported supervised paper calculation")
    if at is not None and action != "tick":
        raise ValueError("only scheduled ticks accept an explicit clock")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
        raise ValueError("invalid calculation deadline")
    payload = json.dumps({"root": str(Path(root).resolve()), "action": action, "value": value,
                          "store": store, "at": at}, allow_nan=False).encode()
    if len(payload) > 70 * 1024:
        raise ValueError("supervised research input exceeds limit")
    process, terminated = None, False
    try:
        async with asyncio.timeout(timeout_seconds):
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-B", "-m", "gym.services.research_process",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env={k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE")},
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            raw = bytearray()
            while chunk := await process.stdout.read(16384):
                if len(raw) + len(chunk) > MAX_OUTPUT + 4096:
                    raise ResearchProcessFailure("paper result exceeds delivery bound; inspect saved state", terminated=False, status=413)
                raw.extend(chunk)
            code = await process.wait()
            terminated = True
            if code != 0:
                raise ResearchProcessFailure("paper worker exited without a verified result; inspect saved state", terminated=True)
            try:
                reply = parse_account_json(raw)
            except ReadUncertain:
                raise ResearchProcessFailure("invalid paper worker response; inspect saved state", terminated=True) from None
            if type(reply) is not dict or set(reply) not in ({"result"}, {"error", "kind"}):
                raise ResearchProcessFailure("invalid paper worker response; inspect saved state", terminated=True)
            if "error" in reply:
                if reply["kind"] not in ("VALIDATION", "DELIVERY", "STORE") or type(reply["error"]) is not str or len(reply["error"]) > 1000:
                    raise ResearchProcessFailure("invalid paper worker response; inspect saved state", terminated=True)
                if reply["kind"] == "VALIDATION":
                    raise ResearchProcessFailure(reply["error"], terminated=True, status=400)
                raise ResearchProcessFailure("paper result exceeds delivery bound; inspect saved state" if reply["kind"] == "DELIVERY"
                                             else "paper store unavailable; inspect saved state", terminated=True,
                                             status=413 if reply["kind"] == "DELIVERY" else 503)
            return reply["result"]
    except TimeoutError:
        raise ResearchProcessFailure("paper calculation deadline exceeded; inspect saved state before retry", terminated=True, status=504) from None
    except OSError:
        raise ResearchProcessFailure("paper worker unavailable", terminated=process is None) from None
    finally:
        if process is not None and not terminated:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            # Wait for the exact child to exit before releasing the caller's lock.
            await asyncio.wait_for(process.wait(), 5)


def main():
    from .research_actions import research_action
    try:
        raw = sys.stdin.buffer.read(70 * 1024 + 1)
        if len(raw) > 70 * 1024:
            raise ValueError("paper input exceeds bound")
        request = parse_account_json(raw)
        fields(request, "root action value store at")
        if request["action"] not in HEAVY_ACTIONS or request["store"] not in ("live", "demo"):
            raise ValueError("unsupported supervised paper calculation")
        if request["action"] in ("comparison", "validation"):
            from .research import saved_comparison
            result = saved_comparison(Path(request["root"]), request["value"], store=request["store"],
                                      validation=request["action"] == "validation")
        else:
            result = research_action(Path(request["root"]), request["action"], request["value"], store=request["store"], at=request["at"])
        reply = {"result": result}
    except ValueError as error:
        reply = {"error": str(error)[:1000], "kind": "VALIDATION"}
    except (OSError, sqlite3.Error):
        reply = {"error": "research store unavailable", "kind": "STORE"}
    encoded = json.dumps(reply, default=str, allow_nan=False).encode()
    if len(encoded) > MAX_OUTPUT:
        # The mutation may already be committed; never report rollback or retry it.
        encoded = b'{"error":"paper result exceeds delivery bound; inspect saved state","kind":"DELIVERY"}'
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()
