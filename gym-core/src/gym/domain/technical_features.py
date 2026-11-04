"""Bounded streaming indicators; all values use the native first-close EMA seed."""
from collections import deque
from decimal import Decimal, localcontext

from .market_models import decimal
from .strategy import EMA


class TechnicalFeatures:
    def __init__(self):
        with localcontext() as context:
            context.prec = 160
            self.emas = {n: EMA(n) for n in (12, 20, 26, 50, 200)}
            self.signal = EMA(9)
            self.triple = [EMA(15) for _ in range(3)]
            self.trix_signal = EMA(9)
        self.closes = deque(maxlen=50)
        self.slopes = {n: deque(maxlen=6) for n in (20, 50, 200)}
        self.count = self.range_count = 0
        self.gain = self.loss = self.atr = self.plus = self.minus = self.adx = Decimal(0)
        self.previous = self.previous_range = self.previous_triple = None
        self.dx_count = 0

    def update(self, close, *, high=None, low=None):
        close = decimal(close, "close", positive=True)
        if (high is None) != (low is None):
            raise ValueError("high and low must be supplied together")
        if high is None and self.previous_range is not None:
            raise ValueError("cannot omit range data after starting an OHLC sequence")
        if high is not None:
            high, low = decimal(high, "high", positive=True), decimal(low, "low", positive=True)
            if not low <= close <= high:
                raise ValueError("need low <= close <= high")
        with localcontext() as context:
            context.prec = 160
            return self._update(close, high, low)

    def _update(self, close, high, low):
        self.count += 1
        self.closes.append(close)
        result = {}
        for n, ema in self.emas.items():
            ema.update(close)
            if n in self.slopes:
                if ema.ready:
                    self.slopes[n].append(ema.value)
                history = self.slopes[n]
                result[f"ema_{n}"] = {"value": str(ema.value) if ema.ready else None,
                    "status": "AVAILABLE" if ema.ready else "WARMUP", "required_bars": n,
                    "slope_5_bars": str(history[-1] - history[0]) if len(history) == 6 else None,
                    "ema_seed": "FIRST_CLOSE"}
        for n in (20, 50):
            ready = self.count >= n
            result[f"sma_{n}"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": n,
                                    "value": str(sum(list(self.closes)[-n:]) / n) if ready else None}
        if self.previous is not None:
            move = close - self.previous
            gain, loss = max(Decimal(0), move), max(Decimal(0), -move)
            if self.count <= 15:
                self.gain += gain
                self.loss += loss
                if self.count == 15:
                    self.gain /= 14
                    self.loss /= 14
            else:
                self.gain = (self.gain * 13 + gain) / 14
                self.loss = (self.loss * 13 + loss) / 14
        ready = self.count >= 15
        rsi = 100 * self.gain / (self.gain + self.loss) if self.gain + self.loss else Decimal(50)
        result["rsi_14"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": 15,
                            "value": str(rsi) if ready else None, "smoothing": "WILDER", "flat_series_value": "50"}
        line = self.emas[12].value - self.emas[26].value
        if self.emas[26].ready:
            self.signal.update(line)
        ready = self.signal.ready
        result["macd_12_26_9"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": 34,
            "line": str(line) if self.emas[26].ready else None, "signal": str(self.signal.value) if ready else None,
            "histogram": str(line - self.signal.value) if ready else None,
            "ema_seed": "FIRST_CLOSE", "signal_seed": "FIRST_MATURE_MACD_LINE"}
        value, mature = close, True
        for ema in self.triple:
            if mature:
                value = ema.update(value)
                mature = ema.ready
        trix = None
        if mature:
            if self.previous_triple is not None:
                trix = 100 * (value / self.previous_triple - 1)
                self.trix_signal.update(trix)
            self.previous_triple = value
        result["trix_15_9"] = {"status": "AVAILABLE" if self.trix_signal.ready else "WARMUP", "required_bars": 52,
            "value": str(trix) if trix is not None else None,
            "signal": str(self.trix_signal.value) if self.trix_signal.ready else None, "ema_seed": "FIRST_CLOSE"}
        if high is not None:
            if self.previous_range is not None:
                ph, pl, pc = self.previous_range
                tr = max(high - low, abs(high - pc), abs(low - pc))
                up, down = high - ph, pl - low
                plus = up if up > down and up > 0 else Decimal(0)
                minus = down if down > up and down > 0 else Decimal(0)
                self.range_count += 1
                if self.range_count <= 14:
                    self.atr += tr
                    self.plus += plus
                    self.minus += minus
                    if self.range_count == 14:
                        self.atr /= 14
                        self.plus /= 14
                        self.minus /= 14
                else:
                    self.atr = (self.atr * 13 + tr) / 14
                    self.plus = (self.plus * 13 + plus) / 14
                    self.minus = (self.minus * 13 + minus) / 14
                if self.range_count >= 14:
                    self.dx_count += 1
                    dx = 100 * abs(self.plus - self.minus) / (self.plus + self.minus) if self.plus + self.minus else Decimal(0)
                    self.adx = self.adx + dx if self.dx_count <= 14 else (self.adx * 13 + dx) / 14
                    if self.dx_count == 14:
                        self.adx /= 14
            self.previous_range = high, low, close
        ready = self.range_count >= 14
        result["atr_14"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": 15,
                            "value": str(self.atr) if ready else None, "smoothing": "WILDER"}
        result["adx_14"] = {"status": "AVAILABLE" if self.dx_count >= 14 else "WARMUP", "required_bars": 28,
            "value": str(self.adx) if self.dx_count >= 14 else None,
            "plus_di": str(100 * self.plus / self.atr if self.atr else Decimal(0)) if ready else None,
            "minus_di": str(100 * self.minus / self.atr if self.atr else Decimal(0)) if ready else None}
        ready = ready and self.emas[20].ready
        middle = self.emas[20].value
        result["keltner_20_14_2"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": 20,
            "middle": str(middle) if ready else None, "upper": str(middle + 2 * self.atr) if ready else None,
            "lower": str(middle - 2 * self.atr) if ready else None}
        self.previous = close
        return result
