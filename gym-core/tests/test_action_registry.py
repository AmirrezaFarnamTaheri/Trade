"""U-4: one action table drives the CLI choices; every action is offered in the browser or named CLI-only."""
import re
from pathlib import Path

from gym.services import research_actions as ra

UI = Path(__file__).resolve().parents[1] / "src/gym/ui"


def _browser_references() -> set[str]:
    text = "".join(p.read_text(encoding="utf-8") for p in UI.glob("*.js"))
    menu = re.search(r"const actions = \{(.*?)\n  \};", (UI / "research.js").read_text(encoding="utf-8"), re.DOTALL).group(1)
    keys = set(re.findall(r"^\s+'?([a-z][a-z-]*)'?:", menu, re.MULTILINE))
    quoted = set(re.findall(r"['\"]([a-z]+(?:-[a-z]+)*)['\"]", text))
    return keys | quoted


def _dispatchable() -> set[str]:
    handled = set().union(*(set(names) for names, _ in ra._RESEARCH_HANDLERS))
    return handled | {"register", "shadow-open", "shadow-close", "schedule", "pause", "resume", "list", "tick"}


def test_every_dispatchable_action_is_a_cli_choice():
    assert _dispatchable() - set(ra.CLI_ACTIONS) == set()
    assert set(ra.CLI_ACTIONS) - _dispatchable() == {"start", "mcp"}  # handled by the CLI itself


def test_every_cli_action_has_a_browser_form_or_a_stated_reason():
    browser = _browser_references()
    for action in ra.CLI_ACTIONS:
        if action in ra.CLI_ONLY_ACTIONS:
            assert ra.CLI_ONLY_ACTIONS[action], action
        else:
            assert action in browser, f"{action}: add a browser form or list it in CLI_ONLY_ACTIONS"


def test_cli_only_entries_are_real_and_not_offered_in_the_research_menu():
    menu = (UI / "research.js").read_text(encoding="utf-8")
    for action in ra.CLI_ONLY_ACTIONS:
        assert action in ra.CLI_ACTIONS, action
        assert f"'{action}':" not in menu and f"\n    {action}:" not in menu, action


def test_catalog_and_the_cli_parser_agree(capsys):
    import pytest

    from gym.cli import main
    catalog = {row["action"]: row for row in ra.action_catalog()}
    assert set(catalog) == set(ra.CLI_ACTIONS)
    assert catalog["technicals"]["browser"] and not catalog["tick"]["browser"]
    with pytest.raises(SystemExit):
        main(["research", "no-such-action"])
    offered = re.search(r"choose from (.*)\)", capsys.readouterr().err, re.DOTALL).group(1)
    assert set(re.findall(r"[a-z]+(?:-[a-z]+)*", offered)) == set(ra.CLI_ACTIONS)


def test_each_registered_action_has_exactly_one_handler():
    names = [action for actions, _ in ra._RESEARCH_HANDLERS for action in actions]
    assert len(names) == len(set(names))
