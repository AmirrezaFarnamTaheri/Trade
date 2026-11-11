"""A transport connection is not a completed Centrifugo handshake."""
import asyncio
import json
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from gym.adapters.store import MarketDB, SegmentWriter, read_segment
from gym.services import collector
from gym.services.collector import Collector


class Socket:
    def __init__(self, steps, close_code=1000):
        self.steps, self.close_code, self.sent = iter(steps), close_code, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def send_str(self, raw):
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            step = next(self.steps)
        except StopIteration:
            raise StopAsyncIteration from None
        if callable(step):
            step()
            return await self.__anext__()
        await asyncio.sleep(0)
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=step)


@pytest.fixture
def col(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    segment = SegmentWriter(tmp_path / "raw", db)
    instance = Collector(db, segment, ["BTCUSDT"])
    yield instance
    segment.close()
    db.c.close()


def test_connect_ack_gates_subscriptions_status_and_seed(col, monkeypatch):
    seeded = []

    async def seed(*args):
        seeded.append(True)

    def before_ack():
        assert socket.sent == [{"id": 1, "connect": {}}]
        assert not col.status["connected"] and not seeded

    def after_ack():
        assert len(socket.sent) == 5
        assert col.status["connected"] and col.status["shards"] == 1
        assert col.status["shard_stats"][1]["connected_at"] is not None

    publication = json.dumps({"push": {"channel": "orderbook:BTCUSDT@buyDepth",
                                      "pub": {"data": {"message": [{"price": "100", "quantity": "1"}]}}}})
    frame = '{"id":1,"connect":{"client":"test"}}\n' + publication
    socket = Socket([before_ack, "{}", frame, after_ack, '{"id":1,"connect":{"client":"duplicate"}}'])
    monkeypatch.setattr(col, "seed", seed)
    result = asyncio.run(col._ws_once(SimpleNamespace(ws_connect=lambda *a, **kw: socket), ["BTCUSDT"], 1))
    assert result == 1000
    assert socket.sent == [{"id": 1, "connect": {}}, {},
                           {"id": 2, "subscribe": {"channel": "orderbook:BTCUSDT@buyDepth"}},
                           {"id": 3, "subscribe": {"channel": "orderbook:BTCUSDT@sellDepth"}},
                           {"id": 4, "subscribe": {"channel": "public:BTCUSDT@trade"}}]
    assert seeded == [True]
    assert col.books["BTCUSDT"]["bid"].levels[0][0] == 100
    assert not col.status["connected"] and col.status["shards"] == 0
    col.seg.close()
    assert frame in [row["raw"] for row in read_segment(col.seg.path)]


def test_terminal_handshake_close_never_seeds_or_retries(col, monkeypatch):
    socket = Socket(['{"id":1,"error":{"code":101,"message":"unauthorized"}}'], 3502)

    async def no_seed(*args):
        pytest.fail("handshake failure must not start REST seeding")

    async def no_retry(*args):
        pytest.fail("terminal protocol denial must not retry")

    monkeypatch.setattr(col, "seed", no_seed)
    monkeypatch.setattr(collector.asyncio, "sleep", no_retry)
    # The fake socket's cooperative sleep is unnecessary in this terminal case.
    async def receive(self):
        try:
            return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=next(self.steps))
        except StopIteration:
            raise StopAsyncIteration from None
    monkeypatch.setattr(Socket, "__anext__", receive)
    asyncio.run(col._ws_loop(SimpleNamespace(ws_connect=lambda *a, **kw: socket), ["BTCUSDT"], 1))
    assert socket.sent == [{"id": 1, "connect": {}}]
    assert "3502" in col.status["fatal"] and col.status["reconnects"] == 0
    assert not col.status["connected"]
    assert col.db.c.execute("select count(*) from quality_events where flag='SOURCE_ERROR'").fetchone()[0] == 2


def test_transient_closes_keep_bounded_backoff(col, monkeypatch):
    delays = []

    async def closed(*args):
        return 3001

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 8:
            raise asyncio.CancelledError

    monkeypatch.setattr(col, "_ws_once", closed)
    monkeypatch.setattr(collector.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(col._ws_loop(object(), ["BTCUSDT"], 1))
    assert delays == [2, 4, 8, 16, 32, 60, 60, 60]
    assert col.status["reconnects"] == 8 and col.status["fatal"] is None


def test_handshake_order_against_local_websocket_server(col, monkeypatch):
    received, seeded = [], []

    async def seed(*args):
        seeded.append(True)

    async def endpoint(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        received.append(await socket.receive_json())
        await socket.send_str("{}")
        received.append(await socket.receive_json())
        await socket.send_json({"id": 1, "connect": {"client": "local-test"}})
        for _ in range(3):
            received.append(await socket.receive_json())
        await socket.close(code=3502)
        return socket

    async def scenario():
        app = web.Application()
        app.router.add_get("/connection/websocket", endpoint)
        async with TestServer(app, host="127.0.0.1") as server, aiohttp.ClientSession() as session:
            monkeypatch.setattr(collector.wallex, "WS", str(server.make_url("/connection/websocket")))
            await asyncio.wait_for(col._ws_loop(session, ["BTCUSDT"], 1), 2)

    monkeypatch.setattr(col, "seed", seed)
    asyncio.run(scenario())
    assert received[:2] == [{"id": 1, "connect": {}}, {}]
    assert [command["id"] for command in received[2:]] == [2, 3, 4]
    assert seeded == [True]
    assert col.status["reconnects"] == 0 and "3502" in col.status["fatal"]
    assert not col.status["connected"]
