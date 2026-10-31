//! Disarmed Windows service with independent stop-only T0 listener.
//! This controls only the monotone in-memory gate; NO orders, keys or exits.
#[cfg(not(windows))]
fn main() {
    eprintln!("gym-executor is available only as a Windows service");
    std::process::exit(2);
}
#[cfg(windows)]
fn main() -> windows_service::Result<()> { windows_host::start() }

#[cfg(windows)]
mod windows_host {
    use std::ffi::OsString;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{mpsc, Arc};
    use std::thread;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};
    use windows_service::define_windows_service;
    use windows_service::service::{
        ServiceControl, ServiceControlAccept, ServiceExitCode,
        ServiceState, ServiceStatus, ServiceType,
    };
    use windows_service::service_control_handler::{self, ServiceControlHandlerResult};
    use windows_service::service_dispatcher;
    const NAME: &str = "TradingGYMExecutor";
    define_windows_service!(ffi_service_main, service_main);

    pub(super) fn start() -> windows_service::Result<()> {
        service_dispatcher::start(NAME, ffi_service_main)
    }
    fn service_main(_args: Vec<OsString>) { let _ = run_service(); }

    fn status(state: ServiceState, code: u32) -> ServiceStatus {
        ServiceStatus {
            service_type: ServiceType::OWN_PROCESS,
            current_state: state,
            controls_accepted: if state == ServiceState::Running {
                ServiceControlAccept::STOP
            } else { ServiceControlAccept::empty() },
            exit_code: ServiceExitCode::Win32(code),
            checkpoint: 0,
            wait_hint: Duration::default(),
            process_id: None,
        }
    }

    /// The elevated installer binds a single OS-issued operator *logon* SID.
    /// The protected file cannot be supplied by a regular pipe caller.
    fn provisioned_logon_sid() -> std::io::Result<String> {
        let root = std::env::var_os("ProgramFiles").ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::PermissionDenied, "missing ProgramData")
        })?;
        let file = PathBuf::from(root).join("TradingGYM").join("Executor")
            .join("stop-logon.sid");
        let info = std::fs::symlink_metadata(&file)?;
        if !info.file_type().is_file() || info.file_type().is_symlink() || info.len() > 120 {
            return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied,
                "untrusted stop SID configuration"));
        }
        let text = std::fs::read_to_string(file)?;
        let sid = text.trim();
        let components: Vec<&str> = sid.split('-').collect();
        if !sid.starts_with("S-1-5-5-") || components.len() != 6
            || components[4..].iter().any(|x| x.is_empty() || !x.bytes().all(|b| b.is_ascii_digit()))
        {
            return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied,
                "invalid provisioned logon SID"));
        }
        Ok(sid.to_owned())
    }

    fn run_service() -> windows_service::Result<()> {
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
        if !exec_svc::windows_identity::is_restricted_executor_service() {
            status_handle.set_service_status(status(ServiceState::Stopped, 5))?;
            return Ok(());
        }
        let service_sid = match exec_svc::windows_identity::executor_service_sid_from_os() {
            Ok(sid) => sid,
            Err(_) => {
                status_handle.set_service_status(status(ServiceState::Stopped, 5))?;
                return Ok(());
            }
        };
        let logon_sid = match provisioned_logon_sid() {
            Ok(sid) if exec_svc::windows_pipe::stop_pipe_sddl(&service_sid, &sid).is_ok() => sid,
            _ => {
                status_handle.set_service_status(status(ServiceState::Stopped, 5))?;
                return Ok(());
            }
        };
        let epoch = SystemTime::now().duration_since(UNIX_EPOCH)
            .map(|t| t.as_nanos() as u64).unwrap_or(0);
        let gate = match exec_svc::StopGate::new(epoch) {
            Ok(gate) => Arc::new(gate),
            Err(_) => {
                status_handle.set_service_status(status(ServiceState::Stopped, 5))?;
                return Ok(());
            }
        };
        let (ready_tx, ready_rx) = mpsc::channel();
        let listener_failed = Arc::new(AtomicBool::new(false));
        let failed = Arc::clone(&listener_failed);
        let stop_on_failure = Arc::clone(&should_stop);
        // This independent T0 thread never waits for Python, UI or the main
        // proposal/reconciliation loop and cannot gain funded permissions.
        thread::spawn(move || {
            let result = tokio::runtime::Builder::new_current_thread()
                .enable_all().build()
                .map_err(std::io::Error::other)
                .and_then(|rt| rt.block_on(exec_svc::windows_pipe::serve_stop_only(
                    gate, &service_sid, &logon_sid, Some(ready_tx),
                )));
            if result.is_err() {
                failed.store(true, Ordering::SeqCst);
                stop_on_failure.store(true, Ordering::SeqCst);
            }
        });
        if ready_rx.recv_timeout(Duration::from_secs(5)).is_err()
            || listener_failed.load(Ordering::SeqCst)
            || should_stop.load(Ordering::SeqCst)
        {
            status_handle.set_service_status(status(ServiceState::Stopped, 5))?;
            return Ok(());
        }
        // SCM RUNNING means the stop pipe exists, NOT exit protection.
        status_handle.set_service_status(status(ServiceState::Running, 0))?;
        while !should_stop.load(Ordering::SeqCst) {
            thread::sleep(Duration::from_millis(50));
        }
        status_handle.set_service_status(status(ServiceState::Stopped,
            if listener_failed.load(Ordering::SeqCst) { 5 } else { 0 }))?;
        Ok(())
    }
}
