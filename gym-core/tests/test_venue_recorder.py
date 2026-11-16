"""The hosted recorder keeps exact venue text, skips failed reads, and imports without duplicates."""
import importlib.util
import json
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "venue_recorder", Path(__file__).resolve().parents[1] / "scripts/venue_recorder.py")
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)

DEPTH = ('{"result":{"ask":[{"price":271121,"quantity":34.86014938,"sum":"1"},{"price":271200,"quantity":200}],'
         '"bid":[{"price":271000,"quantity":12.50,"sum":"1"},{"price":271050.5,"quantity":3}]},"success":true}')


def test_top_takes_the_best_level_by_price_and_keeps_the_exact_text():
    assert recorder.top(DEPTH) == {"bid": "271050.5", "bid_qty": "3", "ask": "271121", "ask_qty": "34.86014938"}
    assert recorder.top('{"result":{"ask":[],"bid":[{"price":1,"quantity":1}]}}') is None


def test_record_writes_one_line_per_market_per_minute_and_skips_a_failed_read(tmp_path):
    now = [0.0]

    def fetch(symbol):
        if symbol == "BAD":
            raise OSError("no route")
        return DEPTH

    out = tmp_path / "quotes.jsonl"
    rows, errors = recorder.record(["USDTTMN", "BAD"], 3, out, fetch=fetch, clock=lambda: now[0],
                                   sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert (rows, errors) == (3, 3) and len(lines) == 3
    assert {line["symbol"] for line in lines} == {"USDTTMN"} and lines[0]["ask"] == "271121"
    assert lines[0]["ts"].endswith("Z") and len(lines[0]["ts"]) == 27  # the store's timestamp form


def test_import_is_idempotent_and_the_version_1_runner_reads_the_result(tmp_path):
    lines = [{"ts": f"2026-11-04T08:{minute:02}:30.000000Z", "symbol": "USDTTMN", "bid": "99999", "bid_qty": "5",
              "ask": "100001", "ask_qty": "7"} for minute in range(10, 40)]
    source = tmp_path / "quotes.jsonl"
    source.write_text("\n".join(json.dumps(line) for line in lines) + "\n\n", encoding="utf-8")
    db = tmp_path / "recorder.sqlite3"
    assert recorder.import_files([source], db) == 30
    assert recorder.import_files([source, source], db) == 0
    connection = sqlite3.connect(db)
    assert connection.execute("SELECT instrument_id, bid, ask_qty, flags FROM book_top LIMIT 1").fetchone() == (
        "wallex:USDTTMN", "99999", "7", "")
    connection.close()
    v1_spec = importlib.util.spec_from_file_location("usdttmn_v1", Path(__file__).resolve().parents[1] / "scripts/usdttmn_v1.py")
    v1 = importlib.util.module_from_spec(v1_spec)
    v1_spec.loader.exec_module(v1)
    days = v1.sessions(db, False)
    assert list(days) == ["2026-11-04"] and len(days["2026-11-04"]) == 30  # 08:10 UTC is 11:40 Tehran, in session


def test_github_sync_downloads_once_and_rejects_unexpected_zip_members(tmp_path):
    import io
    import zipfile

    import pytest
    content = json.dumps({"symbol":"BTCUSDT", "ts":"2026-11-14T08:00:00.000000Z",
                          "bid":"99", "ask":"101", "bid_qty":"1", "ask_qty":"1"}).encode()
    def zipped(name):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(name, content)
        return buffer.getvalue()
    calls = []
    archive = [zipped("quotes.jsonl")]
    def api(path):
        calls.append(path)
        return archive[0] if path.endswith("/zip") else json.dumps({"artifacts":[
            {"id":1, "name":"venue-quotes-123", "expired":False, "size_in_bytes":200}]}).encode()
    db = tmp_path / "recorder.sqlite3"
    assert recorder.sync_artifacts("owner/repo", db, api=api) == 1
    assert recorder.sync_artifacts("owner/repo", db, api=api) == 0
    assert sum(p.endswith("/zip") for p in calls) == 1
    archive[0] = zipped("../escape")
    with pytest.raises(ValueError, match="contents"):
        recorder.sync_artifacts("owner/repo", tmp_path / "bad.db", api=api)
