"""Numeric research claims must resolve to immutable native run fields."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_EVEN
import json

import pytest

from gym.adapters.run_store import save_run
from gym.cli import main
from gym.services.paper import paper
from gym.services.research_grounding import check_claims
from tests.support import START, market_db, quote_history


@pytest.fixture
def saved_run(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
        out["private_notes"] = "private-canary"
        save_run(out, tmp_path / "runs")
        return tmp_path / "runs", out
    finally:
        db.c.close()


def claim(out, **changes):
    return {"id": "net", "operation": "VALUE", "sources": [{"run_id": out["run_id"], "metric": "net_quote"}],
            "value": str(Decimal(out["result"]["end"]["net"]).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN)),
            "decimal_places": 8, **changes}


def test_actual_run_value_and_arithmetic_retain_provenance_without_private_content(saved_run):
    root, out = saved_run
    first = claim(out)
    difference = claim(out, id="excess", operation="DIFFERENCE",
                       sources=[first["sources"][0], {"run_id": out["run_id"], "metric": "hold_cash_net_quote"}])
    result = check_claims(root, {"claims": [first, difference]}, store="live")
    assert result["all_matched"] and all(r["status"] == "MATCHED" for r in result["claims"])
    assert result["claims"][0]["sources"][0]["outputs_digest"] == out["outputs_digest"]
    assert result["claims"][0]["unit"] == "USDT"
    assert not result["source_authenticity_verified"] and not result["semantic_grounding_verified"]
    assert not result["funded_authority"] and "private-canary" not in json.dumps(result)


def test_fabricated_profit_is_a_mismatch_not_a_successful_grounding(saved_run):
    root, out = saved_run
    result = check_claims(root, {"claims": [claim(out, value="1000")]}, store="live")
    assert not result["all_matched"]
    assert result["claims"][0]["status"] == "MISMATCH"
    assert result["claims"][0]["computed_value"] == claim(out)["value"]


@pytest.mark.parametrize("change", ["path", "private", "nonfinite", "boolean", "unknown", "extra", "zero_ratio", "duplicate"])
def test_unsupported_or_ambiguous_claims_fail(saved_run, change):
    root, out = saved_run
    row = claim(out)
    if change == "path":
        row["sources"][0]["run_id"] = "../secret"
    elif change == "private":
        row["sources"][0]["metric"] = "private_notes"
    elif change == "nonfinite":
        row["value"] = "NaN"
    elif change == "boolean":
        row["decimal_places"] = True
    elif change == "unknown":
        row["operation"] = "EXECUTE"
    elif change == "extra":
        row["approved"] = True
    elif change == "zero_ratio":
        row.update(operation="RATIO", sources=[row["sources"][0], {"run_id": out["run_id"], "metric": "hold_cash_net_quote"}])
    with pytest.raises(ValueError):
        check_claims(root, {"claims": [row, row] if change == "duplicate" else [row]}, store="live")


def test_modified_saved_results_cannot_ground_a_claim(saved_run):
    root, out = saved_run
    path = root / (out["run_id"] + ".json")
    corrupted = json.loads(path.read_text())
    corrupted["result"]["end"]["net"] = "1000"
    path.write_text(json.dumps(corrupted))
    with pytest.raises(ValueError, match="digest"):
        check_claims(root, {"claims": [claim(out)]}, store="live")


@pytest.mark.parametrize("content", ["{}", "null", "[]", "[" * 1100 + "]" * 1100])
def test_malformed_artifact_is_rejected_without_a_cli_traceback(saved_run, tmp_path, capsys, content):
    _, out = saved_run
    live = tmp_path / "broken" / "live" / "runs"
    live.mkdir(parents=True)
    (live / (out["run_id"] + ".json")).write_text(content)
    source = tmp_path / "claims.json"
    source.write_text(json.dumps({"claims": [claim(out)]}))
    assert main(["--data", str(live.parent.parent), "research", "claim-check", str(source)]) == 2
    assert "error:" in capsys.readouterr().err


def test_demo_mismatch_and_cli_claim_rejection(saved_run, tmp_path, capsys):
    root, out = saved_run
    with pytest.raises(ValueError, match="store"):
        check_claims(root, {"claims": [claim(out)]}, store="demo")
    live = tmp_path / "data" / "live"
    live.mkdir(parents=True)
    save_run(out, live / "runs")
    source = tmp_path / "claims.json"
    source.write_text(json.dumps({"claims": [claim(out, value="1000")]}))
    assert main(["--data", str(live.parent), "research", "claim-check", str(source)]) == 3
    assert not json.loads(capsys.readouterr().out)["all_matched"]
    assert not (live / "research.sqlite3").exists()
