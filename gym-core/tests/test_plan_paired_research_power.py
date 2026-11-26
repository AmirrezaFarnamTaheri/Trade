import pytest

from scripts.plan_paired_research_power import plan


def test_power_plan_sizes_for_margin_above_threshold_and_family():
    inputs = {"threshold_bps": 5, "alternative_bps": 10, "block_sd_bps": 20, "block_days": 7, "comparisons": 3}
    report = plan(**inputs)
    assert report["independent_blocks_required"] == 142
    assert report["calendar_days_if_complete"] == 994
    assert plan(**(inputs | {"comparisons": 1}))["independent_blocks_required"] < 142
    with pytest.raises(ValueError, match="assumptions"):
        plan(**(inputs | {"alternative_bps": 5}))
