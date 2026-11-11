"""Daily trend allocation: the rule that held up out of sample in the long-history study.

Long while the last completed daily close is above its moving average, sized so the position's
annualised volatility is at most the target, capped at 1x (spot; this paper path has no credit),
and changes smaller than the band are skipped unless they enter or leave the market.
Paper only: it returns a target exposure, never an order.
"""
import math
from itertools import pairwise

LOOKBACK, VOL_DAYS, VOL_TARGET, BAND = 50, 30, 0.4, 0.2


def daily_target(closes, held, *, lookback=LOOKBACK, vol_days=VOL_DAYS, vol_target=VOL_TARGET, band=BAND):
    """Exposure (0..1) for the next day from completed daily closes (oldest first) and the exposure held.

    Returns the decision with every input it used, so a journal can show why it acted.
    """
    if type(lookback) is not int or not 1 <= lookback <= 400:
        raise ValueError("lookback must be an integer in [1, 400]")
    if type(vol_days) is not int or not 1 <= vol_days <= 399:
        raise ValueError("vol_days must be an integer in [1, 399]")
    if not 0 < vol_target <= 5 or not 0 <= band < 1 or not 0 <= held <= 1:
        raise ValueError("vol_target must be in (0, 5], band in [0, 1), held in [0, 1]")
    need = max(lookback, vol_days + 1)
    if len(closes) < need or any(not (c > 0 and math.isfinite(c)) for c in closes[-need:]):
        return {"status": "WARMING_UP", "observations": len(closes), "required": need, "target": held, "trade": False}
    close, average = closes[-1], sum(closes[-lookback:]) / lookback
    logs = [math.log(b / a) for a, b in pairwise(closes[-vol_days - 1:])]
    mean = sum(logs) / vol_days
    vol = math.sqrt(sum((x - mean) ** 2 for x in logs) / vol_days * 365)
    wanted = 0.0 if close <= average else min(1.0, vol_target / vol) if vol else 1.0
    move = abs(wanted - held)
    trade = move > 1e-9 and (move >= band or wanted == 0 or held == 0)
    return {"status": "READY", "close": close, "average": average, "volatility": vol, "wanted": wanted,
            "target": wanted if trade else held, "trade": trade}
