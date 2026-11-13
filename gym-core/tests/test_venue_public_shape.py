"""The shape printer shows structure, never bulk data."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("venue_public_shape", Path(__file__).parents[1] / "scripts" / "venue_public_shape.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_shape_keeps_keys_and_types_and_one_example_per_collection():
    reply = {"success": True, "result": {"symbols": {f"S{i}": {"maxNotional": "5", "stats": {"a": 1}} for i in range(50)}},
             "rows": [{"id": 1}, {"id": 2}], "empty": []}
    assert module.shape(reply) == {
        "success": "bool", "result": {"symbols": {"<50 keys, e.g. S0>": "dict"}}, "rows": [{"id": "int"}], "empty": []}
