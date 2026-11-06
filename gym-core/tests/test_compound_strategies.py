"""Complementary signals and actual-fill risk state, never assumed positions."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.bars import Bar, BarSpec
from gym.domain.registry import create_strategy, catalog
from gym.domain.strategy import Snapshot
from tests.support import START


NAMES = ("trend-pullback","adaptive-channel")


def snap(index=0,price="100",*, execution=True, **changes):
    at = START+timedelta(minutes=index+1)
    close = Decimal(price)
    bar = Bar("BTCUSDT",BarSpec("1min"),at-timedelta(minutes=1),at,at,
              close,close+Decimal('.2'),close-Decimal('.2'),close,Decimal(0),1)
    context = {"equity":"1000","position_qty":"0","bid_qty":"100","ask_qty":"100","fee_rate":"0.001",
               "entry_price":None,"stop_price":None,"entry_time":None,"position_id":None} if execution else None
    if context is not None:
        context.update(changes)
    return Snapshot(at,"BTCUSDT",bar,close-Decimal('.01'),close+Decimal('.01'),at,execution=context)


@pytest.mark.parametrize("name",NAMES)
def test_compound_requires_known_execution_context(name):
    strategy = create_strategy(name)
    assert any(row["id"]==name and row["mode"]=="PAPER_ONLY" for row in catalog())
    assert strategy.decide(snap(execution=False),False)[0] == "ABSTAIN_NO_EXECUTION_CONTEXT"


@pytest.mark.parametrize("name",NAMES)
def test_risk_exit_does_not_wait_for_indicator_warmup_or_narrow_spread(name):
    strategy = create_strategy(name)
    point = snap(price="90",position_qty="1",entry_price="100",stop_price="98",
                 entry_time=START.isoformat(),position_id="filled-order")
    point = replace(point,ask=Decimal(110))
    action,fraction,reasons,_ = strategy.decide(point,True)
    assert action == "SELL_REQUEST" and fraction == 1 and "STOP" in reasons[0]


@pytest.mark.parametrize("name",NAMES)
def test_missing_fill_identity_cannot_create_a_protected_position(name):
    strategy = create_strategy(name)
    action,*_ = strategy.decide(snap(position_qty="1"),True)
    assert action == "ABSTAIN_UNKNOWN_POSITION"


@pytest.mark.parametrize("name",NAMES)
def test_invalid_or_future_bar_never_advances_indicators_or_trades(name):
    strategy = create_strategy(name)
    point = snap()
    assert strategy.decide(replace(point,as_of=point.bar.start),False)[0] == "ABSTAIN_UNAVAILABLE_BAR"
    assert strategy.decide(point,False)[0] == "ABSTAIN_WARMUP"
    assert strategy.feature_values["observations"] == 1


@pytest.mark.parametrize("name",NAMES)
def test_missing_period_resets_warmup_but_stop_remains_usable(name):
    strategy = create_strategy(name)
    for index in range(60):
        strategy.decide(snap(index,str(Decimal(100)+Decimal(index)/100)),False)
    assert strategy.decide(snap(65,"101"),False)[0] == "ABSTAIN_WARMUP"
    assert strategy.feature_values["observations"] == 1
    assert strategy.decide(snap(66,"90",position_qty="1",entry_price="100",stop_price="98",
        entry_time=START.isoformat(),position_id="real-fill"),True)[0] == "SELL_REQUEST"


@pytest.mark.parametrize("name",NAMES)
def test_wide_market_remains_observed_but_cannot_generate_entry(name):
    strategy = create_strategy(name)
    point = snap()
    action = strategy.decide(replace(point,bid=Decimal(90),ask=Decimal(110)),False)[0]
    assert action == "ABSTAIN_SPREAD"


@pytest.mark.parametrize("name",NAMES)
def test_new_order_uses_bounded_risk_and_actual_displayed_capacity(name):
    strategy = create_strategy(name)
    # A deterministic pullback/recovery sequence exercises native indicators, not patched signals.
    prices = [Decimal(100)+Decimal(i)/10 for i in range(70)]
    if name=="trend-pullback":
        peak = prices[-1]
        prices += [peak-Decimal('1.1')+Decimal(i)*Decimal('.4') for i in range(14)]
    else:
        prices += [prices[-1]-Decimal(i)/5 for i in range(1,9)]
        prices += [prices[-1]+Decimal(i)/5 for i in range(1,18)]
    proposals = []
    for index,price in enumerate(prices):
        action,fraction,_,_ = strategy.decide(snap(index,str(price),bid_qty="0.2",ask_qty="0.2"),False)
        if action == "BUY_REQUEST":
            proposals.append((fraction,price))
            assert 0 < fraction <= Decimal('.25')
            assert fraction*1000 <= Decimal('.2')*(price+Decimal('.01'))*Decimal('.1')
            assert Decimal(strategy.feature_values["target_room_bps"]) > Decimal(strategy.feature_values["round_trip_cost_bps"])
            import json
            json.dumps(strategy.feature_values,allow_nan=False)
    assert proposals, "The declared recovery fixture must exercise an entry, not pass by always abstaining"


@pytest.mark.parametrize("name",NAMES)
@pytest.mark.parametrize("price,reason",[("105","TARGET"),("100","MAX_HOLDING")])
def test_real_position_targets_and_time_limits_work_without_indicator_history(name,price,reason):
    strategy = create_strategy(name,{"max_holding_bars":1})
    point = snap(2,price,position_qty="1",entry_price="100",stop_price="98",entry_time=START.isoformat(),position_id="fill")
    action,_,reasons,_ = strategy.decide(point,True)
    assert action == "SELL_REQUEST" and reason in reasons[0]


@pytest.mark.parametrize("name",NAMES)
def test_break_even_stop_tightens_and_is_not_rebased_by_price_recovery(name):
    strategy = create_strategy(name)
    context = {"position_qty":"1","entry_price":"100","stop_price":"98","entry_time":START.isoformat(),"position_id":"fill"}
    strategy.decide(snap(0,"102.1",**context),True)
    stop = Decimal(strategy.feature_values["stop_price"])
    assert stop >= Decimal(100)/Decimal('.999')
    action,_,reasons,_ = strategy.decide(snap(1,"100",**context),True)
    assert action == "SELL_REQUEST" and "STOP" in reasons[0]
    assert Decimal(strategy.feature_values["stop_price"]) >= stop


@pytest.mark.parametrize("name",NAMES)
def test_adverse_quote_time_and_bad_account_context_cannot_trade(name):
    strategy = create_strategy(name)
    point = snap()
    assert strategy.decide(replace(point,quote_time=point.as_of+timedelta(seconds=1)),False)[0] == "ABSTAIN_NO_QUOTE"
    assert strategy.decide(snap(equity="NaN"),False)[0] == "ABSTAIN_INVALID_EXECUTION_CONTEXT"
    assert strategy.decide(snap(position_qty="1"),False)[0] == "ABSTAIN_INVALID_EXECUTION_CONTEXT"
    assert strategy.features.count == 0


@pytest.mark.parametrize("name",NAMES)
def test_fee_cost_guard_uses_actual_scenario_fees(name):
    strategy = create_strategy(name)
    prices = [Decimal(100)+Decimal(i)/10 for i in range(70)]
    peak = prices[-1]
    if name=="trend-pullback":
        prices += [peak-Decimal('1.1')+Decimal(i)*Decimal('.4') for i in range(14)]
    else:
        prices += [peak-Decimal(i)/5 for i in range(1,9)]
        prices += [prices[-1]+Decimal(i)/5 for i in range(1,18)]
    actions = [strategy.decide(snap(index,str(price),fee_rate="0.01"),False)[0] for index,price in enumerate(prices)]
    assert "ABSTAIN_COST" in actions and "BUY_REQUEST" not in actions


@pytest.mark.parametrize("name",NAMES)
def test_future_extensions_do_not_change_earlier_decisions(name):
    def run(length):
        strategy = create_strategy(name)
        return [strategy.decide(snap(index,str(Decimal(100)+Decimal(index%13)/10)),False) for index in range(length)]
    assert run(100) == run(140)[:100]


@pytest.mark.parametrize("name",NAMES)
def test_invalid_risk_parameters_are_rejected_at_public_factory(name):
    for params in ({"risk_bps":True},{"risk_bps":201},{"allocation_bps":0},{"participation_bps":10001},{"stop_atr":0},{"unsupported":1}):
        with pytest.raises(ValueError):
            create_strategy(name,params)


@pytest.mark.parametrize("name",NAMES)
def test_drawdown_lock_exits_and_remains_latched_after_recovery(name):
    strategy = create_strategy(name)
    strategy.decide(snap(),False)
    point = snap(1,"99",equity="970",position_qty="1",entry_price="100",stop_price="95",
                 entry_time=START.isoformat(),position_id="fill")
    action,_,reasons,_ = strategy.decide(point,True)
    assert action == "SELL_REQUEST" and "DRAWDOWN" in reasons[0]
    assert strategy.decide(snap(2,"100",equity="1000"),False)[0] == "ABSTAIN_DRAWDOWN"


@pytest.mark.parametrize("name",NAMES)
def test_actual_exit_starts_cooldown_and_a_failed_exit_does_not(name):
    strategy = create_strategy(name)
    for index in range(60):
        strategy.decide(snap(index,str(Decimal(100)+Decimal(index)/10)),False)
    context = {"position_qty":"1","entry_price":"106","stop_price":"104","entry_time":(START+timedelta(minutes=60)).isoformat(),"position_id":"fill"}
    assert strategy.decide(snap(60,"103",**context),True)[0] == "SELL_REQUEST"
    assert strategy.decide(snap(61,"103",**context),True)[0] == "SELL_REQUEST"
    for index in range(62,65):
        assert strategy.decide(snap(index,"103"),False)[0] == "ABSTAIN_COOLDOWN"


@pytest.mark.parametrize("name",NAMES)
def test_wide_quote_preserves_history_but_blocks_entry(name):
    strategy = create_strategy(name)
    for index in range(60):
        strategy.decide(snap(index,str(Decimal(100)+Decimal(index)/100)),False)
    point = snap(60,"100.6")
    assert strategy.decide(replace(point,bid=Decimal('100.4'),ask=Decimal('100.8')),False)[0]=="ABSTAIN_SPREAD"
    assert strategy.feature_values["observations"] == 61 and strategy.ready


@pytest.mark.parametrize("name",NAMES)
def test_wide_spread_history_can_complete_indicator_warmup(name):
    strategy = create_strategy(name)
    for index in range(50):
        point = snap(index,str(Decimal(100)+Decimal(index)/100))
        action,*_ = strategy.decide(replace(point,bid=point.bid-Decimal('.2'),ask=point.ask+Decimal('.2')),False)
        assert action=="ABSTAIN_SPREAD"
    assert strategy.ready and strategy.feature_values["observations"]==50


@pytest.mark.parametrize("name",NAMES)
def test_wide_spread_does_not_suppress_a_confirmed_downtrend_exit(name):
    strategy = create_strategy(name,{"max_holding_bars":1000})
    for index in range(70):
        strategy.decide(snap(index,str(Decimal(110)-Decimal(index)/10)),False)
    point = snap(70,"103",position_qty="1",entry_price="103",stop_price="95",
        entry_time=(START+timedelta(minutes=70)).isoformat(),position_id="fill")
    action,_,reasons,_ = strategy.decide(replace(point,bid=Decimal('102.8'),ask=Decimal('103.2')),True)
    assert action=="SELL_REQUEST" and reasons==("REGIME_EXIT",)


def test_adaptive_range_rebound_uses_native_regime_and_channel():
    from math import sin,pi
    strategy = create_strategy("adaptive-channel")
    entries = []
    for index in range(150):
        point = snap(index,str(100+2*sin(index*2*pi/10)))
        point = replace(point,bar=replace(point.bar,high=point.bar.close+Decimal('.02'),low=point.bar.close-Decimal('.02')))
        action,_,reasons,_ = strategy.decide(point,False)
        if action=="BUY_REQUEST":
            entries.append(reasons[0])
    assert entries and all(reason.startswith("RANGE:") for reason in entries)


@pytest.mark.parametrize("name",NAMES)
def test_recorded_dust_exit_starts_cooldown_without_hiding_balance(name):
    strategy = create_strategy(name)
    for index in range(60):
        strategy.decide(snap(index,str(Decimal(100)+Decimal(index)/10)),False)
    context = {"position_qty":"1","entry_price":"106","stop_price":"104","entry_time":START.isoformat(),"position_id":"fill"}
    assert strategy.decide(snap(60,"103",**context),True)[0]=="SELL_REQUEST"
    for index in range(61,64):
        point = snap(index,"103",position_qty="0.00099",position_state="DUST",tradable_qty="0")
        assert strategy.decide(point,False)[0]=="ABSTAIN_COOLDOWN"
