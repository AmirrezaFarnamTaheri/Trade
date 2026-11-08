"""Bounded streaming indicators; all values use the native first-close EMA seed."""
from collections import deque
from decimal import Decimal, localcontext

from .market_models import decimal
from .strategy import EMA


class TechnicalFeatures:
    def __init__(self, *, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9,
                 trix_period=15, trix_signal=9, keltner_period=20, range_period=14, multiplier=2):
        periods = (rsi_period, macd_fast, macd_slow, macd_signal, trix_period, trix_signal, keltner_period, range_period)
        if (any(type(n) is not int or not 1 <= n <= 500 for n in periods)
                or min(rsi_period, trix_period, range_period) < 2 or macd_fast >= macd_slow
                or type(multiplier) is not int or not 1 <= multiplier <= 10):
            raise ValueError("invalid technical feature periods or multiplier")
        self.rsi_period, self.macd_fast, self.macd_slow, self.macd_signal = rsi_period, macd_fast, macd_slow, macd_signal
        self.trix_period, self.trix_signal_period = trix_period, trix_signal
        self.keltner_period, self.range_period, self.multiplier = keltner_period, range_period, multiplier
        self.rsi_key = f"rsi_{rsi_period}"
        self.macd_key = f"macd_{macd_fast}_{macd_slow}_{macd_signal}"
        self.trix_key = f"trix_{trix_period}_{trix_signal}"
        self.adx_key = f"adx_{range_period}"
        self.keltner_key = f"keltner_{keltner_period}_{range_period}_{multiplier}"
        with localcontext() as context:
            context.prec = 160
            self.emas = {n: EMA(n) for n in dict.fromkeys((macd_fast, 20, macd_slow, 50, 200, keltner_period))}
            self.signal = EMA(macd_signal)
            self.triple = [EMA(trix_period) for _ in range(3)]
            self.trix_signal = EMA(trix_signal)
        self.closes = deque(maxlen=200)
        self.medians = deque(maxlen=34)
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
        for n in (20, 50, 200):
            ready = self.count >= n
            average = sum(list(self.closes)[-n:]) / n if ready else None
            result[f"sma_{n}"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": n,
                                    "value": str(average) if ready else None}
            result[f"sma_distance_{n}_percent"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": n,
                "value": str(100 * (close / average - 1)) if ready else None, "unit": "percent", "basis": "CLOSE_OVER_SMA_MINUS_ONE"}
        if high is not None:
            self.medians.append((high + low) / 2)
        ready = len(self.medians) == 34
        result["awesome_5_34"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": 34,
            "value": str(sum(list(self.medians)[-5:]) / 5 - sum(self.medians) / 34) if ready else None,
            "basis": "SMA5_MINUS_SMA34_OF_HIGH_LOW_MIDPOINT"}
        if self.previous is not None:
            move = close - self.previous
            gain, loss = max(Decimal(0), move), max(Decimal(0), -move)
            if self.count <= self.rsi_period + 1:
                self.gain += gain
                self.loss += loss
                if self.count == self.rsi_period + 1:
                    self.gain /= self.rsi_period
                    self.loss /= self.rsi_period
            else:
                self.gain = (self.gain * (self.rsi_period - 1) + gain) / self.rsi_period
                self.loss = (self.loss * (self.rsi_period - 1) + loss) / self.rsi_period
        ready = self.count >= self.rsi_period + 1
        rsi = 100 * self.gain / (self.gain + self.loss) if self.gain + self.loss else Decimal(50)
        result[self.rsi_key] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": self.rsi_period + 1,
                            "value": str(rsi) if ready else None, "smoothing": "WILDER", "flat_series_value": "50"}
        line = self.emas[self.macd_fast].value - self.emas[self.macd_slow].value
        if self.emas[self.macd_slow].ready:
            self.signal.update(line)
        ready = self.signal.ready
        result[self.macd_key] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": self.macd_slow + self.macd_signal - 1,
            "line": str(line) if self.emas[self.macd_slow].ready else None, "signal": str(self.signal.value) if ready else None,
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
        result[self.trix_key] = {"status": "AVAILABLE" if self.trix_signal.ready else "WARMUP", "required_bars": 3 * self.trix_period + self.trix_signal_period - 2,
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
                if self.range_count <= self.range_period:
                    self.atr += tr
                    self.plus += plus
                    self.minus += minus
                    if self.range_count == self.range_period:
                        self.atr /= self.range_period
                        self.plus /= self.range_period
                        self.minus /= self.range_period
                else:
                    self.atr = (self.atr * (self.range_period - 1) + tr) / self.range_period
                    self.plus = (self.plus * (self.range_period - 1) + plus) / self.range_period
                    self.minus = (self.minus * (self.range_period - 1) + minus) / self.range_period
                if self.range_count >= self.range_period:
                    self.dx_count += 1
                    dx = 100 * abs(self.plus - self.minus) / (self.plus + self.minus) if self.plus + self.minus else Decimal(0)
                    self.adx = self.adx + dx if self.dx_count <= self.range_period else (self.adx * (self.range_period - 1) + dx) / self.range_period
                    if self.dx_count == self.range_period:
                        self.adx /= self.range_period
            self.previous_range = high, low, close
        ready = self.range_count >= self.range_period
        result[f"atr_{self.range_period}"] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": self.range_period + 1,
                            "value": str(self.atr) if ready else None, "smoothing": "WILDER"}
        result[self.adx_key] = {"status": "AVAILABLE" if self.dx_count >= self.range_period else "WARMUP", "required_bars": 2 * self.range_period,
            "value": str(self.adx) if self.dx_count >= self.range_period else None,
            "plus_di": str(100 * self.plus / self.atr if self.atr else Decimal(0)) if ready else None,
            "minus_di": str(100 * self.minus / self.atr if self.atr else Decimal(0)) if ready else None}
        ready = ready and self.emas[self.keltner_period].ready
        middle = self.emas[self.keltner_period].value
        result[self.keltner_key] = {"status": "AVAILABLE" if ready else "WARMUP", "required_bars": max(self.keltner_period, self.range_period + 1),
            "middle": str(middle) if ready else None, "upper": str(middle + self.multiplier * self.atr) if ready else None,
            "lower": str(middle - self.multiplier * self.atr) if ready else None}
        self.previous = close
        return result
