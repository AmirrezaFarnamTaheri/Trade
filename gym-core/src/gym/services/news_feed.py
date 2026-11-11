"""Explicit fetch of one fixed public official RSS feed, with actual receipt clocks."""
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from hashlib import sha256

from ..domain.market_models import fields
from ..domain.model import iso, now_utc
from .research_protocol import ResearchProtocol

FEED_URL = "https://www.federalreserve.gov/feeds/press_all.xml"
MAX_BODY = 512 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("public feed redirect refused")


def parse_feed(raw, *, received_at, max_items):
    if type(max_items) is not int or not 1 <= max_items <= 20 or not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BODY:
        raise ValueError("public feed requires 1..20 items and a bounded XML body")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper() or b"\x00" in raw:
        raise ValueError("public feed declarations or non-UTF XML refused")
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("public feed returned invalid RSS") from None
    if tree.tag != "rss" or len(tree.findall("channel")) != 1 or sum(1 for _ in tree.iter()) > 10000:
        raise ValueError("unsupported public RSS structure")
    rows, seen, future = [], set(), 0
    for item in tree.findall("channel/item"):
        if len(rows) == max_items:
            break
        if any(len(item.findall(name)) != 1 for name in ("title", "link", "pubDate")):
            raise ValueError("ambiguous public RSS item")
        title, link, published = (item.findtext(name, default="").strip() for name in ("title", "link", "pubDate"))
        if not title or len(title) > 1000 or not re.fullmatch(r"https://www\.federalreserve\.gov/newsevents/pressreleases/[A-Za-z0-9_./-]{1,256}", link):
            raise ValueError("invalid public RSS headline or official article link")
        try:
            at = parsedate_to_datetime(published)
        except (ValueError, TypeError, OverflowError):
            raise ValueError("invalid public RSS publication clock") from None
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("public RSS publication requires a timezone")
        if at > received_at:
            future += 1
            continue
        if link in seen:
            raise ValueError("duplicate public RSS article")
        seen.add(link)
        rows.append({"source_id": "federalreserve.gov", "series": "press-releases", "subject": "FED-" + sha256(link.encode()).hexdigest()[:32],
                     "kind": "NEWS", "unit": "text", "value": title + "\n" + link, "published_at": iso(at), "revision_at": None})
    return rows, future


def fetch_news(root, request, *, store):
    fields(request, "source max_items")
    if request["source"] != "FED_PRESS" or store != "live" or type(request["max_items"]) is not int or not 1 <= request["max_items"] <= 20:
        raise ValueError("only explicit FED_PRESS live-store fetches with 1..20 items are supported")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(urllib.request.Request(FEED_URL, headers={"User-Agent": "TradingGYM-public-research/1", "Accept": "application/rss+xml,text/xml", "Accept-Encoding": "identity"}), timeout=8) as response:
            if response.status != 200 or response.geturl() != FEED_URL or response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("unsupported public feed response")
            raw = response.read(MAX_BODY + 1)
    except (OSError, urllib.error.URLError):
        raise ValueError("public feed unavailable; nothing imported") from None
    received_at = now_utc()
    rows, future = parse_feed(raw, received_at=received_at, max_items=request["max_items"])
    report = {"source": "FED_PRESS", "source_url": FEED_URL, "body_sha256": sha256(raw).hexdigest(),
              "received_at": iso(received_at), "future_items_excluded": future, "funded_authority": False,
              "limitation": "Official HTTPS retrieval and local receipt only; no independent signature, verified interpretation or historical backfill."}
    if rows:
        root.mkdir(parents=True, exist_ok=True)
        with ResearchProtocol(root, store=store) as protocol:
            report.update(protocol.ingest_observations({"observations": rows}, origin="PUBLIC_FEED_HTTP"))
    else:
        report["imported_ids"] = []
    report["observations"] = rows
    return report
