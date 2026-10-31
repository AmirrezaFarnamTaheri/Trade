"""Imports point inward; the domain never depends on I/O libraries."""
import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "gym"


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
