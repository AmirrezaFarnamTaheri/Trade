"""Operational campaign containment and coverage preserve failed and unfinished work."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest


@pytest.fixture
def campaign():
    spec = importlib.util.spec_from_file_location("market_campaign", Path(__file__).parents[1]/"scripts/market_campaign.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_checkpoint_publication_preserves_previous_receipt(tmp_path,campaign,monkeypatch):
    path = tmp_path/"receipt.json"
    campaign.write(path,{"state":"RUNNING"})
    def broken(value, output, **kwargs):
        output.write('{"partial":')
        raise ValueError("cannot encode")
    monkeypatch.setattr(campaign.json,"dump",broken)
    with pytest.raises(ValueError):
        campaign.write(path,{"state":"FINISHED"})
    assert json.loads(path.read_text()) == {"state":"RUNNING"}
    assert list(tmp_path.iterdir()) == [path]


def test_watch_verifies_engine_before_starting_any_attempt(tmp_path,campaign,monkeypatch):
    campaign.write(tmp_path/"plan.json",{"engine_digest":"expected"})
    monkeypatch.setattr("gym.services.research_protocol._engine_digest",lambda:"changed")
    with pytest.raises(AssertionError,match="frozen prospective engine"):
        asyncio.run(campaign.watch_worker(tmp_path,0,1))
    assert not (tmp_path/"prospective").exists()


def test_windows_reader_contention_retries_publication_without_losing_old_receipt(tmp_path,campaign,monkeypatch):
    path = tmp_path/"receipt.json"
    campaign.write(path,{"state":"RUNNING"})
    replace, calls = campaign.os.replace, []
    def contended(source,target):
        calls.append(target)
        if len(calls) < 3:
            assert json.loads(path.read_text()) == {"state":"RUNNING"}
            raise PermissionError("reader held open")
        replace(source,target)
    monkeypatch.setattr(campaign.os,"replace",contended)
    monkeypatch.setattr(campaign.time,"sleep",lambda _:None)
    campaign.write(path,{"state":"FINISHED"})
    assert len(calls) == 3 and json.loads(path.read_text()) == {"state":"FINISHED"}
    calls.clear()
    monkeypatch.setattr(campaign.os,"replace",lambda *_:(_ for _ in ()).throw(PermissionError("persistent lock")))
    with pytest.raises(PermissionError):
        campaign.write(path,{"state":"FAILED"})
    assert json.loads(path.read_text()) == {"state":"FINISHED"}
    assert list(tmp_path.iterdir()) == [path]


def test_runner_labels_its_wall_limit_in_saved_abort(tmp_path,campaign,monkeypatch):
    from tests.support import market_db
    db = market_db(tmp_path,[])
    db.c.close()
    campaign.write(tmp_path/"plan.json",{"engine_digest":"frozen","data":str(tmp_path),"running_seconds":900,
        "wall_limit_seconds":0.01,"fee_rate":"0.001","latency_ms":500,
        "prospective":[{"symbol":"BTCUSDT","cash":"1000","strategy":"ema-trend","params":{}}]})
    (tmp_path/"prospective").mkdir()
    monkeypatch.setattr("gym.services.research_protocol._engine_digest",lambda:"frozen")
    async def observe(*args,**kwargs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError as error:
            return {"reason":str(error),"result":{"session":{"state":"ABORTED"}}}
    monkeypatch.setattr("gym.services.live_paper.watch",observe)
    monkeypatch.setattr(campaign,"inspect",lambda out:{"termination_reason":out["reason"]})
    asyncio.run(campaign.watch_worker(tmp_path,0,1))
    receipt = campaign.read(tmp_path/"prospective/0000.json")
    assert receipt["state"] == "ABORTED"
    assert receipt["termination_reason"] == "Campaign wall limit reached"


def test_interrupt_kills_active_base_process_and_cancels_queued_markets(tmp_path,campaign,monkeypatch):
    campaign.write(tmp_path/"plan.json",{"universe":[{"symbol":symbol,"spot_status":"ELIGIBLE_SPOT"} for symbol in ("AUSDT","BUSDT","CUSDT")]})
    started, killed = threading.Event(), threading.Event()
    calls = []
    class Child:
        def __init__(self,command,**kwargs):
            calls.append(command)
            started.set()
        def wait(self,timeout):
            assert killed.wait(3)
            return 1
        def poll(self):
            return 1 if killed.is_set() else None
        def kill(self):
            killed.set()
    def interrupt(_):
        assert started.wait(3)
        raise KeyboardInterrupt()
    monkeypatch.setattr(campaign.subprocess,"Popen",Child)
    monkeypatch.setattr(campaign,"as_completed",interrupt)
    with pytest.raises(KeyboardInterrupt):
        campaign.launch(SimpleNamespace(output=tmp_path,workers=1),"history")
    assert killed.is_set() and len(calls) == 1
    assert "--runtime-site" in calls[0]
    assert campaign.read(tmp_path/"history-interrupted.json")["state"] == "INTERRUPTED_INSPECT_REGISTRY"
    assert not (tmp_path/"history-finished.json").exists()


def test_timed_out_market_is_not_retried_or_reported_complete(tmp_path,campaign,monkeypatch):
    campaign.write(tmp_path/"plan.json",{"universe":[{"symbol":"AUSDT","spot_status":"ELIGIBLE_SPOT"}]})
    class Child:
        stopped = False
        def __init__(self,*args,**kwargs):
            pass
        def wait(self,timeout):
            if not self.stopped:
                raise subprocess.TimeoutExpired("paper",timeout)
            return 1
        def poll(self):
            return 1 if self.stopped else None
        def kill(self):
            self.stopped = True
    monkeypatch.setattr(campaign.subprocess,"Popen",Child)
    campaign.launch(SimpleNamespace(output=tmp_path,workers=1),"history")
    assert campaign.read(tmp_path/"history-finished.json")["outcomes"] == [{"item":"AUSDT","state":"TIMED_OUT_INSPECT_REGISTRY"}]


def test_report_keeps_every_unreported_case_and_venue_exclusion(tmp_path,campaign):
    request = {"symbol":"AUSDT","strategy":"ema-trend","resolution":"1min","trials":[{}],"windows":[{}],"scenarios":[{},{}]}
    plan = {"groups":[{"index":0,"request":request}],"universe":[
        {"symbol":"AUSDT","spot_status":"ELIGIBLE_SPOT"}, {"symbol":"BUSDT","spot_status":"VENUE_NOT_SPOT"}],
        "prospective":[{"symbol":"AUSDT"}],"engine_digest":"source","planned_historical":2}
    campaign.write(tmp_path/"plan.json",plan)
    campaign.report(SimpleNamespace(output=tmp_path))
    saved = campaign.read(tmp_path/"coverage.json")
    assert saved["historical_states"] == {"NOT_REPORTED":2}
    assert len(saved["markets"]) == 2 and saved["markets"][1]["planned"] == 0
    assert saved["prospective"]["original"]["states"] == {"NOT_STARTED":1}
    assert len((tmp_path/"results.csv").read_text(encoding="utf-8-sig").splitlines()) == 3
    assert not saved["funded_authority"]
    first = tmp_path/"historical-continuation"
    second = first/"historical-continuation"
    second.mkdir(parents=True)
    for source in (first,second):
        campaign.write(source/"plan.json",plan)
    (second/"historical").mkdir()
    campaign.write(second/"historical/AUSDT.json",{"groups":[{"index":0,"attempts":[
        {"trial":0,"window":0,"scenario":index,"state":"COMPLETED"} for index in (0,1)]}]})
    campaign.report(SimpleNamespace(output=tmp_path))
    assert campaign.read(tmp_path/"coverage.json")["historical_states"] == {"COMPLETED":2}
    assert campaign.read(tmp_path/"coverage.json")["all_registered_attempts_including_repeats"] == 6
    assert "historical-continuation/historical-continuation" in (tmp_path/"results.csv").read_text(encoding="utf-8-sig")


def test_recovery_retains_partial_group_before_registering_repeat(tmp_path,campaign,monkeypatch):
    from gym.services.experiment_registry import ExperimentRegistry
    data = tmp_path/"data"
    request = {"symbol":"AUSDT","hypothesis":"original","trials":[{}],"windows":[{}],"scenarios":[{},{}]}
    plan = {"data":str(data),"engine_digest":"frozen","groups":[{"index":0,"purpose":"comparison","request":request}],"prospective":[],"margin":[]}
    campaign.write(tmp_path/"plan.json",plan)
    (tmp_path/"historical").mkdir()
    campaign.write(tmp_path/"historical/AUSDT.json",{"state":"RUNNING","groups":[]})
    (tmp_path/"engine/gym").mkdir(parents=True)
    with pytest.raises(ValueError,match="Stop and inspect"):
        campaign.recover_history(SimpleNamespace(output=tmp_path))
    campaign.write(tmp_path/"history-interrupted.json",{"state":"INTERRUPTED"})
    with ExperimentRegistry(data,store="live") as registry:
        parent = registry.append("EXPERIMENT",None,{"definition":request})["id"]
        for scenario in (0,1):
            attempt = registry.append("ATTEMPT",parent,{"trial":0,"window":0,"scenario":scenario})
            if scenario == 0:
                registry.append("RESULT",parent,{"attempt_id":attempt["id"],"state":"FAILED","reason":"NO_QUALIFIED_DATA"})
    campaign.recover_history(SimpleNamespace(output=tmp_path))
    recovered = campaign.read(tmp_path/"historical-continuation/plan.json")
    assert recovered["recovery"][0]["prior_experiment"] == parent
    assert recovered["recovery"][0]["prior_results"] == 1
    assert recovered["planned_historical"] == 2
    assert campaign.read(tmp_path/"historical-continuation/prior-checkpoints/AUSDT.json")["state"] == "RUNNING"
    retained = campaign.read(tmp_path/"historical/AUSDT.json")["groups"][0]["attempts"]
    assert [row["state"] for row in retained] == ["FAILED","RESULT_PENDING"]
    with pytest.raises(ValueError,match="already registered"):
        campaign.recover_history(SimpleNamespace(output=tmp_path))
