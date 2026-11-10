"""U-3: the stylesheet and DESIGN.md must not drift. A new size, radius or colour goes into DESIGN.md first."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "gym-core/src/gym/ui/styles.css").read_text(encoding="utf-8")
DESIGN = (ROOT / "DESIGN.md").read_text(encoding="utf-8")


def block(name):
    match = re.search(rf"^{name}:\n((?:  .+\n)+)", DESIGN, re.MULTILINE)
    return dict(re.findall(r'^  ([a-z0-9-]+): "([^"]+)"', match.group(1), re.MULTILINE))


def test_font_sizes_match():
    css = {float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", CSS)}
    doc = {float(x) for x in re.findall(r'fontSize:\s*"?([\d.]+)px', DESIGN)}
    assert css == doc, (sorted(css - doc), sorted(doc - css))


def test_radii_are_design_tokens():
    tokens = set(block("rounded").values())
    used = set(re.findall(r"border-radius:\s*([\d.]+px|50%)", CSS))
    assert used <= tokens, sorted(used - tokens)


def test_theme_colours_match_design_colours():
    colours = block("colors")
    light_css, dark_css = CSS.split('[data-theme="dark"] {', 1)
    light = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3,8});", light_css.split("}", 1)[0]))
    dark = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3,8});", dark_css.split("}", 1)[0]))
    assert len(light) >= 20 and len(dark) >= 5
    checked = 0
    for name, value in light.items():
        if name in colours:
            assert colours[name].lower() == value.lower(), (name, value, colours[name])
            checked += 1
    for name, value in dark.items():
        if f"dark-{name}" in colours:
            assert colours[f"dark-{name}"].lower() == value.lower(), ("dark", name, value)
            checked += 1
    assert checked >= 25
