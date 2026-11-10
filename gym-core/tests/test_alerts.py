"""Health alerts: sent once per change, again on recovery, never repeated, retried when a channel fails."""
import pytest

from gym.services import alerts


def report(*statuses):
    checks = [{"check": f"c{i}", "status": s, "detail": f"detail {i}"} for i, s in enumerate(statuses)]
    worst = "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"
    return {"as_of": "2026-11-10T00:00:00+00:00", "status": worst, "checks": checks}


def test_alerts_fire_on_change_and_recovery_only(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "toast", lambda title, body: sent.append((title, body)) or True)
    assert alerts.notify(report("PASS", "SKIP"), tmp_path)["sent"] is False or sent == []
    assert alerts.notify(report("PASS", "WARN"), tmp_path)["sent"] and sent[-1][0] == "TradingGYM WARN"
    assert "WARN c1: detail 1" in sent[-1][1]
    assert alerts.notify(report("PASS", "WARN"), tmp_path) == {"sent": False, "reason": "unchanged"}
    alerts.notify(report("FAIL", "WARN"), tmp_path)
    assert sent[-1][0] == "TradingGYM FAIL"
    alerts.notify(report("PASS", "PASS"), tmp_path)
    assert sent[-1][0] == "TradingGYM recovered" and len(sent) == 3


def test_failed_delivery_is_retried_and_webhooks_must_be_https(tmp_path, monkeypatch):
    monkeypatch.setattr(alerts, "toast", lambda title, body: False)
    assert alerts.notify(report("WARN"), tmp_path)["sent"]
    assert alerts.notify(report("WARN"), tmp_path)["sent"]  # nothing delivered, so it tries again
    with pytest.raises(ValueError, match="https"):
        alerts.webhook("http://example.com/topic", "t", "b")
    with pytest.raises(ValueError, match="https"):
        alerts.webhook("https://user:pw@example.com/topic", "t", "b")
    out = alerts.notify(report("FAIL"), tmp_path, webhook_url="ftp://x", use_toast=False)
    assert out["channels"]["webhook"].startswith("failed")
