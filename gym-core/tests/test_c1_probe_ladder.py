"""C1 probe ladder: no trade submission, hard budget not raised by venue minimum."""
import sqlite3
import pytest

from gym.services.probe_budget import ProbeBudgetBook, ProbeUnsafe, assess_probe_read


def test_unsupported_private_read_is_uncertain_not_absent_or_certified():
    status = assess_probe_read(
        resource="ORDER_STATUS", http_status=404,
        response_bytes=b'{"error":"not found"}', max_bytes=1024,
    )
    assert status["state"] == "UNKNOWN"
    assert status["absent_proven"] is False
    assert status["method_certified"] is False
    assert status["funded_authority"] is False
    assert "body" not in status and "response_bytes" not in status


def test_good_bounded_private_read_is_still_non_authoritative():
    read = assess_probe_read(
        resource="BALANCES", http_status=200,
        response_bytes=b'{"success":true,"result":{"balances":{"USDT":{"value":"4","locked":"1"}}}}',
        max_bytes=1024,
    )
    assert read["state"] == "OBSERVED"
    assert read["body_sha256"] and len(read["body_sha256"]) == 64
    assert read["method_certified"] is False
    assert read["funded_authority"] is False
    assert read["resource"] == "BALANCES"


@pytest.mark.parametrize("status,raw", [
    (200, b'not-json'),
    (200, b'[]'),
    (200, b'{"success":false,"result":{}}'),
    (401, b'{"success":true,"result":{}}'),
    (429, b'{"success":true,"result":{}}'),
    (500, b'{"success":true,"result":{}}'),
])
def test_unknown_read_does_not_prove_orders_absent_or_trading_capable(status, raw):
    x = assess_probe_read(resource="ORDER_STATUS", http_status=status,
                          response_bytes=raw, max_bytes=4096)
    assert x["state"] == "UNKNOWN"
    assert x["absent_proven"] is False
    assert x["method_certified"] is False


def test_probe_budget_survives_restart_and_never_spends_more_than_loss_ceiling(tmp_path):
    path = tmp_path / "budget.sqlite"
    with ProbeBudgetBook(path, total_loss_limit="2.00", quote_asset="USDT") as book:
        quote = book.stage(
            probe_id="p-1", kind="CLIENT_ID_ECHO",
            symbol="BTCUSDT", worst_case_total_loss="1.25",
            venue_minimum_quote="1.00",
        )
        assert quote["state"] == "OFFLINE_REVIEW_ONLY"
        assert quote["order_submitted"] is False
        assert quote["funded_authority"] is False
        assert quote["client_id"] is None
        assert book.remaining() == "0.75"
        with pytest.raises(ProbeUnsafe, match="budget"):
            book.stage(probe_id="p-2", kind="DUPLICATE_ID",
                       symbol="BTCUSDT", worst_case_total_loss="0.76",
                       venue_minimum_quote="0.50")
        with pytest.raises(ProbeUnsafe, match="duplicate"):
            book.stage(probe_id="p-1", kind="CLIENT_ID_ECHO",
                       symbol="BTCUSDT", worst_case_total_loss="0.25",
                       venue_minimum_quote="0.10")
    with ProbeBudgetBook(path, total_loss_limit="2.00", quote_asset="USDT") as reopened:
        assert reopened.remaining() == "0.75"
        assert len(reopened.proposals()) == 1
        with pytest.raises(ProbeUnsafe, match="immutable"):
            ProbeBudgetBook(path, total_loss_limit="3.00", quote_asset="USDT")


def test_venue_minimum_cannot_raise_operator_budget(tmp_path):
    with ProbeBudgetBook(tmp_path/"probe.db", total_loss_limit="0.50", quote_asset="USDT") as book:
        with pytest.raises(ProbeUnsafe, match="minimum"):
            book.stage(probe_id="first", kind="STOP_LIMIT",
                       symbol="BTCUSDT", worst_case_total_loss="0.50",
                       venue_minimum_quote="1")
        assert book.remaining() == "0.50"
        assert book.proposals() == []


@pytest.mark.parametrize("amount", ["NaN", "-1", "Infinity", "1e3", "0", "0.0000000000000000001", 1.5, True])
def test_invalid_exact_probe_amount_never_creates_budget(tmp_path, amount):
    with pytest.raises((ProbeUnsafe, TypeError, ValueError)):
        ProbeBudgetBook(tmp_path/"probe.db", total_loss_limit=amount, quote_asset="USDT")


def test_probe_budget_requires_valid_known_method_and_does_not_accept_keys(tmp_path):
    with ProbeBudgetBook(tmp_path/"probe.db", total_loss_limit="5", quote_asset="USDT") as book:
        with pytest.raises(ProbeUnsafe):
            book.stage(probe_id="p/escape", kind="CLIENT_ID_ECHO", symbol="BTCUSDT",
                       worst_case_total_loss="1", venue_minimum_quote="1")
        with pytest.raises(ProbeUnsafe):
            book.stage(probe_id="p-2", kind="UNLIMITED_TRADE", symbol="BTCUSDT",
                       worst_case_total_loss="1", venue_minimum_quote="1")
        assert not hasattr(book, "post")
        assert not hasattr(book, "submit")
        assert book.proposals() == []

def test_probe_budget_never_mixes_quote_assets_or_currency_units(tmp_path):
    with ProbeBudgetBook(tmp_path/"budget.db", total_loss_limit="2", quote_asset="USDT") as book:
        with pytest.raises(ProbeUnsafe, match="quote asset"):
            book.stage(probe_id="wrong-unit", kind="CLIENT_ID_ECHO",
                       symbol="BTCTMN", worst_case_total_loss="1",
                       venue_minimum_quote="0.5")
        assert book.remaining() == "2"
