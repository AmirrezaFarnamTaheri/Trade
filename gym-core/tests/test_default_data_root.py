"""Default checkout data path is stable regardless of launch directory."""

from pathlib import Path

import pytest

from gym import cli
from gym.commands import common

REPO = Path(__file__).resolve().parents[2]


def test_default_checkout_root_is_independent_of_working_directory(monkeypatch):
    for cwd in (REPO, REPO / "gym-core"):
        monkeypatch.chdir(cwd)
        assert common.default_data_root() == REPO / "data"


def test_cli_defaults_to_same_data_root_from_both_directories(monkeypatch):
    class CapturedArguments(Exception):
        pass

    observed = []

    def capture(args):
        observed.append(args.data)
        raise CapturedArguments

    monkeypatch.setattr(cli, "open_db", capture)
    for cwd in (REPO, REPO / "gym-core"):
        monkeypatch.chdir(cwd)
        with pytest.raises(CapturedArguments):
            cli.main(["rules", "list"])
    assert observed == [str(REPO / "data")] * 2


def test_explicit_cli_data_override_is_retained(monkeypatch, tmp_path):
    class CapturedArguments(Exception):
        pass

    observed = []

    def capture(args):
        observed.append(args.data)
        raise CapturedArguments

    monkeypatch.setattr(cli, "open_db", capture)
    monkeypatch.chdir(REPO / "gym-core")
    with pytest.raises(CapturedArguments):
        cli.main(["--data", str(tmp_path / "isolated"), "rules", "list"])
    assert observed == [str(tmp_path / "isolated")]
