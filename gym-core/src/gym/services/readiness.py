"""Current public-data readiness; process liveness never proves execution authority.

Adapts TradingGym's reason-coded readiness design to this collector's two-sided books.
"""
from ..domain.bars import qualified
from ..domain.model import book_top, iso


def current_top(collector, symbol, now):
    sides = collector.books[symbol]
    return book_top(symbol, sides["bid"], sides["ask"], now, collector.lim)


def operational_readiness(collector, now):
    markets = []
    for symbol, sides in collector.books.items():
        ages = {name: None if side is None else (now - side.ts).total_seconds()
                for name, side in sides.items()}
        top = current_top(collector, symbol, now)
        if any(age is None for age in ages.values()):
            state = "MISSING"
        elif any(age < 0 for age in ages.values()):
            state = "FUTURE"
        elif any(age > collector.lim.stale_s for age in ages.values()):
            state = "STALE"
        else:
            state = "READY" if qualified(top) else "INVALID"
        markets.append({"symbol": symbol, "state": state, "flags": sorted(top.flags),
                        "bid_age_seconds": ages["bid"], "ask_age_seconds": ages["ask"]})
    reasons = []
    if not collector.status["connected"]:
        reasons.append("STREAM_DISCONNECTED")
    if collector.status["fatal"]:
        reasons.append("COLLECTOR_FAULT")
    fresh = sum(row["state"] == "READY" for row in markets)
    if not fresh:
        reasons.append("NO_CURRENT_QUALIFIED_QUOTES")
    ready = not reasons
    return {"as_of": iso(now), "ready": ready,
            "status": "BLOCKED" if not ready else "READY" if fresh == len(markets) else "DEGRADED",
            "scope": "PUBLIC_OBSERVATIONS", "demo": collector.demo,
            "markets": markets, "reasons": reasons,
            "fresh_markets": fresh, "watched_markets": len(markets),
            "funded_authority": False, "executor_state_verified": False}
