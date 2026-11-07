"""Windows launchers retain a canonical data root and whole-market defaults."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32" or shutil.which("uv") is None, reason="Windows scheduled-task tools")
def test_collector_task_uses_explicit_data_root_and_all_market_default(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    data = tmp_path / "observed data"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File",
                             str(repo / "scripts/windows/Install-Collector.ps1"),
                             "-DataDirectory", str(data), "-WhatIf"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert str(data) in result.stdout
    assert "--assets all" in result.stdout
    assert "-I -B -m gym.cli" in result.stdout
    assert ".venv\\Scripts\\python.exe" in result.stdout
    assert "--data" in result.stdout and "--watch" not in result.stdout


@pytest.mark.skipif(sys.platform != "win32" or shutil.which("uv") is None, reason="Windows scheduled-task tools")
def test_workspace_preview_does_not_start_a_process_or_create_a_link(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    data = tmp_path / "observed data"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File",
                             str(repo / "scripts/windows/Start-Workspace.ps1"),
                             "-DataDirectory", str(data), "-WhatIf"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "--assets all" in result.stdout and "Start paper scheduler" in result.stdout
    assert not data.exists()
