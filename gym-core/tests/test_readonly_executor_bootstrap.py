"""Static release-guard checks; Windows execution/ACL tests are a separate gate."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts/windows/Install-ReadOnlyExecutor.ps1"
VERIFY = ROOT / "scripts/windows/Test-ReadOnlyExecutor.ps1"
HOST = ROOT / "executor/exec-svc/src/main.rs"


def test_installer_refuses_automatic_activation_and_uses_local_service():
    body = INSTALL.read_text(encoding="utf-8")
    assert "#Requires -RunAsAdministrator" in body
    assert "'start=', 'disabled'" in body
    assert 'NT AUTHORITY\\LocalService' in body
    assert 'sidtype' in body and 'restricted' in body
    assert 'Start-Service' not in body
    assert 'start= auto' not in body
    assert 'start= demand' not in body
    assert 'password=' not in body


def test_bootstrap_protects_code_and_ledger_data_and_never_provisions_keys():
    body = INSTALL.read_text(encoding="utf-8")
    for fragment in ('/inheritance:r', '/grant:r', 'Get-FileHash', 'Test-ReadOnlyExecutor.ps1'):
        assert fragment in body
    for forbidden in ('withdraw', 'api_key', 'Read-Host -AsSecureString'):
        assert forbidden not in body.lower()


def test_verifier_requires_protected_dacls_and_rejects_broad_access():
    body = VERIFY.read_text(encoding="utf-8")
    for fragment in ('AreAccessRulesProtected', 'SecurityIdentifier', 'S-1-1-0',
                     'S-1-5-32-545', 'S-1-5-11', 'S-1-5-4',
                     'NT SERVICE\\TradingGYMExecutor', 'StartMode'):
        assert fragment in body
    assert 'throw' in body


def test_service_host_uses_scm_and_refuses_wrong_account():
    body = HOST.read_text(encoding="utf-8")
    assert 'service_dispatcher::start' in body
    assert 'ServiceControl::Stop' in body
    assert 'is_local_service' in body
    assert 'ServiceState::Stopped' in body
    assert 'POST' not in body
