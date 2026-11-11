import asyncio

from gym.services.loop_lag import WARN_P99_MS, LoopLag


def test_report_percentiles_and_warning():
    lag = LoopLag(window=200)
    assert lag.report()["status"] == "NO_DATA"
    for value in [1.0] * 196 + [400.0] * 3 + [-3.0]:
        lag.record(value)
    report = lag.report()
    assert (report["samples"], report["p50_ms"], report["max_ms"]) == (200, 1.0, 400.0)
    assert report["p99_ms"] == 400.0 and report["status"] == "WARN" and report["warn_p99_ms"] == WARN_P99_MS
    assert min(lag.samples) == 0.0  # a clock that runs early never reports negative lag


def test_sampler_sees_a_blocking_write_on_the_loop():
    import time

    async def scenario():
        lag = LoopLag(interval=0.01)
        task = asyncio.create_task(lag.run())
        await asyncio.sleep(0.05)
        time.sleep(0.2)  # noqa: ASYNC251 - the deliberate stall under test, like a slow commit on the loop
        await asyncio.sleep(0.05)
        task.cancel()
        return lag.report()

    assert asyncio.run(scenario())["max_ms"] >= 150
