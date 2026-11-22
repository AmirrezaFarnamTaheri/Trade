"""One portfolio strategy consumes independent venue records and denominations."""

from dataclasses import replace
from decimal import Decimal

from gym.domain.model import InstrumentId
from gym.services.research_actions import research_action
from gym.services.research_process import work_estimate
from tests.support import START, market_db, quote_history
from tests.test_portfolio_workflow import request


def test_fixed_universe_replay_uses_second_venue_terms_and_preserves_scaled_returns(tmp_path):
    common = request()
    originals = ("BTCUSDT", "ETHUSDT")
    alternates = ("ALPHA", "BETA")
    scale = Decimal(100)
    db = market_db(tmp_path, [])
    try:
        for symbol, alternative in zip(originals, alternates):
            instrument = InstrumentId.wallex(symbol)
            db.upsert_instrument(instrument, {}, {"stepSize": 6, "minNotional": "1"}, "reference", START)
            db.upsert_instrument(InstrumentId("fixture", alternative, instrument.base + "X", "EUR"),
                                 {}, {"stepSize": 6, "minNotional": "100"}, "fixture", START)
            for top in quote_history(n=180, sym=symbol):
                db.add_book_top(top, None)
                db.add_book_top(replace(top, symbol=alternative, bid=top.bid * scale, ask=top.ask * scale),
                                None, venue="fixture")
        # A different venue's book for the same symbol must not win the lookup.
        db.add_book_top(replace(quote_history(n=1)[0], symbol="ALPHA"), None)
    finally:
        db.c.close()

    def replay(value):
        result = research_action(tmp_path, "portfolio-replay", value)
        return research_action(tmp_path, "portfolio-read", {"run_id": result["run_id"]})

    a = replay({**common, "symbols": list(originals)})
    alternate_request = {**common, "symbols": list(alternates), "venue": "fixture",
                         "cash": str(Decimal(common["cash"]) * scale)}
    assert work_estimate(tmp_path, alternate_request) == 360
    b = replay(alternate_request)
    assert b["inputs"]["venue"] == "fixture"
    assert b["result"]["quote"] == "EUR"
    assert b["result"]["valuation"]["basis"] == "USDT conversion unavailable"
    assert b["result"]["end"]["net_usdt_eq"] is None
    assert b["performance"]["total_return_pct"] == a["performance"]["total_return_pct"]
    assert Decimal(b["result"]["end"]["equity"]) == Decimal(a["result"]["end"]["equity"]) * scale
    for reference, alternative in zip(originals, alternates):
        aa, bb = a["result"]["markets"][reference], b["result"]["markets"][alternative]
        assert aa["observations"] == bb["observations"] == 180
        assert aa["fills"] == bb["fills"] and aa["fills"] > 0
        assert Decimal(bb["realized_pnl"]) == Decimal(aa["realized_pnl"]) * scale
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": b["run_id"], "quote_count": 100})
    resumed = research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["record"]["id"]})
    assert resumed["result_digest"] == b["outputs_digest"]
