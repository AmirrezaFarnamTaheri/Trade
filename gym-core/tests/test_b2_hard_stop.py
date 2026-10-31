"""B2 last-resort hard stop is operator-elevated containment, not exit safety."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARD = ROOT / "scripts/windows/Invoke-ExecutorHardStop.ps1"
VM = ROOT / "scripts/windows/Test-ReadOnlyExecutorOnHostedVm.ps1"
WORKFLOW = ROOT / ".github/workflows/validate.yml"


def test_hard_stop_is_elevated_and_requires_explicit_loss_of_protection_consent():
    body = HARD.read_text("utf-8")
    assert "#Requires -RunAsAdministrator" in body
    assert "SupportsShouldProcess = $true" in body
    assert "ConfirmImpact = 'High'" in body
    assert "$AcknowledgeLossOfProtection" in body
    assert "ShouldProcess" in body
    assert "UNPROTECTED" in body
    assert "Stop-Service" in body
    assert "start=', 'disabled'" in body
    assert "NT AUTHORITY\\LocalService" in body
    assert "gym-executor.exe" in body
    assert "client_id" not in body.lower()
    assert "secrets.dat" not in body.lower()


def test_disposable_windows_runner_runs_hard_stop_only_on_own_noop_service():
    smoke = VM.read_text("utf-8")
    assert "Invoke-ExecutorHardStop.ps1" in smoke
    assert "AcknowledgeLossOfProtection" in smoke
    assert "Assert-ServiceState -StartMode 'Disabled' -State 'Stopped'" in smoke
    workflow = WORKFLOW.read_text("utf-8")
    assert "Invoke-ExecutorHardStop.ps1" in workflow
    assert "windows-vm-smoke:" in workflow
    assert "github.event_name == 'push'" in workflow
