//! Disarmed service with independent T0 STOP and privileged custody/account/limit control.
//! Custody and account GETs are implemented; funded orders and protective exits are not.
#[cfg(windows)]
mod credential_vault;
#[cfg(windows)]
mod operate_pipe;
#[cfg(windows)]
mod privileged_pipe;
#[cfg(windows)]
mod service_account;

#[cfg(not(windows))]
fn main() {
    eprintln!("gym-executor is available only as a Windows service");
    std::process::exit(2);
}
#[cfg(windows)]
fn main() -> windows_service::Result<()> {
    windows_host::start()
}

#[cfg(windows)]
mod windows_host {
    use exec_svc::ServiceFailure;
    use std::ffi::OsString;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
    use std::sync::{mpsc, Arc};
    use std::thread;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};
    use windows_service::define_windows_service;
    use windows_service::service::{
        ServiceControl, ServiceControlAccept, ServiceExitCode, ServiceState, ServiceStatus,
        ServiceType,
    };
    use windows_service::service_control_handler::{self, ServiceControlHandlerResult};
    use windows_service::service_dispatcher;
    const NAME: &str = "TradingGYMExecutor";
    define_windows_service!(ffi_service_main, service_main);

    pub(super) fn start() -> windows_service::Result<()> {
        service_dispatcher::start(NAME, ffi_service_main)
    }
    fn service_main(args: Vec<OsString>) {
        let _ = run_service(args);
    }

    fn status(state: ServiceState, code: u32) -> ServiceStatus {
        ServiceStatus {
            service_type: ServiceType::OWN_PROCESS,
            current_state: state,
            controls_accepted: if state == ServiceState::Running {
                ServiceControlAccept::STOP
            } else {
                ServiceControlAccept::empty()
            },
            exit_code: ServiceExitCode::Win32(code),
            checkpoint: 0,
            wait_hint: Duration::default(),
            process_id: None,
        }
    }

    fn startup_failure(failure: ServiceFailure) -> ServiceStatus {
        let mut result = status(ServiceState::Stopped, 0);
        result.exit_code = ServiceExitCode::ServiceSpecific(failure as u32);
        result
    }

    /// The elevated installer binds a single OS-issued operator *logon* SID.
    /// The protected file cannot be supplied by a regular pipe caller.
    fn provisioned_logon_sid() -> std::io::Result<String> {
        let root = std::env::var_os("ProgramFiles").ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::PermissionDenied, "missing ProgramData")
        })?;
        let file = PathBuf::from(root)
            .join("TradingGYM")
            .join("Executor")
            .join("stop-logon.sid");
        let info = std::fs::symlink_metadata(&file)?;
        if !info.file_type().is_file() || info.file_type().is_symlink() || info.len() > 120 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "untrusted stop SID configuration",
            ));
        }
        let text = std::fs::read_to_string(file)?;
        let sid = text.trim();
        let components: Vec<&str> = sid.split('-').collect();
        if !sid.starts_with("S-1-5-5-")
            || components.len() != 6
            || components[4..]
                .iter()
                .any(|x| x.is_empty() || !x.bytes().all(|b| b.is_ascii_digit()))
        {
            return Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "invalid provisioned logon SID",
            ));
        }
        Ok(sid.to_owned())
    }

    /// Operator user identity is separately provisioned from a trusted OS
    /// process token, never copied from a client request or environment value.
    fn provisioned_user_sid() -> std::io::Result<String> {
        let root = std::env::var_os("ProgramFiles").ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::PermissionDenied, "missing ProgramFiles")
        })?;
        let file = PathBuf::from(root)
            .join("TradingGYM")
            .join("Executor")
            .join("stop-user.sid");
        let info = std::fs::symlink_metadata(&file)?;
        if !info.file_type().is_file() || info.file_type().is_symlink() || info.len() > 120 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "untrusted operator user SID configuration",
            ));
        }
        let value = std::fs::read_to_string(file)?;
        let sid = value.trim();
        let components: Vec<&str> = sid.split('-').collect();
        if !sid.starts_with("S-1-")
            || !(5..=16).contains(&components.len())
            || components
                .iter()
                .skip(1)
                .any(|x| x.is_empty() || !x.bytes().all(|b| b.is_ascii_digit()))
        {
            return Err(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                "invalid provisioned operator user SID",
            ));
        }
        Ok(sid.to_owned())
    }

    fn run_service(args: Vec<OsString>) -> windows_service::Result<()> {
        let should_stop = Arc::new(AtomicBool::new(false));
        let callback_stop = Arc::clone(&should_stop);
        let handler = move |event| match event {
            ServiceControl::Stop => {
                callback_stop.store(true, Ordering::SeqCst);
                ServiceControlHandlerResult::NoError
            }
            ServiceControl::Interrogate => ServiceControlHandlerResult::NoError,
            _ => ServiceControlHandlerResult::NotImplemented,
        };
        let status_handle = service_control_handler::register(NAME, handler)?;
        // StartService arguments are SCM-admin controlled, never accepted from a pipe.
        let arguments: Option<Vec<String>> = args
            .iter()
            .skip(1)
            .map(|s| s.to_str().map(str::to_owned))
            .collect();
        let mode = match arguments
            .and_then(|a| exec_ipc::provision::StartupMode::from_scm_arguments(&a).ok())
        {
            Some(mode) => mode,
            None => {
                status_handle.set_service_status(status(ServiceState::Stopped, 87))?;
                return Ok(());
            }
        };
        if !exec_svc::windows_identity::is_restricted_executor_service() {
            status_handle
                .set_service_status(startup_failure(ServiceFailure::RestrictedIdentity))?;
            return Ok(());
        }
        let service_sid = match exec_svc::windows_identity::executor_service_sid_from_os() {
            Ok(sid) => sid,
            Err(_) => {
                status_handle
                    .set_service_status(startup_failure(ServiceFailure::ServiceIdentity))?;
                return Ok(());
            }
        };
        let logon_sid = match provisioned_logon_sid() {
            Ok(sid) if exec_svc::windows_pipe::stop_pipe_sddl(&service_sid, &sid).is_ok() => sid,
            _ => {
                status_handle.set_service_status(startup_failure(ServiceFailure::OperatorLogon))?;
                return Ok(());
            }
        };
        let operator_user = match provisioned_user_sid() {
            Ok(sid) => sid,
            Err(_) => {
                status_handle.set_service_status(startup_failure(ServiceFailure::OperatorUser))?;
                return Ok(());
            }
        };
        let epoch = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|t| t.as_nanos() as u64)
            .unwrap_or(0);
        let gate = match exec_svc::StopGate::new(epoch) {
            Ok(gate) => Arc::new(gate),
            Err(_) => {
                status_handle.set_service_status(startup_failure(ServiceFailure::StopGate))?;
                return Ok(());
            }
        };
        let (privileged_tx, privileged_rx) = mpsc::channel();
        let privileged_sid = service_sid.clone();
        let privileged_operator = operator_user.clone();
        let privileged_failed = Arc::new(AtomicBool::new(false));
        let privileged_phase = Arc::new(AtomicU32::new(ServiceFailure::PrivilegedListener as u32));
        let failure_phase = privileged_phase.clone();
        let failed_t2 = privileged_failed.clone();
        let stop_t2 = should_stop.clone();
        let operator_context = crate::operate_pipe::Context {
            gate: gate.clone(),
            user: privileged_operator,
            logon: logon_sid.clone(),
            stop: should_stop.clone(),
            failed: privileged_failed.clone(),
            phase: privileged_phase.clone(),
        };
        thread::spawn(move || {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .map_err(std::io::Error::other)
                    .and_then(|rt| {
                        rt.block_on(crate::privileged_pipe::serve(
                            &privileged_sid,
                            privileged_tx,
                            mode,
                            failure_phase,
                            operator_context,
                        ))
                    })
            }));
            if mode != exec_ipc::provision::StartupMode::CredentialRecovery
                || !matches!(result, Ok(Ok(())))
            {
                failed_t2.store(true, Ordering::SeqCst);
            }
            stop_t2.store(true, Ordering::SeqCst);
        });
        match privileged_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(Ok(())) if !privileged_failed.load(Ordering::SeqCst) => {}
            result => {
                let failure = match result {
                    Ok(Err(failure)) => failure,
                    _ => ServiceFailure::PrivilegedListener,
                };
                status_handle.set_service_status(startup_failure(failure))?;
                return Ok(());
            }
        }
        let (ready_tx, ready_rx) = mpsc::channel();
        let listener_failed = Arc::new(AtomicBool::new(false));
        let failed = Arc::clone(&listener_failed);
        let stop_on_failure = Arc::clone(&should_stop);
        // This independent T0 thread never waits for Python, UI or the main
        // proposal/reconciliation loop and cannot gain funded permissions.
        thread::spawn(move || {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .map_err(std::io::Error::other)
                    .and_then(|rt| {
                        rt.block_on(exec_svc::windows_pipe::serve_stop_only(
                            gate,
                            &service_sid,
                            &logon_sid,
                            &operator_user,
                            Some(ready_tx),
                        ))
                    })
            }));
            // Any return (or panic) loses T0; never leave SCM RUNNING.
            let _ = result;
            failed.store(true, Ordering::SeqCst);
            stop_on_failure.store(true, Ordering::SeqCst);
        });
        if ready_rx.recv_timeout(Duration::from_secs(5)).is_err()
            || listener_failed.load(Ordering::SeqCst)
            || should_stop.load(Ordering::SeqCst)
        {
            status_handle.set_service_status(startup_failure(ServiceFailure::StopListener))?;
            return Ok(());
        }
        // SCM RUNNING means the stop pipe exists, NOT exit protection.
        status_handle.set_service_status(status(ServiceState::Running, 0))?;
        // Explicit SCM-admin drill: T0 must remain responsive while this loop is hung.
        if mode == exec_ipc::provision::StartupMode::StopIsolationDrill {
            loop {
                thread::park();
            }
        }
        while !should_stop.load(Ordering::SeqCst) {
            thread::sleep(Duration::from_millis(50));
        }
        let mut stopped = status(
            ServiceState::Stopped,
            if listener_failed.load(Ordering::SeqCst) || privileged_failed.load(Ordering::SeqCst) {
                5
            } else {
                0
            },
        );
        if privileged_failed.load(Ordering::SeqCst) {
            stopped.exit_code =
                ServiceExitCode::ServiceSpecific(privileged_phase.load(Ordering::SeqCst));
        }
        status_handle.set_service_status(stopped)?;
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn a_diagnostic_failure_is_stopped_without_control_authority() {
            let failure = startup_failure(ServiceFailure::RestrictedIdentity);
            assert_eq!(failure.current_state, ServiceState::Stopped);
            assert!(failure.controls_accepted.is_empty());
            assert_eq!(failure.exit_code, ServiceExitCode::ServiceSpecific(1001));
        }
    }
}
