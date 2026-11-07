"""Descriptive closed-price indicators with explicit native seed and warmup rules."""
import itertools
from decimal import Decimal, localcontext

from .market_models import decimal
from .strategy import EMA
from .technical_features import TechnicalFeatures


def indicator_values(closes):
    if type(closes) is not list or len(closes) > 10000 or any(type(value) is not Decimal for value in closes):
        raise ValueError("indicators require at most 10000 exact Decimal closes")
    closes = [decimal(value, "close", positive=True) for value in closes]
    with localcontext() as context:
        context.prec = 160
        values = {}
        for period in (20, 50, 200):
            ready = len(closes) >= period
            average = sum(closes[-period:]) / period if ready else None
            values[f"sma_{period}"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": period,
                                        "value": str(average) if ready else None}
            values[f"sma_distance_{period}_percent"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": period,
                "value": str(100 * (closes[-1] / average - 1)) if ready else None, "unit": "percent", "basis": "CLOSE_OVER_SMA_MINUS_ONE"}
        rsi = None
        if len(closes) >= 15:
            changes = [last - first for first, last in itertools.pairwise(closes)]
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


def bar_indicator_values(bars):
    """Range values refer to observed MID quote bars, never exchange trade volume."""
    if type(bars) is not list or len(bars) > 10000:
        raise ValueError("indicators require at most 10000 closed bars")
    state, values, previous = TechnicalFeatures(), None, None
    for bar in bars:
        if bar.forming or bar.end > bar.avail or (previous is not None and previous.end != bar.start):
            raise ValueError("indicators require contiguous closed bars")
        if not bar.low <= bar.open <= bar.high:
            raise ValueError("bar open is outside its observed range")
        values = state.update(bar.close, high=bar.high, low=bar.low)
        previous = bar
    if values is not None:
        return values
    values = indicator_values([])
    for n in (20, 50, 200):
        values[f"ema_{n}"] = {"status": "WARMUP", "required_bars": n, "value": None,
                               "slope_5_bars": None, "ema_seed": "FIRST_CLOSE"}
    for name, required, fields in (("atr_14", 15, ("value",)), ("adx_14", 28, ("value", "plus_di", "minus_di")),
                                   ("trix_15_9", 52, ("value", "signal")),
                                   ("keltner_20_14_2", 20, ("middle", "upper", "lower"))):
        values[name] = {"status": "WARMUP", "required_bars": required, **dict.fromkeys(fields)}
    values["awesome_5_34"] = {"status": "WARMUP", "required_bars": 34, "value": None,
                              "basis": "SMA5_MINUS_SMA34_OF_HIGH_LOW_MIDPOINT"}
    return values
