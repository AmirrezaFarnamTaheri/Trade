from decimal import Decimal

from scripts.score_paired_research_blocks import score


def test_stale_valuations_leave_marked_difference_visible_without_scoring():
    row = {"from": "2026-11-18T22:00:00Z", "to": "2026-11-21T22:00:00Z", "candidate_bps": "-79.74",
           "benchmark_bps": "-79.80", "candidate_status": "STALE_VALUATION", "benchmark_status": "CURRENT"}
    result = score([row], threshold_bps=Decimal(5), block_length=2, seed=0)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["counts"] == {"UNSCORED_VALUATION": 1}
    assert result["blocks"][0]["marked_difference_bps"] == "0.06"
    row["candidate_status"] = "CURRENT"
    result = score([row], threshold_bps=Decimal(5), block_length=2, seed=0)
    assert result["inference"]["status"] == "INSUFFICIENT_DATA"
    next_row = {**row, "from": "2026-11-21T22:00:00Z", "to": "2026-11-22T22:00:00Z"}
    result = score([row, next_row], threshold_bps=Decimal(5), block_length=2, seed=0)
    assert result["inference"]["status"] == "INCOMPLETE_CALENDAR_OR_VALUATION"
