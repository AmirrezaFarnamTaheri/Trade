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


def test_the_webhook_opener_refuses_a_redirect_instead_of_following_it():
    import threading
    import urllib.error
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    followed = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(302)
            self.send_header("Location", "/moved")
            self.end_headers()

        def do_GET(self):  # urllib turns a redirected POST into a GET
            followed.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/hook", data=b"x", method="POST")
        with pytest.raises(urllib.error.HTTPError) as refused:
            alerts._NO_REDIRECT.open(request, timeout=5)
        assert refused.value.code == 302 and followed == []
    finally:
        server.shutdown()
        server.server_close()
