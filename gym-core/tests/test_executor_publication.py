"""Local publication mechanics and the service's pre-listener startup boundary."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "script,expected",
    [
        (
            "Update-ReadOnlyExecutor.ps1",
            "atomic replacement and retained-byte rollback",
        ),
        (
            "Test-ExecutorOperator.ps1",
            "exact u64 values, native frame layout and correlation rejection",
        ),
    ],
)
def test_publication_and_operator_protocol_self_checks(script, expected):
    shell = shutil.which("powershell.exe")
    if shell is None:
        pytest.skip("Windows PowerShell publication self-check requires Windows")
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/windows" / script),
            "-SelfTest",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout


def test_incomplete_publication_veto_precedes_listeners_and_binding_revokes_old_user():
    host = (ROOT / "executor/exec-svc/src/main.rs").read_text("utf-8")
    check = host.index("exec_svc::require_complete_publication")
    assert check < host.index("thread::spawn(")
    assert "startup_failure(ServiceFailure::IncompleteUpdate)" in host[check:]
    bind = (ROOT / "scripts/windows/Bind-ExecutorOperator.ps1").read_text("utf-8")
    assert "gym-review.exe" in bind and '/remove:g "*$previousUser"' in bind
    assert bind.index("Remove-Item -LiteralPath $logonPath") < bind.index("/grant:r")


def test_operator_review_needs_no_service_process_access_and_authenticates_the_pipe():
    control = (ROOT / "executor/exec-svc/src/windows_control.rs").read_text("utf-8")
    read_only = control.split("pub fn pin_readonly()", 1)[1].split(
        "fn validate_config", 1
    )[0]
    assert "service(false)?" in read_only and "pinned.verify()?" in read_only
    assert "OpenProcess" not in read_only
    verification = control.split("impl ReadOnlyPinned", 1)[1].split(
        "pub fn pin_readonly", 1
    )[0]
    assert "validate_config(&self.service)?" in verification
    assert "status.current_state == ServiceState::Running" in verification
    helper = (ROOT / "executor/exec-svc/src/bin/gym-review.rs").read_text("utf-8")
    assert helper.count("authenticate_pipe(pipe.as_handle(), pinned.pid)") == 2
    assert helper.count("pinned.verify()") == 2
