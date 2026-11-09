"""Page structure and runtime contracts for the bundled browser application."""
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from gym.api.server import UI, UI_ASSETS


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
    for name in UI_ASSETS:
        if not name.endswith(".js"):
            continue
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


def test_shell_stays_routing_only_and_view_assets_load_in_order():
    """Require UI modules to load in declared dependency order with a slim shell."""
    html = UI.read_text("utf-8")
    names = ["workspace-config.js", "workspace-utils.js", "workspace-overview.js",
             "workspace-alerts.js", "app.js", "markets-events.js", "research-events.js",
             "operator-events.js", "shell-events.js"]
    assert all(html.count(f'src="/{name}"') == 1 for name in names)
    assert [html.index(f'src="/{name}"') for name in names] == sorted(html.index(f'src="/{name}"') for name in names)
    assert set(names) <= set(UI_ASSETS)
    shell = UI.with_name("app.js").read_text("utf-8")
    assert len(shell.splitlines()) < 150
    assert "function route(" in shell and "async function showView(" in shell
    assert "function renderOverview(" not in shell


def test_persian_copy_outside_the_vocabulary_does_not_grow():
    """Copy kept in workspace-config.js gets one native-speaker review; inline pairs elsewhere are missed.

    The counts are the lines holding Persian on 2026-11-09. Moving copy into the vocabulary lowers them (update
    the table down); adding inline Persian anywhere else fails here.
    """
    import re
    allowed = {"margin.js": 39, "models.js": 11, "native-review.js": 2, "portfolio.js": 52, "replay-chart.js": 4,
               "research.js": 188, "workspace-overview.js": 2, "workspace-utils.js": 1, "index.html": 2}
    persian = re.compile("[\u0600-\u06ff]")
    for path in [*sorted(UI.with_name("app.js").parent.glob("*.js")), UI.with_name("index.html")]:
        if path.name == "workspace-config.js":
            continue
        lines = sum(1 for line in path.read_text("utf-8").splitlines() if persian.search(line))
        assert lines <= allowed.get(path.name, 0), f"{path.name}: {lines} lines of inline Persian; move copy to workspace-config.js"
