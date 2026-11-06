"""Native indicator triggers, persistence, scheduling and decision inspection together."""
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from gym.adapters.run_store import load_verified_run, save_run
from gym.domain.model import BookTop, iso
from gym.services.paper import paper
from gym.services.replay_debugger import replay_decisions
from gym.services.research_ledger import ResearchLedger
from tests.support import START, market_db


def recovery_quotes(name,wide_history=False,scale=Decimal(1)):
    prices = [Decimal(100)+Decimal(i)/10 for i in range(70)]
    if name=="trend-pullback":
        prices += [prices[-1]-Decimal('1.1')+Decimal(i)*Decimal('.4') for i in range(14)]
    else:
        prices += [prices[-1]-Decimal(i)/5 for i in range(1,9)]
        prices += [prices[-1]+Decimal(i)/5 for i in range(1,18)]
    prices += [prices[-1]-Decimal(i)/10 for i in range(1,15)]
    return [BookTop("BTCUSDT",START+timedelta(minutes=index,seconds=second),(price+offset-spread)*scale,
            (price+offset+spread)*scale,Decimal(100)/scale,Decimal(100)/scale,frozenset())
            for index,price in enumerate(prices) for spread in (Decimal('.2') if wide_history and index<70 else Decimal('.01'),)
            for second,offset in ((0,Decimal(0)),(15,Decimal('.2')),(30,Decimal('-.2')),(59,Decimal(0)))]


@pytest.mark.parametrize("name",["trend-pullback","adaptive-channel"])
@pytest.mark.parametrize("wide_history",[False,True])
@pytest.mark.parametrize("scale",[Decimal(1),Decimal('1E-9')])
def test_native_compound_trigger_survives_schedule_save_and_verified_debugger(tmp_path,name,wide_history,scale):
    rows = recovery_quotes(name,wide_history,scale)
    db = market_db(tmp_path,rows)
    db.c.execute("INSERT INTO instrument_specs(instrument_id,valid_from,spec,source) VALUES(?,?,?,?)",
        ("wallex:BTCUSDT",iso(START),'{"stepSize":3,"minNotional":"0.5"}',"synthetic-test"))
    db.c.commit()
    end = rows[-1].ts_avail+timedelta(seconds=1)
    try:
        out = paper(db,"BTCUSDT",START,end,resolution="1min",strategy_id=name)
        assert out["inputs"]["strategy_version"]==3
        assert out["result"]["fills"]>=2, "Exercise native entries and exits, not an always-abstaining fixture"
        assert not any(row["action"] in ("ABSTAIN_INVALID_EXECUTION_CONTEXT","ABSTAIN_UNKNOWN_POSITION") for row in out["result"]["decisions"])
        assert out == paper(db,"BTCUSDT",START,end,resolution="1min",strategy_id=name)
        json.dumps(out,allow_nan=False)
        save_run(out,tmp_path/"runs")
        assert load_verified_run(tmp_path/"runs",out["run_id"],store="live")==json.loads(json.dumps(out))
        replay = replay_decisions(tmp_path/"runs",{"run_id":out["run_id"],"offset":0,"limit":200},store="live")
        for row,decision in zip(replay["decisions"],out["result"]["decisions"]):
            assert row["known_at_decision"]["execution_known"] == decision["execution_known"]
            assert row["known_at_decision"]["execution_snapshot"] == decision["execution_snapshot"]
        with ResearchLedger(tmp_path/"research.sqlite3") as ledger:
            hid = ledger.register({"symbol":"BTCUSDT","strategy":name,"params":{}})["hypothesis_id"]
            seconds = int((end-START).total_seconds())
            ledger.schedule({"hypothesis_id":hid,"every_seconds":seconds,"lookback_seconds":seconds,
                "first_at":iso(end),"resolution":"1min","cash":"1000","fee_rate":"0.001"})
            due = ledger.run_due(db,iso(end))
            assert len(due["completed"])==1 and not due["failed"]
            saved = json.loads(ledger.conn.execute("SELECT body FROM reports").fetchone()[0])
            assert saved["run_id"]==out["run_id"]
            assert not ledger.run_due(db,iso(end))["completed"]
    finally:
        db.c.close()
