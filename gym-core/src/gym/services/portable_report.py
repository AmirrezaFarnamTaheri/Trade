"""A self-contained, script-free view of the existing allowlisted paper summary."""
import base64
from hashlib import sha256
from html import escape
import json

from .reports import paper_summary


_STYLE = """body{font:16px/1.6 system-ui,sans-serif;max-width:64rem;margin:auto;padding:1.5rem;color:#27231e;background:#faf9f6}h1{line-height:1.2}dl{display:grid;grid-template-columns:minmax(8rem,1fr) 2fr;gap:.6rem}dd{margin:0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eeece6;padding:1rem}li{margin:.5rem 0}.notice{border-left:4px solid #965322;padding:1rem;background:#f0e8dc}@media(max-width:480px){body{padding:1rem}dl{display:block}dt{font-weight:bold}dd{margin-bottom:.8rem}}"""


def render_html(out):
    card = paper_summary(out)
    inputs, end = card["inputs"], card["end"]
    unit = card["currency"]
    unavailable = "Unavailable"
    values = [("Run", card["run_id"]), ("Strategy", inputs["strategy"]),
              ("Period · UTC", inputs["from"] + " → " + inputs["to"]),
              ("Source store", inputs["store"]), ("Starting cash", card["starting_cash"] + " " + unit),
              ("Closing equity", end["equity"] + " " + unit if end else unavailable),
              ("Net result", end["net"] + " " + unit if end else unavailable),
              ("Valuation at run cutoff", card["valuation"]["status"]), ("Modeled fills", card["counts"]["fills"]),
              ("Sampled maximum drawdown · %", card["sampled_drawdown"].get("maximum_percent", unavailable)),
              ("Summary checksum", card["summary_digest"])]
    facts = "".join("<dt>" + escape(label) + "</dt><dd>" + escape(str(value)) + "</dd>" for label, value in values)
    limitations = "".join("<li>" + escape(text) + "</li>" for text in card["limitations"])
    style_hash = base64.b64encode(sha256(_STYLE.encode()).digest()).decode("ascii")
    policy = "default-src 'none'; base-uri 'none'; form-action 'none'; style-src 'sha256-" + style_hash + "'"
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"" + escape(policy, quote=True) + "\">"
            "<title>Paper research · " + escape(inputs["symbol"]) + "</title><style>" + _STYLE + "</style></head>"
            "<body><main><p>TradingGYM · Paper research</p><h1>" + escape(inputs["symbol"]) + "</h1>"
            "<p class=\"notice\"><strong>PAPER ONLY · No capital authorized.</strong> "
            "Historical modeled results. This report does not certify profitability or live execution.</p>"
            "<dl>" + facts + "</dl><h2>Limitations</h2><ul>" + limitations + "</ul>"
            "<details><summary>Allowlisted source summary and fingerprints</summary><pre>"
            + escape(json.dumps(card, ensure_ascii=False, indent=2)) + "</pre></details>"
            "</main></body></html>\n")
