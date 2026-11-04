//! Source contracts do not certify Windows runtime isolation. No privileged setup in tests.
#[cfg(windows)]
#[path = "../src/research_worker.rs"]
mod research_worker;

#[cfg(windows)]
#[test]
fn rejects_non_operator_paths_before_any_process_or_profile_operation() {
    for path in [
        "",
        ".",
        "relative",
        "C:relative",
        "\\\\server\\share",
        "C:\\input:stream",
        "C:\\input\"bad",
    ] {
        assert_eq!(
            research_worker::launch(std::path::Path::new(path), false)
                .unwrap_err()
                .kind(),
            std::io::ErrorKind::PermissionDenied
        );
    }
}
const NATIVE: &str = include_str!("../src/research_worker.rs");
const BINARY: &str = include_str!("../src/bin/gym-research-worker.rs");
const INSTALL: &str = include_str!("../../../scripts/windows/Install-ResearchWorker.ps1");
const INITIALIZE: &str =
    include_str!("../../../scripts/windows/Initialize-ResearchWorkerProfile.ps1");
const PROBE: &str = include_str!("../../../scripts/windows/Test-ResearchWorkerBoundary.ps1");
const PYTHON: &str = include_str!("../../../gym-core/src/gym/services/research_worker.py");

#[test]
fn real_child_is_verified_and_job_assigned_before_resume() {
    let create = NATIVE.find("CreateProcessW(").unwrap();
    let verify = NATIVE[create..]
        .find("verify_token(child.process.0, sid.0)?")
        .unwrap()
        + create;
    let assign = NATIVE[verify..].find("AssignProcessToJobObject").unwrap() + verify;
    let resume = NATIVE[assign..].find("ResumeThread").unwrap() + assign;
    assert!(create < verify && verify < assign && assign < resume);
    for evidence in [
        "CREATE_SUSPENDED",
        "TokenIsAppContainer",
        "TokenAppContainerSid",
        "TokenCapabilities",
        "TokenIntegrityLevel",
        "EqualSid",
        "CapabilityCount: 0",
        "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
        "ActiveProcessLimit = 1",
        "ProcessMemoryLimit = MEMORY_BYTES",
        "WaitForSingleObject(child.process.0, WALL_MS)",
    ] {
        assert!(NATIVE.contains(evidence), "missing {evidence}");
    }
}
#[test]
fn only_fresh_explicit_stdio_and_fixed_installed_python() {
    for evidence in [
        "CreatePipe",
        "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
        "PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES",
        "let mut handles = [stdin.0, stdout.0, stderr.0]",
        "let mut environment = [0u16; 2]",
        "-I -S -B -m gym.services.research_worker",
        "FILE_FLAG_OPEN_REPARSE_POINT",
        "GetSecurityInfo",
        "untrusted mutation",
        "protected profile binding mismatch",
        "SQLite format 3",
        "standalone rollback-mode SQLite",
    ] {
        assert!(NATIVE.contains(evidence), "missing {evidence}");
    }
    for forbidden in [
        "DuplicateHandle",
        "CreateAppContainerProfile",
        "Command::new",
        "powershell",
        "cmd.exe",
        "-c ",
    ] {
        assert!(!NATIVE.contains(forbidden), "unexpected {forbidden}");
    }
    assert!(BINARY.contains("#[path = \"../research_worker.rs\"]"));
    assert!(PYTHON.contains("serve_stdio(root)"));
    assert!(!PYTHON.contains("exec("));
}
#[test]
fn install_is_explicit_and_probes_do_not_fake_absent_targets() {
    for evidence in [
        "SupportsShouldProcess",
        "ConfirmPublicOnly",
        "ProtectedSource",
        "SetAccessRuleProtection($true, $false)",
        "src.backup(dst)",
        "journal_mode=DELETE",
        "DeriveAppContainerSidFromAppContainerName",
        "$operatorSid",
        "NOT_VERIFIED",
    ] {
        assert!(INSTALL.contains(evidence), "missing {evidence}");
    }
    for evidence in [
        "NOT_VERIFIED",
        "GetFiles('\\\\.\\pipe\\')",
        "Test-Path",
        "Get-Service",
        "actual_R0_child",
        "--boundary-probe",
        "market_coverage,research_state,strategy_catalog",
    ] {
        assert!(PROBE.contains(evidence), "missing {evidence}");
    }
    assert!(!PROBE.contains("CreateAppContainerProfile"));
    assert!(!PROBE.contains("Set-Acl"));
    assert!(INITIALIZE.contains("CreateAppContainerProfile"));
    assert!(INITIALIZE.contains("[IntPtr]::Zero,0"));
    assert!(INITIALIZE.contains("actual unelevated operator logon"));
    assert!(!INSTALL.contains("CreateAppContainerProfile"));
    for evidence in [
        "FAIL_OPENED",
        "NOT_VERIFIED_WIN32_",
        "OpenServiceW",
        "CreateFileW",
        "os.getpid()",
        "profile_canary",
    ] {
        assert!(PYTHON.contains(evidence), "missing {evidence}");
    }
}
