"""Page structure and runtime contracts for the bundled browser application."""
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from gym.api.server import UI


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.parents = []

    def handle_starttag(self, tag, attrs):
        self.elements.append({"tag": tag, "attrs": dict(attrs),
                              "parent": self.parents[-1] if self.parents else None})
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}:
            self.parents.append(len(self.elements) - 1)

    def handle_endtag(self, tag):
        while self.parents:
            if self.elements[self.parents.pop()]["tag"] == tag:
                break


def page():
    result = Page()
    result.feed(UI.read_text("utf-8"))
    return result.elements


def node():
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node not installed; UI runtime check unavailable")
    return executable


def test_ui_navigation_and_form_labels():
    elements = page()
    ids = [e["attrs"]["id"] for e in elements if "id" in e["attrs"]]
    assert len(ids) == len(set(ids)), "Duplicate IDs make label and view targets ambiguous"
    routes = [e["attrs"]["data-view"] for e in elements if "data-view" in e["attrs"]]
    assert set(routes) == {"overview", "markets", "research", "account", "operate", "rules", "health", "safety", "backups", "models"}
    assert len(routes) == len(set(routes))
    for route in routes:
        section = next(e for e in elements if e["attrs"].get("id") == "v-" + route)
        assert section["attrs"].get("aria-labelledby") in ids
    labels = {e["attrs"].get("for") for e in elements if e["tag"] == "label"}
    for element in elements:
        attrs = element["attrs"]
        if element["tag"] in {"input", "select", "textarea"} and attrs.get("type") != "hidden":
            assert (attrs.get("id") in labels or attrs.get("aria-label")
                    or attrs.get("aria-labelledby") in ids or attrs.get("data-t-label")), attrs


def test_ui_javascript_syntax():
    for name in ("app.js", "models.js", "research.js", "margin.js", "native-review.js"):
        result = subprocess.run([node(), "--check", str(UI.with_name(name))], capture_output=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr


def test_ui_runtime_contracts():
    result = subprocess.run(
        [node(), str(Path(__file__).with_name("ui_contract.cjs")), str(UI.with_name("app.js"))],
        input=json.dumps(page()), capture_output=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_review_lives_on_the_operate_view():
    html = UI.read_text("utf-8")
    operate = html.split('id="v-operate"', 1)[1].split('id="v-rules"', 1)[0]
    assert 'id="native-review-form"' in operate


def test_every_ui_node_suite_runs():
    root = Path(__file__).parent
    suites = sorted(str(path) for path in (root / "ui").glob("*.test.cjs"))
    assert len(suites) >= 3
    result = subprocess.run([node(), "--test", *suites], cwd=root.parent, capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
