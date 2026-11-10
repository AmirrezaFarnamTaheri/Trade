import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("ratchet", Path(__file__).resolve().parents[1] / "scripts/complexity_ratchet.py")
ratchet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ratchet)


def test_new_or_growing_functions_fail_and_the_four_split_hotspots_stay_out():
    baseline = {"src/a.py::f": 30}
    assert ratchet.compare({"src/a.py::f": 30}, baseline) == []
    assert ratchet.compare({"src/a.py::f": 31}, baseline) == ["src/a.py::f grew from 30 to 31"]
    assert "not in the baseline" in ratchet.compare({"src/b.py::g": 21}, baseline)[0]
    import json
    shipped = json.loads(ratchet.BASELINE.read_text(encoding="utf-8"))
    for name in ("research_action", "make_app", "weights", "market_order"):
        assert not any(key.endswith("::" + name) for key in shipped), name
    assert shipped["src/gym/services/portfolio.py::_portfolio"] <= 65
