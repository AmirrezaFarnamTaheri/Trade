"""Mobile action controls share the 44 px touch-target floor."""
import re
from pathlib import Path


def test_mobile_touch_target_floor_includes_regular_actions_and_research_tabs():
    css = (Path(__file__).parents[1] / "src/gym/ui/styles.css").read_text("utf-8")
    mobile = css.split("@media (max-width: 600px) {", 1)[1].split(".confirm-dialog", 1)[0]
    covered = set()
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]+)\}", mobile):
        if re.search(r"min-height:\s*44px\s*;", declarations):
            covered.update(selector.strip() for selector in selectors.split(","))
    assert {".button", ".view-header > .button", ".segmented button",
            ".sidebar .button-quiet", '.tabs [role="tab"]'} <= covered
