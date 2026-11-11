"""Bounded local paper calculations in a disposable process; no arbitrary commands."""
import asyncio
import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ..adapters.wallex_account_read import ReadUncertain, parse_account_json
from ..domain.market_models import fields

DEADLINE_SECONDS = 120
MAX_DEADLINE_SECONDS = 600
# 500 markets and 200,000 observations replayed in 79.8 s (system-status); about 0.4 ms per observation.
SECONDS_PER_OBSERVATION = 0.0004
DEADLINE_HEADROOM = 2.5
DEADLINE_WARN = 0.75  # a run above this share of its deadline is one data-growth step from failing
MAX_OUTPUT = 2 * 1024 * 1024
HEAVY_ACTIONS = frozenset(("premium-research", "lead-lag-research", "twap-preview", "execution-choice-preview", "adaptive-twap-preview", "postfill-check", "shadow-drift-screen", "prospective-evaluate", "experiment-scorecard", "fractional-sizing", "campaign-status", "tick", "job-catch-up", "experiment-run", "walk-forward", "execution-calibration", "robustness", "strategy-audit", "return-bootstrap",
                           "replay-checkpoint", "replay-resume", "final-run", "comparison", "validation", "news-fetch",
                           "margin-markets", "margin-preview", "margin-replay", "margin-pairs-replay", "combine-oos", "strategy-retirement-screen", "portfolio-replay",
                           "execution-model-calibrate"))


class ResearchProcessFailure(RuntimeError):
    def __init__(self, reason, *, terminated, status=503):
        """Capture whether a failed supervised calculation may have committed."""
        self.status = status
        self.report = {"error": reason, "process_terminated": terminated,
                       "result_delivered": False, "operation_may_have_committed": True,
                       "automatic_retry_allowed": False}
        super().__init__(reason)


def work_estimate(root, value) -> int | None:
    """Stored quotes a request will replay (capped), from its symbols and window; None when it names neither."""
    if not isinstance(value, dict):
        return None
    symbols = value.get("symbols") or ([value["symbol"]] if isinstance(value.get("symbol"), str) else None)
    start, end = value.get("from"), value.get("to")
    if not (isinstance(symbols, list) and 0 < len(symbols) <= 2000 and all(isinstance(s, str) for s in symbols)
            and isinstance(start, str) and isinstance(end, str)):
        return None
    path = Path(root) / "market.db"
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            marks = ",".join("?" for _ in symbols)
            return conn.execute(f"SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id IN ({marks}) "
                                "AND ts_avail>=? AND ts_avail<? LIMIT 5000000)",
                                (*(f"wallex:{s}" for s in symbols), start, end)).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def deadline_for(observations: int | None) -> float:
    """P-2: the deadline scales with the work, with headroom, between the old constant and a stated maximum."""
    if not observations:
        return DEADLINE_SECONDS
    return float(min(MAX_DEADLINE_SECONDS,
                     max(DEADLINE_SECONDS, observations * SECONDS_PER_OBSERVATION * DEADLINE_HEADROOM)))


async def calculate(root, action, value=None, *, store="live", at=None, timeout_seconds=None):
    """Execute an allowlisted bounded research request in an isolated child."""
    if action not in HEAVY_ACTIONS or store not in ("live", "demo"):
        raise ValueError("unsupported supervised paper calculation")
    if timeout_seconds is None:
        timeout_seconds = deadline_for(await asyncio.to_thread(work_estimate, root, value))
    if at is not None and action != "tick":
        raise ValueError("only scheduled ticks accept an explicit clock")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
        raise ValueError("invalid calculation deadline")
    payload = json.dumps({"root": str(Path(root).resolve()), "action": action, "value": value,
                          "store": store, "at": at}, allow_nan=False).encode()
    if len(payload) > 70 * 1024:
        raise ValueError("supervised research input exceeds limit")
    process, terminated, temporary = None, False, None
    started = time.monotonic()
    try:
        temporary = tempfile.TemporaryDirectory(prefix="tradinggym-research-")
        environment = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE")}
        environment.update(TEMP=temporary.name, TMP=temporary.name)
        if os.environ.get("GYM_RUST_KERNEL") == "1":
            environment["GYM_RUST_KERNEL"] = "1"
        async with asyncio.timeout(timeout_seconds):
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-B", "-m", "gym.services.research_process",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=environment,
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
            _timing(action, started, timeout_seconds, "completed")
            return reply["result"]
    except TimeoutError:
        _timing(action, started, timeout_seconds, "deadline_exceeded")
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
        if temporary is not None:
            temporary.cleanup()


def _timing(action, started, deadline, outcome):
    """Deadline use per worker run in the event log, so a limit that is getting close shows before it fails."""
    from .event_log import event, log
    seconds = time.monotonic() - started
    share = seconds / deadline
    event("research_worker", action=action, outcome=outcome, seconds=round(seconds, 2),
          deadline_seconds=deadline, deadline_used=round(share, 3))
    if share > DEADLINE_WARN:
        log.warning("research_worker_near_deadline", extra={"fields": {"action": action, "deadline_used": round(share, 3)}})


def main():
    """Validate worker input and return a bounded single JSON result or error."""
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
