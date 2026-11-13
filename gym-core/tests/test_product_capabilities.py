"""A market listing, a credit grid and account authorization are separate facts."""
from datetime import timedelta

from gym.domain.model import InstrumentId, iso
from gym.services import margin
from gym.services.research_actions import research_action
from tests.support import START, market_db, quote_history


def test_product_matrix_covers_every_observed_market_without_inventing_margin_credit(tmp_path, monkeypatch):
    market_db(tmp_path, quote_history(n=3) + quote_history(n=3, sym="ADAUSDT")).c.close()
    monkeypatch.setattr(margin, "now_utc", lambda: START)
    catalogue = margin._save(tmp_path, {"kind": "MARKETS", "received_at": iso(START), "source_url": margin.ORIGIN + margin.MARKETS,
        "markets": [{"symbol": "ADAUSDT", "base": "ADA", "quote": "USDT", "min_risk_coef": "1.1", "max_risk_coef": "4.1",
                     "risk_coef_step": "0.2", "liquidity_margin": "0.15", "max_age": 86400}]})
    monkeypatch.setattr("gym.services.capabilities.now_utc", lambda: START + timedelta(seconds=1))
    report = research_action(tmp_path, "market-products", {"margin_catalogue_id": catalogue["run_id"]})
    rows = {row["symbol"]: row for row in report["markets"]}
    assert set(rows) == {"BTCUSDT", "ADAUSDT"}
    assert rows["ADAUSDT"]["margin"]["credit_grid"]["step"] == "0.2"
    assert rows["BTCUSDT"]["margin"]["status"] == "NOT_LISTED"
    assert rows["ADAUSDT"]["spot"]["sell"] == "OWNED_ASSET_ONLY"
    assert all(row["trade_credit"] == "ACCOUNT_ELIGIBILITY_UNVERIFIED" for row in rows.values())
    assert report["funded_authority"] is False
    monkeypatch.setattr("gym.services.capabilities.now_utc", lambda: START + timedelta(minutes=6))
    stale = research_action(tmp_path, "market-products", {"margin_catalogue_id": catalogue["run_id"]})
    assert all(row["margin"]["status"] == "STALE_CATALOGUE" for row in stale["markets"])


def test_product_matrix_reports_the_venue_catalogue_flags_or_unknown(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history(n=3) + quote_history(n=3, sym="ADAUSDT"))
    db.upsert_instrument(InstrumentId.wallex("BTCUSDT", "BTC", "USDT"), {}, {
        "symbol": "BTCUSDT", "is_spot": True, "is_margin": True, "is_otc": True, "is_zero_fee": False,
        "max_leverage": "10", "leverage_step": "0.5", "otc_buy_enabled": True, "otc_sell_enabled": False,
        "otc_min_notional": "90000", "otc_max_notional": "500000000"}, "rest:/hector/web/v1/markets", START)
    db.c.close()
    monkeypatch.setattr("gym.services.capabilities.now_utc", lambda: START + timedelta(seconds=1))
    rows = {row["symbol"]: row for row in research_action(tmp_path, "market-products", {"margin_catalogue_id": None})["markets"]}
    assert rows["BTCUSDT"]["venue"] == {
        "valid_from": iso(START), "spot": True, "margin": True, "otc": True, "zero_fee": False,
        "max_leverage": "10", "leverage_step": "0.5", "otc_buy": True, "otc_sell": False,
        "otc_min_notional": "90000", "otc_max_notional": "500000000"}
    assert rows["ADAUSDT"]["venue"] is None
