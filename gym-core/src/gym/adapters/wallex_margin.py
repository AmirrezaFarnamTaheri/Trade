"""Pinned, credential-free Wallex margin reads and calculators; no position writes."""
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..domain.margin import OPTIONAL_FIELDS, REQUEST_FIELDS
from ..domain.market_models import decimal
from .wallex_account_read import ReadUncertain, parse_account_json

ORIGIN = "https://api.wallex.ir"
MARKETS = "/margin-trade/v1/public/markets"
LOAN = "/margin-trade/v1/public/loan"
PREVIEW = "/margin-trade/v1/public/dry-run"
PACKAGES = "/v1/prop/packages"  # trading-credit package list; answers without a key
MAX_BODY = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("margin response redirect refused")


def public_margin(path, body=None):
    if path in (MARKETS, PACKAGES) and body is None:
        data = None
    elif path in (LOAN, PREVIEW) and type(body) is dict:
        optional = OPTIONAL_FIELDS if path == PREVIEW else set()
        if not REQUEST_FIELDS <= body.keys() or body.keys() - REQUEST_FIELDS - optional:
            raise ValueError("public calculator input fields outside allowlist")
        if type(body["market"]) is not str or len(body["market"]) > 24 or not body["market"].isascii() or not body["market"].isalnum() or body["side"] not in ("long", "short"):
            raise ValueError("invalid public margin market or side")
        for key in body.keys() - {"market", "side"}:
            decimal(body[key], key, positive=True)
        data = json.dumps(body, allow_nan=False).encode()
        if len(data) > 4096:
            raise ValueError("margin calculator input exceeds limit")
    else:
        raise ValueError("endpoint outside public margin calculator allowlist")
    request = Request(ORIGIN + path, data=data, headers={"Accept": "application/json", "Content-Type": "application/json",
                                                       "Accept-Encoding": "identity", "User-Agent": "TradingGYM-public-margin/1"})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=12) as response:
            if response.status != 200 or response.geturl() != ORIGIN + path or response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("unexpected public margin response")
            raw = response.read(MAX_BODY + 1)
    except HTTPError as error:
        raise ValueError(f"public margin request returned HTTP {error.code}; no credentials or orders were used") from None
    except (OSError, URLError):
        raise ValueError("public margin service unavailable; no result assumed") from None
    if not 0 < len(raw) <= MAX_BODY:
        raise ValueError("margin response exceeds size limit")
    try:
        result = parse_account_json(raw)
    except ReadUncertain:
        raise ValueError("invalid public margin JSON") from None
    if type(result) is not dict or result.get("success") is not True or "result" not in result:
        raise ValueError("public margin calculation was not successful")
    return result["result"], hashlib.sha256(raw).hexdigest()
