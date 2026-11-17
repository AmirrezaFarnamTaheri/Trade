"""The scheduler takes due jobs one at a time and does not wait between them."""
import asyncio

from gym.commands import research


def test_due_jobs_run_back_to_back_then_the_scheduler_waits(monkeypatch):
    replies = [{"completed": [1], "failed": []}, {"completed": [], "failed": [2]}, {"completed": [], "failed": []}]
    stop = asyncio.Event()
    calls = []

    async def fake_calculate(root, action, **kwargs):
        calls.append(action)
        reply = replies[len(calls) - 1]
        if len(calls) == len(replies):
            stop.set()
        return reply

    monkeypatch.setattr(research, "calculate", fake_calculate)
    result = asyncio.run(asyncio.wait_for(research._watch("unused", "live", 60, stop), timeout=5))
    assert calls == ["tick", "tick", "tick"]
    assert (result["ticks"], result["completed"], result["failed"]) == (3, 1, 1)


def test_a_stopped_worker_is_counted_and_the_scheduler_keeps_going(monkeypatch):
    from gym.services.research_process import ResearchProcessFailure
    stop, calls = asyncio.Event(), []

    async def fake_calculate(root, action, **kwargs):
        calls.append(action)
        if len(calls) == 1:
            raise ResearchProcessFailure("paper calculation deadline exceeded", terminated=True, status=504)
        stop.set()
        return {"completed": [], "failed": []}

    monkeypatch.setattr(research, "calculate", fake_calculate)
    result = asyncio.run(asyncio.wait_for(research._watch("unused", "live", 1, stop), timeout=5))
    assert (result["state"], result["ticks"], result["failed"]) == ("STOPPED", 2, 1)
    assert result["reason"] == "Stop requested"


def test_a_broken_worker_still_stops_the_scheduler(monkeypatch):
    from gym.services.research_process import ResearchProcessFailure

    async def fake_calculate(root, action, **kwargs):
        raise ResearchProcessFailure("paper store unavailable", terminated=True)

    monkeypatch.setattr(research, "calculate", fake_calculate)
    result = asyncio.run(asyncio.wait_for(research._watch("unused", "live", 1, asyncio.Event()), timeout=5))
    assert (result["state"], result["error"], result["ticks"]) == ("STOPPED", "paper store unavailable", 0)
