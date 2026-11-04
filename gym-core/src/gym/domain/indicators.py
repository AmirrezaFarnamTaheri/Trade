"""Descriptive closed-price indicators with explicit native seed and warmup rules."""
from decimal import Decimal, localcontext

from .market_models import decimal
from .strategy import EMA


def indicator_values(closes):
    if type(closes) is not list or len(closes) > 10000 or any(type(value) is not Decimal for value in closes):
        raise ValueError("indicators require at most 10000 exact Decimal closes")
    closes = [decimal(value, "close", positive=True) for value in closes]
    with localcontext() as context:
        context.prec = 160
        values = {}
        for period in (20, 50):
            ready = len(closes) >= period
            values[f"sma_{period}"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": period,
                                        "value": str(sum(closes[-period:]) / period) if ready else None}
        rsi = None
        if len(closes) >= 15:
            changes = [last - first for first, last in zip(closes, closes[1:])]
            gain = sum(max(Decimal(0), move) for move in changes[:14]) / 14
            loss = sum(max(Decimal(0), -move) for move in changes[:14]) / 14
            for move in changes[14:]:
                gain = (gain * 13 + max(Decimal(0), move)) / 14
                loss = (loss * 13 + max(Decimal(0), -move)) / 14
            rsi = 100 * gain / (gain + loss) if gain + loss else Decimal(50)
        values["rsi_14"] = {"status": "AVAILABLE" if rsi is not None else "WARMUP", "required_bars": 15,
                             "value": str(rsi) if rsi is not None else None, "smoothing": "WILDER",
                             "flat_series_value": "50"}
        fast, slow, signal = EMA(12), EMA(26), EMA(9)
        line = None
        for close in closes:
            line = fast.update(close) - slow.update(close)
            if slow.ready:
                signal.update(line)
        ready = signal.ready
        values["macd_12_26_9"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": 34,
                                   "line": str(line) if slow.ready else None,
                                   "signal": str(signal.value) if ready else None,
                                   "histogram": str(line - signal.value) if ready else None,
                                   "ema_seed": "FIRST_CLOSE", "signal_seed": "FIRST_MATURE_MACD_LINE"}
    return values
