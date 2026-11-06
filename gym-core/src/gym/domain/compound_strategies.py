"""Closed-bar composite research rules with actual-fill state and explicit cost/risk budgets."""
from datetime import timedelta
from decimal import Decimal

from .market_models import decimal
from .model import parse_ts
from .strategy import digest
from .technical_features import TechnicalFeatures

PARAMETERS = {
    "risk_bps":{"type":"integer","default":50,"minimum":1,"maximum":200},
    "allocation_bps":{"type":"integer","default":2500,"minimum":1,"maximum":10000},
    "max_spread_bps":{"type":"integer","default":25,"minimum":1,"maximum":1000},
    "participation_bps":{"type":"integer","default":1000,"minimum":1,"maximum":10000},
    "stop_atr":{"type":"integer","default":2,"minimum":1,"maximum":5},
    "reward_risk":{"type":"integer","default":2,"minimum":1,"maximum":5},
    "cooldown_bars":{"type":"integer","default":3,"minimum":0,"maximum":100},
    "max_holding_bars":{"type":"integer","default":60,"minimum":1,"maximum":1000},
    "max_drawdown_bps":{"type":"integer","default":300,"minimum":50,"maximum":2000},
}


class CompoundStrategy:
    def __init__(self,**params):
        if params.keys()-PARAMETERS.keys():
            raise ValueError("unsupported compound parameters")
        self.params = {key:params.get(key,spec["default"]) for key,spec in PARAMETERS.items()}
        for key,value in self.params.items():
            if type(value) is not int or not PARAMETERS[key]["minimum"] <= value <= PARAMETERS[key]["maximum"]:
                raise ValueError("invalid compound parameter: "+key)
        self.execution_limits = {key:self.params[key] for key in ("max_spread_bps","participation_bps")}
        self.features = TechnicalFeatures()
        self.previous = self.last_bar = None
        self.feature_values = {}
        self.was_holding = False
        self.position_id = self.peak = self.trailing_stop = None
        self.cooldown = 0
        self.equity_high = None
        self.drawdown_locked = False

    @property
    def ready(self):
        return self.features.count >= 50

    def reply(self,action,reason,fraction=Decimal(0)):
        return action,fraction,(reason,),digest(self.feature_values)[:16]

    def reset_history(self):
        self.features,self.previous,self.last_bar = TechnicalFeatures(),None,None
        self.feature_values["observations"] = 0

    def risk_exit(self,snap,context,atr=None):
        entry,stop = decimal(context["entry_price"],"entry",positive=True),decimal(context["stop_price"],"stop",positive=True)
        if self.position_id != context["position_id"]:
            self.position_id,self.peak,self.trailing_stop = context["position_id"],entry,stop
        self.peak = max(self.peak,snap.bid)
        if atr is not None:
            self.trailing_stop = max(self.trailing_stop,self.peak-self.params["stop_atr"]*atr)
        risk = entry-stop
        if snap.bid >= entry+risk:
            self.trailing_stop = max(self.trailing_stop,entry/(1-decimal(context["fee_rate"],"fee")))
        target = entry+self.params["reward_risk"]*risk
        self.feature_values.update(stop_price=str(self.trailing_stop),target_price=str(target),peak_bid=str(self.peak))
        if snap.bid <= self.trailing_stop:
            return "PAPER_STOP_TRIGGER"
        if snap.bid >= target:
            return "PAPER_TARGET_TRIGGER"
        if snap.as_of-parse_ts(context["entry_time"]) >= snap.bar.spec.step*self.params["max_holding_bars"]:
            return "PAPER_MAX_HOLDING_TIME"
        return None

    def decide(self,snap,holding):
        self.feature_values = {"observations":self.features.count,"required_bars":50,"regime":"UNKNOWN",
                               "execution_limits":dict(self.execution_limits)}
        if type(holding) is not bool:
            return self.reply("ABSTAIN_UNKNOWN_HOLDINGS","actual holding state unavailable")
        bar = snap.bar
        if (bar.forming or bar.end>snap.as_of or bar.avail>snap.as_of
                or any(not value.is_finite() or value<=0 for value in (bar.open,bar.high,bar.low,bar.close))
                or not bar.low<=min(bar.open,bar.close)<=max(bar.open,bar.close)<=bar.high):
            return self.reply("ABSTAIN_UNAVAILABLE_BAR","need a closed, available, valid OHLC bar")
        context = snap.execution
        if context is None:
            return self.reply("ABSTAIN_NO_EXECUTION_CONTEXT","fees, equity and displayed depth must be known")
        try:
            equity = decimal(context["equity"],"equity",positive=True)
            quantity = decimal(context["position_qty"],"position quantity")
            fee = decimal(context["fee_rate"],"fee")
            dust = context.get("position_state")=="DUST" and quantity>0 and decimal(context.get("tradable_qty"),"tradable quantity")==0
            if quantity<0 or not 0<=fee<1 or holding != (quantity>0 and not dust):
                raise ValueError("inconsistent position or fees")
            if holding:
                entry = decimal(context["entry_price"],"entry",positive=True)
                stop = decimal(context["stop_price"],"stop",positive=True)
                if not context["position_id"] or not 0<stop<entry or parse_ts(context["entry_time"])>snap.as_of:
                    raise ValueError("unknown fill identity or risk state")
        except (ValueError,TypeError,KeyError):
            return self.reply("ABSTAIN_UNKNOWN_POSITION" if holding else "ABSTAIN_INVALID_EXECUTION_CONTEXT","known actual fills and finite account context required")
        if (snap.bid is None or snap.ask is None or not snap.bid.is_finite() or not snap.ask.is_finite()
                or not 0<snap.bid<snap.ask or snap.quote_time is None
                or not timedelta(0)<=snap.as_of-snap.quote_time<=timedelta(seconds=120)):
            return self.reply("ABSTAIN_NO_QUOTE","no fresh available two-sided quote")
        self.equity_high = max(self.equity_high or equity,equity)
        drawdown = (1-equity/self.equity_high)*10000
        self.drawdown_locked |= drawdown>=self.params["max_drawdown_bps"]
        self.feature_values.update(drawdown_bps=str(drawdown),drawdown_locked=self.drawdown_locked)
        if self.drawdown_locked:
            return self.reply("SELL_REQUEST" if holding else "ABSTAIN_DRAWDOWN","PAPER_SESSION_DRAWDOWN_LOCK",Decimal(int(holding)))
        if self.was_holding and not holding:
            self.cooldown = self.params["cooldown_bars"]
            self.position_id = self.peak = self.trailing_stop = None
        self.was_holding = holding
        risk_exit = self.risk_exit(snap,context) if holding else None
        spread = (snap.ask-snap.bid)/((snap.ask+snap.bid)/2)*10000
        self.feature_values["spread_bps"] = str(spread)
        if spread>self.params["max_spread_bps"]:
            self.reset_history()
            return self.reply("SELL_REQUEST",risk_exit,Decimal(1)) if risk_exit else self.reply("HOLD" if holding else "ABSTAIN_SPREAD","entry spread exceeds configured limit")
        if self.last_bar and bar.start!=self.last_bar.end:
            self.reset_history()
        if self.last_bar and abs(bar.close/self.last_bar.close-1)>Decimal('.05'):
            self.reset_history()
            return self.reply("SELL_REQUEST",risk_exit,Decimal(1)) if risk_exit else self.reply("HOLD" if holding else "ABSTAIN_PRICE_JUMP","bar move exceeds 5%; require a new continuous history")
        before,last_bar = self.previous,self.last_bar
        current = self.features.update(bar.close,high=bar.high,low=bar.low)
        self.previous,self.last_bar = current,bar
        self.feature_values.update(observations=self.features.count,indicators=current)
        atr = Decimal(current["atr_14"]["value"]) if current["atr_14"]["value"] is not None else None
        if holding:
            risk_exit = self.risk_exit(snap,context,atr)
            if risk_exit:
                return self.reply("SELL_REQUEST",risk_exit,Decimal(1))
        if not self.ready:
            return self.reply("HOLD" if holding else "ABSTAIN_WARMUP","need 50 continuous usable closed bars")
        ema20,ema50 = (Decimal(current[f"ema_{n}"]["value"]) for n in (20,50))
        adx = Decimal(current["adx_14"]["value"])
        up = ema20>ema50 and Decimal(current["ema_20"]["slope_5_bars"])>0 and Decimal(current["adx_14"]["plus_di"])>Decimal(current["adx_14"]["minus_di"])
        regime = "UP_TREND" if adx>=25 and up else "DOWN_TREND" if adx>=25 and ema20<ema50 else "RANGE" if adx<=18 and atr and abs(ema20-ema50)<=atr else "TRANSITION"
        self.feature_values["regime"] = regime
        if holding:
            if regime=="DOWN_TREND" or self.name=="adaptive-channel" and regime=="RANGE" and bar.close>=ema20:
                return self.reply("SELL_REQUEST","REGIME_EXIT",Decimal(1))
            return self.reply("HOLD","actual position remains inside its paper risk limits")
        if self.cooldown:
            self.cooldown -= 1
            return self.reply("ABSTAIN_COOLDOWN","cooldown after an observed exit fill")
        try:
            bid_qty = decimal(context["bid_qty"],"displayed bid quantity",positive=True)
            ask_qty = decimal(context["ask_qty"],"displayed ask quantity",positive=True)
        except (ValueError,TypeError,KeyError):
            return self.reply("ABSTAIN_NO_LIQUIDITY","fresh displayed quantities required")
        if atr is None or atr<=0 or atr/bar.close>Decimal('.02'):
            return self.reply("ABSTAIN_VOLATILITY","ATR must be positive and no more than 2% of price")
        rsi = Decimal(current["rsi_14"]["value"])
        if self.name=="trend-pullback":
            trigger = regime=="UP_TREND" and before and last_bar and last_bar.close<=Decimal(before["ema_20"]["value"]) and bar.close>ema20 and 40<=rsi<=70
            room = self.params["reward_risk"]*max(Decimal(50),self.params["stop_atr"]*atr/snap.ask*10000)
        elif regime=="UP_TREND":
            trigger = before and last_bar and last_bar.close<=Decimal(before["keltner_20_14_2"]["upper"]) and bar.close>Decimal(current["keltner_20_14_2"]["upper"]) and Decimal(current["macd_12_26_9"]["histogram"])>0
            room = self.params["reward_risk"]*max(Decimal(50),self.params["stop_atr"]*atr/snap.ask*10000)
        else:
            trigger = regime=="RANGE" and before and last_bar and last_bar.close<=Decimal(before["keltner_20_14_2"]["lower"]) and bar.close>Decimal(current["keltner_20_14_2"]["lower"]) and 30<=rsi<=55
            room = (ema20/snap.ask-1)*10000
        if not trigger:
            return self.reply("HOLD","no confirmed pullback, breakout or range rebound in this regime")
        cost = spread+2*fee*10000+10  # Ten bps is a disclosed extra execution-cost allowance, not measured latency.
        stop_bps = max(Decimal(50),self.params["stop_atr"]*atr/snap.ask*10000)
        self.feature_values.update(round_trip_cost_bps=str(cost),target_room_bps=str(room),stop_distance_bps=str(stop_bps))
        if room<2*cost:
            return self.reply("ABSTAIN_COST","modeled target room must exceed twice the spread/fee/cost allowance")
        fraction = min(Decimal(self.params["allocation_bps"])/10000,
            Decimal(self.params["risk_bps"])/(stop_bps+cost),
            min(bid_qty,ask_qty)*snap.ask*self.params["participation_bps"]/10000/equity)
        self.feature_values["entry_fraction"] = str(fraction)
        return self.reply("BUY_REQUEST",regime+": confirmed composite entry; bounded by risk, cash and displayed capacity",fraction)


class TrendPullback(CompoundStrategy):
    name = "trend-pullback"


class AdaptiveChannel(CompoundStrategy):
    name = "adaptive-channel"
