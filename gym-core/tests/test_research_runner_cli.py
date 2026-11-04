import json

from gym.cli import main


def test_research_start_uses_supervised_runner(monkeypatch, tmp_path, capsys):
    from gym.services import research_runner

    async def watch(root, *, store, poll_seconds):
        assert root == tmp_path / "demo"
        assert store == "demo" and poll_seconds == 2
        return {"state": "STOPPED", "funded_authority": False}

    monkeypatch.setattr(research_runner, "watch", watch)
    assert main(["--data", str(tmp_path), "research", "start", "--demo", "--poll-seconds", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "STOPPED"


def test_research_resume_routes_to_existing_job(monkeypatch, tmp_path, capsys):
    from gym.services.research_ledger import ResearchLedger

    def resume(self, job_id):
        assert job_id == "existing-job"
        return {"job_id": job_id, "state": "ACTIVE"}

    monkeypatch.setattr(ResearchLedger, "resume", resume)
    assert main(["--data", str(tmp_path), "research", "resume", "existing-job"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "ACTIVE"


def test_session_cli_selects_registered_strategy(monkeypatch, tmp_path):
    from gym.services import live_paper

    root = tmp_path / "demo"
    root.mkdir()
    from gym.adapters.store import MarketDB
    db = MarketDB(root / "market.db")
    db.c.close()

    async def watch(db, runs, symbol, *args, **options):
        assert symbol == "BTCUSDT" and runs == root / "runs"
        assert options == {"strategy_id": "sma-reversion", "params": {"lookback": 5, "entry_bps": 50}}

    monkeypatch.setattr(live_paper, "watch", watch)
    assert main(["--data", str(tmp_path), "session", "BTCUSDT", "--demo", "--seconds", "60",
                 "--strategy", "sma-reversion", "--params", '{"lookback":5,"entry_bps":50}']) == 0
