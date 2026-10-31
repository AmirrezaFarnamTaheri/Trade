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
