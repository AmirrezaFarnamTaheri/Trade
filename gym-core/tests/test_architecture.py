"""Imports point inward; the domain never depends on I/O libraries."""
import ast
import json
import subprocess
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "gym"


def test_local_ownership_does_not_load_the_collector_network_stack():
    code = (
        "import json,sys; sys.path=json.loads(sys.argv[1]); "
        "import gym.services.process_owner; "
        "assert 'gym.services.collector' not in sys.modules; "
        "assert 'aiohttp' not in sys.modules"
    )
    subprocess.run(
        [getattr(sys, "_base_executable", sys.executable), "-I", "-c", code, json.dumps(sys.path)],
        check=True, capture_output=True, text=True,
    )


@pytest.mark.parametrize(("layer", "forbidden"), [
    ("domain", {"gym.adapters", "gym.services", "gym.api", "aiohttp", "sqlite3", "zstandard",
                "socket", "asyncio", "os", "pathlib", "subprocess"}),
    ("adapters", {"gym.services", "gym.api"}),
    ("services", {"gym.api"}),
])
def test_imports_follow_dependency_direction(layer, forbidden):
    for path in (SOURCE / layer).rglob("*.py"):
        package = ".".join(path.parent.relative_to(SOURCE.parent).parts)
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = resolve_name("." * node.level + (node.module or ""), package)
                imports = [module + "." + alias.name for alias in node.names]
            else:
                continue
            for imported in imports:
                assert not any(imported == banned or imported.startswith(banned + ".") for banned in forbidden), (
                    f"{path.relative_to(SOURCE)} imports {imported}"
                )
