"""Contract checks for Windows-only SCM and hostile-principal tests.

These checks cannot substitute for real Win32 ACL / token tests.  They ensure
that the target-side negative test and explicit SCM descriptor stay in the
version-controlled release gates.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts/windows/Install-ReadOnlyExecutor.ps1"
VERIFY = ROOT / "scripts/windows/Test-ReadOnlyExecutor.ps1"
DENIAL = ROOT / "scripts/windows/Test-UnprivilegedExecutorAccess.ps1"
CI = ROOT / ".github/workflows/validate.yml"


def test_service_is_registered_with_an_explicit_read_only_scm_dacl():
    source = INSTALL.read_text(encoding="utf-8")
    assert "'sdset'" in source
    assert re.search(r"D:P\(A;;GA;;;SY\)\(A;;GA;;;BA\)\(A;;0x[0-9a-fA-F]+;;;AU\)", source)
    mask = int(re.search(r"\(A;;0x([0-9a-fA-F]+);;;AU\)", source).group(1), 16)
    # No user-origin control: config, start, stop, pause, user controls,
    # deletion, writing the descriptor, ownership or generic write/all.
    forbidden = 0x2 | 0x10 | 0x20 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000
    assert mask & forbidden == 0
    assert mask & 0x4 != 0  # Query service status is still usable by operator.


def test_elevated_audit_inspects_scm_dacl_not_just_start_mode():
    body = VERIFY.read_text(encoding="utf-8")
    assert 'sdshow' in body
    assert 'CommonSecurityDescriptor' in body
    assert 'AccessMask' in body
    assert 'Service SCM descriptor' in body
    assert '$ace.AccessMask -ne 0x0002008D' in body


def test_unprivileged_script_uses_real_denied_access_attempts_not_only_acl_text():
    body = DENIAL.read_text(encoding="utf-8")
    assert 'WindowsBuiltInRole' in body
    assert 'Administrator' in body
    assert 'File]::Open' in body
    assert '[IO.FileMode]::CreateNew' in body  # no accidental overwrite of an existing object
    assert 'InnerException' in body  # unwrap PowerShell's MethodInvocationException
    assert 'OpenService' in body
    assert 'GetLastWin32Error' in body
    assert 'should remain DISABLED' in body
    assert 'ACCESS_DENIED' in body
    assert 'OpenSCManager' in body
    assert 'if ($writePermitted)' in body  # cleanup failure must not mask a successful write


def test_windows_ci_syntax_checks_include_negative_probe():
    body = CI.read_text(encoding="utf-8")
    assert 'Test-UnprivilegedExecutorAccess.ps1' in body
