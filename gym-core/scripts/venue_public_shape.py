"""Print which uncovered venue endpoints answer without a key, and the shape of each answer. Standard library only.

Run: `python scripts/venue_public_shape.py`. No key is sent; a 401 or 403 means the endpoint needs one.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

ORIGIN = "https://api.wallex.ir"
PATHS = ("/v1/otc/markets", "/v1/account/otc/price?symbol=USDTTMN&side=BUY", "/v1/prop/packages",
         "/v1/networks", "/v1/currencies")


def shape(value, depth: int = 3):
    """Keys and value types only, one example per list or symbol map, so no market data is printed in bulk."""
    if depth == 0 or not isinstance(value, (dict, list)):
        return type(value).__name__
    if isinstance(value, list):
        return [shape(value[0], depth - 1)] if value else []
    if len(value) > 40:  # a map keyed by symbol: show one entry
        key = next(iter(value))
        return {f"<{len(value)} keys, e.g. {key}>": shape(value[key], depth - 1)}
    return {key: shape(item, depth - 1) for key, item in value.items()}


if __name__ == "__main__":
    for path in PATHS:
        request = urllib.request.Request(ORIGIN + path, headers={"User-Agent": "TradingGYM-probe"})
        try:
            with urllib.request.urlopen(request, timeout=20) as reply:
                print(path, reply.status, json.dumps(shape(json.loads(reply.read(4 * 1024 * 1024))), ensure_ascii=False))
        except urllib.error.HTTPError as error:
            print(path, error.code, error.read(300).decode("utf-8", "replace"))
        except (OSError, ValueError) as error:
            print(path, "FAILED", repr(error))
