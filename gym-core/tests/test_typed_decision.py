"""L-8: the typed-decision client is loopback-only, advisory, and degrades to null."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from gym.services.research_actions import research_action

PAIRS = {"pairs": [{"id": "c1", "claim": "net was negative", "passage": "the run lost 3 USDT"}]}


def serve(reply_for):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, headers, payload = reply_for(body)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def configure(root, port):
    (root / "typed-decision.json").write_text(json.dumps(
        {"url": f"http://127.0.0.1:{port}/v1/systemone", "model_sha256": "a" * 64, "timeout_s": 5}))


def test_not_configured_is_null_and_never_verifies(tmp_path):
    out = research_action(tmp_path, "entailment-check", PAIRS)
    assert out["status"] == "NOT_CONFIGURED" and out["pairs"][0]["advisory_probability"] is None
    assert out["semantic_grounding_verified"] is False and out["accepted_state_changed"] is False


def test_probability_is_advisory_and_bad_replies_degrade(tmp_path):
    seen = []
    server = serve(lambda body: (seen.append(body), (200, {}, b'{"probability": 0.91}'))[1])
    try:
        configure(tmp_path, server.server_port)
        out = research_action(tmp_path, "entailment-check", PAIRS)
        assert out["pairs"][0] == {"id": "c1", "advisory_probability": 0.91, "reason": None}
        assert out["semantic_grounding_verified"] is False
        assert seen == [{"task": "entailment", "premise": "the run lost 3 USDT", "hypothesis": "net was negative"}]
    finally:
        server.shutdown()
    for reply, reason in [((200, {}, b'{"probability": 1.5}'), "no probability"),
                          ((200, {}, b"not json"), "not JSON"),
                          ((302, {"Location": "http://example.com/"}, b""), "server unavailable")]:
        server = serve(lambda body, r=reply: r)
        try:
            configure(tmp_path, server.server_port)
            row = research_action(tmp_path, "entailment-check", PAIRS)["pairs"][0]
            assert row["advisory_probability"] is None and reason in row["reason"], row
        finally:
            server.shutdown()
    configure(tmp_path, 1)  # nothing listens on port 1
    assert research_action(tmp_path, "entailment-check", PAIRS)["pairs"][0]["reason"].startswith("server unavailable")


@pytest.mark.parametrize("url", ["https://127.0.0.1:9/v1", "http://10.0.0.5:9/v1", "http://127.0.0.1/v1",
                                 "http://user@127.0.0.1:9/v1"])
def test_non_loopback_or_unpinned_configuration_is_refused(tmp_path, url):
    (tmp_path / "typed-decision.json").write_text(json.dumps({"url": url, "model_sha256": "a" * 64, "timeout_s": 5}))
    with pytest.raises(ValueError):
        research_action(tmp_path, "entailment-check", PAIRS)


def test_no_order_sizing_or_executor_module_imports_the_client():
    src = Path(__file__).resolve().parents[1] / "src/gym"
    allowed = {"typed_decision.py", "research_actions.py"}
    for path in src.rglob("*.py"):
        if path.name not in allowed:
            assert "typed_decision" not in path.read_text(encoding="utf-8"), path
