"""Release guards for isolated Windows SCM smoke tests.

These checks are deliberately static; only the Windows GitHub Actions job
can prove actual SCM token and NTFS/SCM access decisions.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / '.github/workflows/validate.yml'
SMOKE = ROOT / 'scripts/windows/Test-ReadOnlyExecutorOnHostedVm.ps1'


def test_smoke_script_is_restricted_to_ephemeral_github_hosted_windows():
    script = SMOKE.read_text(encoding='utf-8')
    assert "RUNNER_ENVIRONMENT -ne 'github-hosted'" in script
    assert "RUNNER_OS -ne 'Windows'" in script
    assert "GITHUB_ACTIONS -ne 'true'" in script
    assert 'IsInRole' in script and 'Administrator' in script
    assert '(Test-Path -LiteralPath $CodeRoot)' in script
    assert '(Test-Path -LiteralPath $DataRoot)' in script


def test_smoke_performs_real_disabled_install_and_stopped_acl_audit():
    script = SMOKE.read_text(encoding='utf-8')
    assert 'Install-ReadOnlyExecutor.ps1' in script
    assert 'Test-ReadOnlyExecutor.ps1' in script
    assert 'Test-UnprivilegedExecutorAccess.ps1' in script
    assert '-WhatIf' in script
    assert '-Confirm:$false' in script
    assert "Assert-ServiceState -StartMode 'Disabled' -State 'Stopped'" in script
    assert "$service.State -ne $State" in script
    assert 'Get-FileHash' in script


def test_smoke_runs_two_non_admin_principals_and_checks_exit_codes():
    script = SMOKE.read_text(encoding='utf-8')
    assert 'New-LocalUser' in script
    assert 'Start-Process' in script and '-Credential' in script
    assert 'Remove-LocalUser' in script
    assert "'operator'" in script and "'worker'" in script
    assert 'ExitCode -ne 0' in script
    assert 'ACCESS_DENIED' in script
    assert 'finally {' in script


def test_smoke_proves_token_identity_with_temporary_read_only_scm_start():
    script = SMOKE.read_text(encoding='utf-8')
    assert 'Start-Service' in script and 'Stop-Service' in script
    assert "'start=', 'demand'" in script
    assert "'start=', 'disabled'" in script
    assert "Assert-ServiceState -StartMode 'Manual' -State 'Running'" in script
    assert 'finally {' in script


def test_ci_runs_smoke_only_on_trusted_repo_push_and_locked_build():
    ci = CI.read_text(encoding='utf-8')
    assert 'windows-vm-smoke:' in ci
    assert 'windows-latest' in ci
    assert "github.event_name == 'push'" in ci
    assert "github.repository == 'AmirrezaFarnamTaheri/Trade'" in ci
    assert 'permissions:' in ci and 'contents: read' in ci
    assert 'cargo build --release --locked -p exec-svc --bin gym-executor' in ci
    assert 'Test-ReadOnlyExecutorOnHostedVm.ps1' in ci
    assert 'timeout-minutes:' in ci


def test_preexisting_service_or_install_roots_are_never_deleted_by_finally():
    script = SMOKE.read_text(encoding='utf-8')
    assert '$OwnServiceInstall = $false' in script
    assert '$OwnServiceInstall = $true' in script
    assert 'if ($OwnServiceInstall)' in script
    assert '$ReportCreated = $false' in script
    assert '$ReportCreated = $true' in script
