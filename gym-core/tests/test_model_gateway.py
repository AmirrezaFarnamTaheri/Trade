"""Optional gateway launch and real Windows DPAPI byte-boundary checks."""
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gym.cli import main
from gym.services import model_gateway

_HELPER = Path(model_gateway.__file__).parents[1] / "adapters" / "model_credentials.py"


def test_cli_routes_models_without_opening_market_database():
    with patch.object(model_gateway, "run", return_value=7) as run:
        assert main(["models", "catalog", "openai"]) == 7
        run.assert_called_once_with(["catalog", "openai"])


def test_gateway_launch_is_argv_only_and_preserves_exit_status():
    with tempfile.TemporaryDirectory() as folder:
        entry = Path(folder) / "gateway.mjs"
        entry.write_text("", encoding="utf-8")
        with patch.object(model_gateway, "_ENTRY", entry), \
             patch.object(model_gateway.shutil, "which", return_value="node.exe"), \
             patch.object(model_gateway.subprocess, "run", return_value=SimpleNamespace(returncode=9)) as launch:
            assert model_gateway.run(["complete", "name;not-a-shell-command"]) == 9
            args, options = launch.call_args
            assert args[0] == ["node.exe", str(entry), "complete", "name;not-a-shell-command"]
            assert options["check"] is False and "shell" not in options
            assert options["env"]["GYM_MODEL_PYTHON"] == sys.executable
            assert "input" not in options and "capture_output" not in options


def test_gateway_missing_node_fails_without_importing_sdk():
    with patch.object(model_gateway.shutil, "which", return_value=None), \
         patch("sys.stderr", new_callable=io.StringIO) as error:
        assert model_gateway.run(["status"]) == 2
        assert "Node.js >=22.19.0" in error.getvalue()


def test_gateway_missing_entry_or_launch_failure_is_generic():
    with tempfile.TemporaryDirectory() as folder:
        entry = Path(folder) / "gateway.mjs"
        with patch.object(model_gateway, "_ENTRY", entry), \
             patch.object(model_gateway.shutil, "which", return_value="node"), \
             patch("sys.stderr", new_callable=io.StringIO) as error:
            assert model_gateway.run([]) == 2
            assert "complete source checkout" in error.getvalue()
            entry.write_text("", encoding="utf-8")
            with patch.object(model_gateway.subprocess, "run", side_effect=OSError("private-canary")):
                assert model_gateway.run([]) == 2
                assert "private-canary" not in error.getvalue()


def test_dpapi_bridge_real_roundtrip_or_explicit_platform_refusal():
    plaintext = b'{"type":"oauth","refresh":"synthetic-test-not-a-real-token"}'
    encrypted = subprocess.run([sys.executable, str(_HELPER), "encrypt"], input=plaintext, capture_output=True, timeout=10)
    if os.name != "nt":
        assert encrypted.returncode == 2 and encrypted.stdout == b""
        assert plaintext not in encrypted.stderr
        return
    assert encrypted.returncode == 0 and encrypted.stderr == b""
    assert encrypted.stdout != plaintext and plaintext not in encrypted.stdout
    decrypted = subprocess.run([sys.executable, str(_HELPER), "decrypt"], input=encrypted.stdout, capture_output=True, timeout=10)
    assert decrypted.returncode == 0 and decrypted.stdout == plaintext and decrypted.stderr == b""


def test_dpapi_bridge_refuses_bad_operation_corruption_and_size_without_echo():
    for operation, payload in (("decrypt", b"private-canary"), ("unknown", b"private-canary"), ("encrypt", b"x" * 65537)):
        result = subprocess.run([sys.executable, str(_HELPER), operation], input=payload, capture_output=True, timeout=10)
        assert result.returncode == 2 and result.stdout == b""
        assert result.stderr.strip() == b"error: model credential operation failed"
