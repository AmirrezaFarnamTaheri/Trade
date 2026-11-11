"""Advisory typed-decision client: an entailment read from a local model, never an authority.

A typed-decision model answers "does this passage support this claim?" with a probability and generates no text.
This client talks only to a loopback server named in `<data root>/typed-decision.json`:
    {"url": "http://127.0.0.1:<port>/v1/systemone", "model_sha256": "<hex of the weights file>", "timeout_s": 10}
Request: {"task": "entailment", "premise": <passage>, "hypothesis": <claim>}; reply: {"probability": 0..1}.

The result goes into `advisory_probability` only. `semantic_grounding_verified` stays false whatever the model
says, nothing here changes a note's accepted state, and no order, sizing or executor module imports this file.
Redirects, non-loopback hosts, oversized or malformed replies and a server that is down all yield null with a
reason. Passages may carry injected instructions; the deterministic checks stay the final authority.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

CONFIG = "typed-decision.json"
LOOPBACK = frozenset(("127.0.0.1", "::1", "localhost"))
MAX_REPLY = 64 * 1024
MAX_TEXT = 4000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise urllib.error.URLError("redirect refused")


def _config(root: Path) -> dict | None:
    path = Path(root) / CONFIG
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"url", "model_sha256", "timeout_s"}:
        raise ValueError(f"{CONFIG} needs exactly url, model_sha256, timeout_s")
    parts = urlsplit(config["url"])
    if parts.scheme != "http" or parts.hostname not in LOOPBACK or parts.port is None or parts.username \
            or parts.query or parts.fragment:
        raise ValueError("typed-decision url must be plain http to a loopback host and explicit port")
    if not re.fullmatch(r"[0-9a-f]{64}", str(config["model_sha256"])):
        raise ValueError("model_sha256 must be the 64-hex SHA-256 of the pinned weights file")
    if type(config["timeout_s"]) is not int or not 1 <= config["timeout_s"] <= 60:
        raise ValueError("timeout_s must be 1..60")
    return config


def _ask(config: dict, claim: str, passage: str) -> tuple[float | None, str | None]:
    body = json.dumps({"task": "entailment", "premise": passage, "hypothesis": claim}).encode()
    request = urllib.request.Request(config["url"], data=body, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=config["timeout_s"]) as reply:
            raw = reply.read(MAX_REPLY + 1)
    except (urllib.error.URLError, OSError, ValueError) as error:
        return None, f"server unavailable: {type(error).__name__}"
    if len(raw) > MAX_REPLY:
        return None, "reply too large"
    try:
        value = json.loads(raw)
        probability = value["probability"] if isinstance(value, dict) and set(value) == {"probability"} else None
    except ValueError:
        return None, "reply is not JSON"
    if type(probability) not in (int, float) or not 0 <= probability <= 1:
        return None, "reply has no probability in [0, 1]"
    return float(probability), None


def entailment_check(root: Path, request) -> dict:
    if not isinstance(request, dict) or set(request) != {"pairs"} or type(request["pairs"]) is not list \
            or not 1 <= len(request["pairs"]) <= 32:
        raise ValueError("need {pairs: [{id, claim, passage}, ...]} with 1..32 pairs")
    config = _config(root)
    rows = []
    for pair in request["pairs"]:
        if not isinstance(pair, dict) or set(pair) != {"id", "claim", "passage"} \
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(pair["id"])) \
                or not all(isinstance(pair[k], str) and 1 <= len(pair[k]) <= MAX_TEXT for k in ("claim", "passage")):
            raise ValueError("each pair needs id, claim and passage (1..4000 characters)")
        if config is None:
            rows.append({"id": pair["id"], "advisory_probability": None, "reason": "not configured"})
            continue
        probability, reason = _ask(config, pair["claim"], pair["passage"])
        rows.append({"id": pair["id"], "advisory_probability": probability, "reason": reason})
    return {"mode": "ADVISORY_ONLY", "status": "NOT_CONFIGURED" if config is None else "CHECKED",
            "model_sha256": config["model_sha256"] if config else None, "pairs": rows,
            "semantic_grounding_verified": False, "accepted_state_changed": False, "order_submitted": False,
            "limitation": "A model probability is advice. It is calibrated only in distribution, weak on numbers and "
                          "open to instructions embedded in the passage; deterministic checks remain the authority."}
