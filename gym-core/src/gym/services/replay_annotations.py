"""Immutable operator annotations anchored to a verified run and exact decision."""
import re

from ..adapters.run_store import load_verified_run
from ..domain.market_models import fields
from ..domain.strategy import digest


def annotations(registry, request, *, save=False):
    fields(request, "run_id outputs_digest decision_index request_id text" if save else "run_id outputs_digest after through limit")
    out = load_verified_run(registry.root / "runs", request["run_id"], store=registry.store)
    if request["outputs_digest"] != out["outputs_digest"]:
        raise ValueError("annotation run revision changed")
    parent = f"run:{out['run_id']}:{out['outputs_digest']}"
    if not save:
        return registry.page({"kind": "REPLAY_ANNOTATION", "parent": parent,
                              **{k: request[k] for k in ("after", "through", "limit")}})
    index, text, nonce = request["decision_index"], request["text"], request["request_id"]
    rows = out["result"]["decisions"]
    if type(index) is not int or not 0 <= index < len(rows):
        raise ValueError("annotation requires a saved decision index")
    if type(text) is not str or not 1 <= len(text.strip()) <= 2000:
        raise ValueError("annotation requires 1..2000 characters")
    if type(nonce) is not str or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise ValueError("annotation requires a 32-character request identity")
    source = {k: request[k] for k in ("run_id", "outputs_digest", "decision_index", "text")}
    content = digest(source)
    registry.conn.execute("BEGIN IMMEDIATE")
    try:
        prior = registry.conn.execute("""SELECT id,body FROM events WHERE kind='REPLAY_ANNOTATION'
            AND json_extract(body,'$.store')=? AND json_extract(body,'$.request_id')=?""", (registry.store, nonce)).fetchone()
        if prior:
            record = registry.read_record(*prior)
            if record["request_digest"] != content:
                raise ValueError("annotation request identity was already used for different content")
        else:
            row = rows[index]
            record = registry.append("REPLAY_ANNOTATION", parent, {**source, "request_id": nonce, "request_digest": content,
                "symbol": out["result"]["symbol"], "resolution": out["inputs"]["resolution"],
                "decision_at": row["t"], "price": row["close"], "economic_evidence": False, "funded_authority": False})
        registry.conn.commit()
    except BaseException:
        registry.conn.rollback()
        raise
    return {"schema": "replay-annotation/1", "record": record, "funded_authority": False}
