"""Heatmap ranking prefers stable neighborhoods to isolated profitable spikes."""

from gym.services.parameter_plateau import parameter_plateau


def test_isolated_parameter_spike_loses_to_flat_local_plateau():
    params = [{"fast": i} for i in range(7)]
    result = parameter_plateau(params, ["12", "0", "0", "10", "10", "10", "10"])
    assert result["status"] == "AVAILABLE"
    assert result["ranked_trials"][0] in (4, 5, 6)
    assert result["cells"][0]["score"] == "6"


def test_grid_uses_axis_neighbours_not_diagonal_cells():
    params = [{"fast": x, "slow": y} for x in (1, 2) for y in (1, 2)]
    result = parameter_plateau(params, ["1", "1", "1", "90"])
    assert result["cells"][0]["neighbors_including_self"] == 3
    assert result["cells"][0]["score"] == "1"
    assert result["cells"][3]["score"] != "90"


def test_invalid_or_missing_heatmap_scores_abstain():
    assert parameter_plateau([{"fast": 1}, {"fast": 1}], ["1", "2"])["status"] == "NOT_GRID"
    assert parameter_plateau([{"fast": 1}, {"fast": 2}], [None, None])["status"] == "INSUFFICIENT_DATA"
