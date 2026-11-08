"""Fixed public RSS parsing, immutable receipt clocks and hostile input refusal."""
import json
from datetime import timedelta

import pytest

from gym.services.news_feed import MAX_BODY, _NoRedirect, fetch_news, parse_feed
from gym.services.research_protocol import ResearchProtocol
from tests.support import START

RSS = b'''<rss><channel><item><title>Public policy announcement</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261029a.htm</link>
<pubDate>Thu, 29 Oct 2026 00:00:00 GMT</pubDate></item></channel></rss>'''


def test_feed_receipt_never_becomes_past_knowledge_and_duplicates_keep_first_receipt(tmp_path):
    receipt = START + timedelta(days=2)
    rows, future = parse_feed(RSS, received_at=receipt, max_items=5)
    assert future == 0 and len(rows) == 1 and rows[0]["kind"] == "NEWS"
    with ResearchProtocol(tmp_path, clock=lambda: receipt) as protocol:
        first = protocol.ingest_observations({"observations": rows}, origin="PUBLIC_FEED_HTTP")
    with ResearchProtocol(tmp_path, clock=lambda: receipt + timedelta(days=1)) as protocol:
        second = protocol.ingest_observations({"observations": rows}, origin="PUBLIC_FEED_HTTP")
        assert first["imported_ids"] == second["imported_ids"]
        encoded, known = protocol.conn.execute("SELECT body,known_at FROM observations").fetchone()
        body = json.loads(encoded)
        assert body["origin"] == "PUBLIC_FEED_HTTP" and not body["source_authenticity_verified"] and not body["rights_verified"]
        assert protocol.conn.execute("SELECT count(*) FROM observations WHERE known_at<?", (receipt.isoformat(),)).fetchone()[0] == 0
        from gym.domain.model import parse_ts
        assert parse_ts(known) == receipt
    assert parse_feed(RSS, received_at=START - timedelta(days=2), max_items=5) == ([], 1)


@pytest.mark.parametrize("raw", [
    b'', b'x' * (MAX_BODY + 1), b'<!DOCTYPE x [<!ENTITY e "bad">]><rss/>', b'<rss>\x00</rss>',
    b'<not-rss/>', RSS.replace(b'www.federalreserve.gov/newsevents/', b'evil.example/newsevents/'),
    RSS.replace(b'GMT', b''), RSS.replace(b'<title>', b'<title>duplicate</title><title>'),
    RSS.replace(b'</channel>', RSS.split(b'<channel>')[1].split(b'</channel>')[0] + b'</channel>'),
])
def test_invalid_xml_identity_clocks_and_duplicates_fail_closed(raw):
    with pytest.raises(ValueError):
        parse_feed(raw, received_at=START + timedelta(days=2), max_items=20)


def test_no_arbitrary_url_source_or_demo_network_and_no_redirects(tmp_path):
    for request, store in (({"source": "https://evil.example", "max_items": 1}, "live"),
                           ({"source": "FED_PRESS", "max_items": True}, "live"),
                           ({"source": "FED_PRESS", "max_items": 21}, "live"),
                           ({"source": "FED_PRESS", "max_items": 1}, "demo")):
        with pytest.raises(ValueError):
            fetch_news(tmp_path, request, store=store)
    assert not (tmp_path / "research_protocol.sqlite3").exists()
    with pytest.raises(ValueError, match="redirect"):
        _NoRedirect().redirect_request(None, None, None, None, None, "https://evil.example")
