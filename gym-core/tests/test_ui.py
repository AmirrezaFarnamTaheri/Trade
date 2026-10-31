"""Syntax checks for the bundled browser application."""
import pytest




def test_ui_javascript_syntax():
    import shutil
    import subprocess
    from gym.api.server import UI
    node = shutil.which("node")
    if not node:
        pytest.skip("Node not installed; UI syntax check unavailable")
    result = subprocess.run([node, "--check", str(UI.with_name("app.js"))], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
