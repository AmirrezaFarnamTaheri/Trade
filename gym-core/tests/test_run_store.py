"""Run artifacts are atomic, immutable and confined to validated filenames."""
import json
import os

import pytest

from gym.adapters.run_store import list_runs, load_run, run_path, save_run

RUN_ID = "0123456789abcdef"


def test_save_is_idempotent_and_refuses_different_results(tmp_path):
    record = {"run_id": RUN_ID, "inputs": {}, "result": {"end": {"net": "1"}}}
    path = save_run(record, tmp_path)
    assert save_run(record, tmp_path) == path
    with pytest.raises(ValueError, match="different results"):
        save_run({**record, "result": {"end": {"net": "2"}}}, tmp_path)
    assert json.loads(path.read_text("utf-8")) == record
    assert len(list(tmp_path.iterdir())) == 1
    assert list_runs(tmp_path) == [{"run_id": RUN_ID, "inputs": {}, "end": {"net": "1"}}]
    assert load_run(tmp_path, RUN_ID)["capital_decisions"] == []


def test_competing_save_never_overwrites_a_run(tmp_path, monkeypatch):
    record = {"run_id": RUN_ID, "result": "first"}
    competitor = {"run_id": RUN_ID, "result": "second"}
    link = os.link

    def competing_link(source, destination):
        destination.write_text(json.dumps(competitor), "utf-8")
        link(source, destination)

    monkeypatch.setattr(os, "link", competing_link)
    with pytest.raises(ValueError, match="different results"):
        save_run(record, tmp_path)
    assert json.loads(run_path(tmp_path, RUN_ID).read_text("utf-8")) == competitor
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("run_id", ["../escape", "ABCDEF0123456789", "0123456789abcde", "0123456789abcdef.json"])
def test_invalid_run_ids_are_rejected(tmp_path, run_id):
    with pytest.raises(ValueError, match="16 lowercase hex"):
        run_path(tmp_path, run_id)


def test_run_list_pages_and_filters_newest_first(tmp_path):
    for i in range(5):
        record = {"run_id": f"{i:016x}", "inputs": {"symbol": "BTCTMN" if i % 2 else "ETHTMN", "strategy": "ema-trend"},
                  "result": {"end": {"net": str(i)}}}
        os.utime(save_run(record, tmp_path), ns=(i * 10**9, i * 10**9))
    def ids(rows):
        return [int(row["run_id"], 16) for row in rows]
    assert ids(list_runs(tmp_path, limit=2)) == [4, 3]
    assert ids(list_runs(tmp_path, limit=2, offset=2)) == [2, 1]
    assert ids(list_runs(tmp_path, symbol="BTCTMN")) == [3, 1]
    assert ids(list_runs(tmp_path, limit=1, offset=1, symbol="ETHTMN")) == [2]
    assert list_runs(tmp_path, strategy="sma-reversion") == []
