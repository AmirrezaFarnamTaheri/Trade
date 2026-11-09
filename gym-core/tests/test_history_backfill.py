"""Long venue-candle backfill pages backwards and stops before the market listed."""
import json
from datetime import UTC, datetime
from itertools import pairwise

from gym.cli import main
from gym.services.collector import Collector


def test_history_pages_backwards_and_stops_after_three_empty_pages(tmp_path, monkeypatch, capsys):
    calls = []

    async def fake_fetch(self, session, symbol, resolution, start, end):
        calls.append((symbol, resolution, start, end))
        return 1000 if end > datetime(2026, 1, 1, tzinfo=UTC) else 0  # nothing before the listing

    monkeypatch.setattr(Collector, "fetch_candles", fake_fetch)
    assert main(["--data", str(tmp_path), "history", "btcusdt", "--resolution", "1d",
                 "--from", "2010-01-01T00:00:00Z", "--to", "2026-11-01T00:00:00Z"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["candles"] == {"BTCUSDT": 1000}
    assert [c[1] for c in calls] == ["1d"] * 4  # one page with data, then three empty pages
    assert all(a[2] == b[3] for a, b in pairwise(calls))  # contiguous windows, newest first
    assert calls[0][3] == datetime(2026, 11, 1, tzinfo=UTC)


def test_history_page_never_crosses_the_start(tmp_path, monkeypatch, capsys):
    calls = []

    async def fake_fetch(self, session, symbol, resolution, start, end):
        calls.append((start, end))
        return 5

    monkeypatch.setattr(Collector, "fetch_candles", fake_fetch)
    assert main(["--data", str(tmp_path), "history", "USDTTMN", "--from", "2026-10-01T00:00:00Z",
                 "--to", "2026-11-01T00:00:00Z"]) == 0
    assert calls[-1][0] == datetime(2026, 10, 1, tzinfo=UTC) and len(calls) == 1  # 31 days of 1h fits one page
