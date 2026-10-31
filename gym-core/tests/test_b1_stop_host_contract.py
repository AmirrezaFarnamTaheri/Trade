"""Read-only T0 Windows service activation contract (source checks only).

Real Windows named-pipe creation and ACKs must be tested by hosted CI.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "executor/exec-svc/src/main.rs"
PIPE = ROOT / "executor/exec-svc/src/windows_pipe.rs"
INSTALLER = ROOT / "scripts/windows/Install-ReadOnlyExecutor.ps1"
SMOKE = ROOT / "scripts/windows/Test-ReadOnlyExecutorOnHostedVm.ps1"
CLIENT = ROOT / "executor/exec-svc/src/bin/gym-stopctl.rs"


def test_service_requires_protected_os_derived_logon_sid():
    installer = INSTALLER.read_text("utf-8")
    service = SERVICE.read_text("utf-8")
    assert "stop-logon.sid" in installer and "stop-logon.sid" in service
    helper = (ROOT / "scripts/windows/Get-OperatorLogonSid.ps1").read_text("utf-8")
    assert "Get-OperatorLogonSid.ps1" in installer
    assert "TokenLogonSid" in helper
    assert "GetTokenInformation" in helper
    assert "S-1-5-5-" in helper
    assert "$identity.Groups" not in installer
    assert "S-1-5-5-" in service
    assert "get_current_operator_sid" not in service
    assert "is_restricted_executor_service" in service


def test_service_only_reports_running_after_dedicated_stop_thread_readiness():
    source = SERVICE.read_text("utf-8")
    assert "thread::spawn" in source
    assert "serve_stop_only" in source
    assert "ready_rx.recv_timeout" in source
    assert source.index("ready_rx.recv_timeout") < source.index("status(ServiceState::Running, 0)")
    assert "StopGate::new" in source


def test_named_pipe_server_signals_ready_after_initial_secure_instance():
    source = PIPE.read_text("utf-8")
    assert "create_pipe(service_sid, logon_sid, true)?" in source
    assert "ready.send" in source
    assert "first_pipe_instance(first)" in source


def test_cli_only_sends_stop_commands_and_requires_correlated_ack():
    client = CLIENT.read_text("utf-8")
    assert "StopRequest" in client and "StopReply" in client
    assert "confirm" in client
    assert "read_exact" in client and "write_all" in client
    for command in ('"pause"', '"exit-only"', '"halt"'):
        assert command in client
    assert "place_order" not in client
    assert "api_key" not in client


def test_disposable_vm_exercises_actual_stop_pipe_and_service_remains_disabled():
    script = SMOKE.read_text("utf-8")
    assert "gym-stopctl.exe" in script
    assert "'pause'" in script and "'exit-only'" in script and "'halt'" in script
    assert "Assert-ServiceState -StartMode 'Disabled' -State 'Stopped'" in script
    installer = INSTALLER.read_text("utf-8")
    assert "'start=', 'disabled'" in installer


def test_stop_authorization_config_is_readonly_to_service():
    installer = INSTALLER.read_text("utf-8")
    main = SERVICE.read_text("utf-8")
    assert "$stopSidPath = Join-Path $CodeDir 'stop-logon.sid'" in installer
    assert 'var_os("ProgramFiles")' in main
    assert 'var_os("ProgramData")' not in main
    # CodeDir grants service RX, unlike data folder where service has Modify.
    assert "Invoke-Icacls -Path $CodeDir -Arguments @('/grant:r', $readCode)" in installer


def test_stop_client_requests_only_data_access_not_pipe_instance_creation():
    client = CLIENT.read_text("utf-8")
    assert "CreateFileW" in client
    assert "0x00100003" in client
    assert "OpenOptions::new().read(true).write(true)" not in client


def test_stop_client_reports_win32_error_without_secret_material():
    client = CLIENT.read_text("utf-8")
    assert "std::io::Error::last_os_error()" in client
    assert "stop pipe open failed" in client
    assert "raw_os_error()" in client


def test_disposable_vm_checks_effective_logon_identity_before_stop_client():
    smoke = SMOKE.read_text("utf-8")
    assert "Get-OperatorLogonSid.ps1" in smoke
    assert "stop-logon.sid" in smoke
    assert "T0 ACL preflight" in smoke
    assert "S-1-5-2" in smoke  # deny-NETWORK group membership diagnostic
    assert "Write-Output $expectedSid" not in smoke
    assert "Write-Output $actualSid" not in smoke


def test_hosted_smoke_defines_protected_code_directory_before_reading_stop_sid():
    smoke = SMOKE.read_text("utf-8")
    assert "$CodeDir = Join-Path $CodeRoot 'Executor'" in smoke
    assert "$expectedSid = (Get-Content -LiteralPath (Join-Path $CodeDir 'stop-logon.sid')" in smoke


def test_remote_pipe_rejection_does_not_deny_local_network_group_tokens():
    pipe = PIPE.read_text("utf-8")
    assert ".reject_remote_clients(true)" in pipe
    assert "D:P(A;;GA;;;SY)" in pipe
    assert "D:P(D;;GA;;;NU)" not in pipe


def test_stop_client_uses_identification_only_qos():
    client = CLIENT.read_text("utf-8")
    assert "0x00110000" in client  # SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION
    assert "CreateFileW" in client


def test_disposable_windows_ci_includes_same_logon_descriptor_canary():
    # A temporary, non-money named-pipe canary distinguishes an invalid
    # logon-SID ACL from a service-specific authorization failure.
    script = SMOKE.read_text("utf-8")
    assert "Canary($principalSid)" in script
    assert "T0 caller token restricted" in script
    for group in ("'BA'", "'AU'", "'WD'"):
        assert group in script
    assert "T0 same-logon DACL canary:" in script


def test_operator_stop_pipe_acl_allows_metadata_read_but_not_pipe_creation():
    pipe = PIPE.read_text("utf-8")
    # A real Windows canary reproduced ACCESS_DENIED at 0x00100003 and
    # permitted 0x00100083; the added 0x80 is FILE_READ_ATTRIBUTES.
    assert '0x00100083;;;{logon_sid}' in pipe
    assert "FILE_CREATE_PIPE_INSTANCE" in pipe
    assert "0x00100003;;;{logon_sid}" not in pipe


def test_disposable_host_checks_subsecond_ack_and_denies_other_logon_tokens():
    smoke = SMOKE.read_text("utf-8")
    probe = (ROOT / "scripts/windows/Test-UnprivilegedExecutorAccess.ps1").read_text("utf-8")
    assert "ElapsedMilliseconds -ge 1000" in smoke
    assert "denied active stop pipe" in smoke
    assert "CheckStopPipeOnly" in smoke
    assert "CheckStopPipeOnly" in probe
    assert "CreateFileW" in probe
    assert "GetLastWin32Error()" in probe


def test_hostile_logon_denial_proves_a_distinct_windows_logon_sid():
    probe = (ROOT / "scripts/windows/Test-UnprivilegedExecutorAccess.ps1").read_text("utf-8")
    smoke = SMOKE.read_text("utf-8")
    assert "whoami.exe /logonid" in probe
    assert "ExpectedLogonSid" in probe
    assert "ExpectedLogonSid" in smoke
    assert "same logon" in probe
