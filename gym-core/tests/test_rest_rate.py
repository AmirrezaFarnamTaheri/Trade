"""Global REST pacing recovers without making a successful retry erase a 429."""
import asyncio

from gym.services import collector


def test_rest_rate_recovers_gradually_without_crossing_its_floor(monkeypatch):
    now = 100.0
    monkeypatch.setattr(collector.time, "monotonic", lambda: now)

    async def check():
        rate = collector.RestRate(requests_per_second=4)
        await rate.penalize()
        await rate.penalize()
        await rate.reward()
        assert rate.interval == 1.0
        for expected in (0.5, 0.25, 0.25):
            nonlocal now
            now += 60
            await rate.reward()
            assert rate.interval == expected

    asyncio.run(check())


def test_wait_does_not_block_a_rate_penalty(monkeypatch):
    async def check():
        rate = collector.RestRate(requests_per_second=4)
        now = 100.0
        delays = []

        async def sleep(delay):
            nonlocal now
            delays.append(delay)
            assert not rate.lock.locked()
            if len(delays) == 1:
                await rate.penalize()
            now += delay

        monkeypatch.setattr(collector.time, "monotonic", lambda: now)
        monkeypatch.setattr(collector.asyncio, "sleep", sleep)
        await rate.wait()
        await rate.wait()
        assert delays == [0.25]
        assert rate.interval == 0.5

    asyncio.run(check())
