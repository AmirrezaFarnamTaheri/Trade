"""Causal long/flat hypotheses; reference prices do not imply executable arbitrage."""
from collections import deque
from datetime import timedelta
from decimal import Decimal

from .cross_market_models import CausalPremiumMoments, ar1_half_life
from .strategy import digest


class TomanPremium:
    name = "toman-premium"
    requires_position_context = True

    def __init__(self, entry_bps=50, exit_bps=0, conversion_cost_bps=20, max_skew_seconds=10,
                 z_entry=0, z_exit=0, half_life_multiple=0):
        if (type(z_entry) is not int or type(z_exit) is not int or type(half_life_multiple) is not int
                or not 0 <= z_entry <= 8 or not 0 <= z_exit <= 8 or not 0 <= half_life_multiple <= 20
                or (z_exit or half_life_multiple) and not z_entry):
            raise ValueError("z-score exits require an enabled positive z_entry")
        self.params = {"entry_bps": entry_bps, "exit_bps": exit_bps,
                       "conversion_cost_bps": conversion_cost_bps, "max_skew_seconds": max_skew_seconds}
        if z_entry:
            self.params.update(z_entry=z_entry, z_exit=z_exit, half_life_multiple=half_life_multiple)
            self.version = 2
        self.z_entry, self.z_exit, self.half_life_multiple = z_entry, z_exit, half_life_multiple
        self.z_moments = CausalPremiumMoments()
        self.past_discounts = deque(maxlen=129)
        self.previous_bar_end, self.holding_since = None, None
        self.feature_values, self.ready = {}, False

    @staticmethod
    def reference_symbols(instrument):
        return (instrument.base + "USDT", "USDTTMN") if instrument.quote == "TMN" and instrument.base != "USDT" else ()

    def decide(self, snap, holding):
        quotes = {q.symbol: q for q in snap.auxiliary_quotes}
        required = (snap.symbol[:-3] + "USDT", "USDTTMN") if snap.symbol.endswith("TMN") and snap.symbol != "USDTTMN" else ()
        self.ready = False
        if self.z_entry and self.previous_bar_end is not None and self.previous_bar_end != snap.bar.start:
            self.z_moments.reset()
            self.past_discounts.clear()
            self.holding_since = None
        self.feature_values = {"conversion_cost_bps": self.params["conversion_cost_bps"], "hypothesis": "TMN discount to observed cross-market bounds; not executable arbitrage"}
        if not required:
            return self.answer("ABSTAIN_UNSUPPORTED_QUOTE", "requires an asset/TMN market and distinct asset/USDT and USDT/TMN references")
        if snap.bid is None or snap.ask is None:
            return self.answer("ABSTAIN_NO_QUOTE", "fresh primary quote required")
        if any(symbol not in quotes for symbol in required):
            return self.answer("ABSTAIN_NO_REFERENCE", "both fresh open-market conversion legs required")
        legs = [quotes[s] for s in required]
        times = [snap.quote_time, *[q.ts_avail for q in legs]]
        if max(times) - min(times) > timedelta(seconds=self.params["max_skew_seconds"]):
            return self.answer("ABSTAIN_REFERENCE_SKEW", "observed quote clocks exceed declared alignment bound")
        fee = Decimal(snap.execution["fee_rate"])
        cost = (1 / (1 - fee)**2 - 1) * 10000 + self.params["conversion_cost_bps"]
        fair_bid, fair_ask = legs[0].bid * legs[1].bid, legs[0].ask * legs[1].ask
        discount, remaining = (fair_bid / snap.ask - 1) * 10000, (fair_ask / snap.bid - 1) * 10000
        self.feature_values.update(discount_bps=str(discount), remaining_discount_bps=str(remaining), roundtrip_cost_bps=str(cost))
        self.ready = True
        if self.z_entry:
            # The current discount cannot influence the mean, variance or
            # mean-reversion half-life used by its own trading decision.
            z = self.z_moments.score(discount)
            self.ready = z is not None
            fit = ar1_half_life(list(self.past_discounts)) if len(self.past_discounts) >= 12 else None
            half = Decimal(fit["half_life_bars"]) if fit and fit["half_life_bars"] is not None else None
            self.feature_values.update(discount_z=str(z) if z is not None else None,
                                       z_sample_count=self.z_moments.count,
                                       half_life_bars=str(half) if half is not None else None,
                                       model="prior-ewma-discount/1", z_entry=self.z_entry,
                                       z_exit=self.z_exit, half_life_multiple=self.half_life_multiple)
            if holding:
                if self.holding_since is None:
                    self.holding_since = snap.bar.start
            else:
                self.holding_since = None
            age_bars = (Decimal((snap.bar.end - self.holding_since) // snap.bar.spec.step)
                        if holding and self.holding_since is not None else Decimal(0))
            duration_reached = (holding and half is not None and self.half_life_multiple > 0
                                and age_bars >= half * self.half_life_multiple)
            action = ("BUY_REQUEST" if not holding and z is not None and z >= self.z_entry and
                      discount > cost + self.params["entry_bps"] else
                      "SELL_REQUEST" if holding and (duration_reached or
                          z is not None and z <= self.z_exit) else
                      "ABSTAIN_WARMUP" if not holding and z is None else "HOLD")
            reason = "prior-only z-score and fitted half-life; not executable arbitrage"
            self.z_moments.observe(discount)
            self.past_discounts.append(discount)
            self.previous_bar_end = snap.bar.end
            return self.answer(action, reason)
        action = ("BUY_REQUEST" if not holding and discount > self.params["entry_bps"] + cost else
                  "SELL_REQUEST" if holding and remaining <= self.params["exit_bps"] else "HOLD")
        return self.answer(action, "declared discount/cost/reversion rule")

    def answer(self, action, reason):
        return action, Decimal(int(action in ("BUY_REQUEST", "SELL_REQUEST"))), (reason,), digest(self.feature_values)[:16]


class LeadLag:
    name = "lead-lag"
    requires_position_context = True
    same_quote_reference = True

    def __init__(self, lookback=20, reference="ETHUSDT", entry_bps=50, lag_bps=30,
                 max_skew_seconds=10, delay_bars=0):
        if type(delay_bars) is not int or not 0 <= delay_bars <= 12:
            raise ValueError("optional lead-lag delay must be 0..12")
        self.params = {"lookback": lookback, "reference": reference, "entry_bps": entry_bps,
                       "lag_bps": lag_bps, "max_skew_seconds": max_skew_seconds}
        if delay_bars:
            self.params["delay_bars"] = delay_bars
            self.version = 2
        self.delay_bars = delay_bars
        self.reference_symbol = reference
        self.history, self.last_end = deque(maxlen=lookback + delay_bars + 1), None
        self.feature_values, self.ready = {}, False

    def decide(self, snap, holding):
        if self.last_end != snap.bar.start:
            self.history.clear()
        self.last_end, self.ready = snap.bar.end, False
        self.feature_values = {"reference": self.reference_symbol}
        reference = snap.reference
        action, reason = "ABSTAIN_WARMUP", "continuous aligned reference history required"
        if snap.bid is None or snap.ask is None or reference is None:
            self.history.clear()
            action, reason = "ABSTAIN_NO_REFERENCE", "fresh primary and reference quotes required"
        elif abs(reference.ts_avail - snap.quote_time) > timedelta(seconds=self.params["max_skew_seconds"]):
            self.history.clear()
            action, reason = "ABSTAIN_REFERENCE_SKEW", "observed quote clocks exceed declared alignment bound"
        else:
            self.history.append((snap.bar.close, (reference.bid + reference.ask) / 2))
            if len(self.history) == self.history.maxlen:
                primary = (snap.bar.close / self.history[-(self.params["lookback"] + 1)][0] - 1) * 10000
                leader_end = self.history[-(self.delay_bars + 1)][1]
                leader_start = self.history[-(self.delay_bars + self.params["lookback"] + 1)][1]
                leader = (leader_end / leader_start - 1) * 10000
                fee = Decimal(snap.execution["fee_rate"])
                friction = (1 / (1 - fee)**2 - 1 + (snap.ask - snap.bid) / snap.bid) * 10000
                lag = leader - primary
                self.ready = True
                self.feature_values.update(primary_return_bps=str(primary), leader_return_bps=str(leader), lag_bps=str(lag), roundtrip_cost_bps=str(friction))
                if self.delay_bars:
                    self.feature_values["delay_bars"] = self.delay_bars
                action = ("BUY_REQUEST" if not holding and primary >= 0 and leader > self.params["entry_bps"] and lag > self.params["lag_bps"] + friction else
                          "SELL_REQUEST" if holding and (leader <= 0 or lag <= self.params["lag_bps"]) else "HOLD")
                reason = "declared leader/follower/cost rule; no causal edge established"
        return action, Decimal(int(action in ("BUY_REQUEST", "SELL_REQUEST"))), (reason,), digest(self.feature_values)[:16]
