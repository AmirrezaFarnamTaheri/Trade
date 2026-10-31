//! Deliberately dormant, read-only Windows SCM host.
//! No IPC listener, venue client, credentials, order path or funded arming.
//! A service that reaches RUNNING here is *not* emergency stop protection.

#[cfg(not(windows))]
fn main() {
    eprintln!("gym-executor bootstrap runs only as a Windows service");
    std::process::exit(2);
}

#[cfg(windows)]
fn main() -> windows_service::Result<()> {
    windows_host::start()
}

#[cfg(windows)]
mod windows_host {
    use std::ffi::OsString;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::thread;
    use std::time::Duration;
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

    fn service_main(_args: Vec<OsString>) {
        // SCM controls remain available only while this routine is active.
        // No secrets or network requests are possible in this binary.
        let _ = run_service();
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

    fn run_service() -> windows_service::Result<()> {
        let should_stop = Arc::new(AtomicBool::new(false));
        let signal = Arc::clone(&should_stop);
        let handler = move |event| match event {
            ServiceControl::Stop => {
                signal.store(true, Ordering::SeqCst);
                ServiceControlHandlerResult::NoError
            }
            ServiceControl::Interrogate => ServiceControlHandlerResult::NoError,
            _ => ServiceControlHandlerResult::NotImplemented,
        };
        let status_handle = service_control_handler::register(NAME, handler)?;
        // An unexpected token means this host cannot run. Windows error 5 is
        // visible in SCM; do not silently fall back to an interactive identity.
        if !exec_svc::windows_identity::is_local_service() {
            status_handle.set_service_status(status(ServiceState::Stopped, 5))?;
            return Ok(());
        }
        // This status is SCM process liveness, NOT a claim that HALT/EXIT work.
        status_handle.set_service_status(status(ServiceState::Running, 0))?;
        while !should_stop.load(Ordering::SeqCst) {
            thread::sleep(Duration::from_millis(100));
        }
        status_handle.set_service_status(status(ServiceState::Stopped, 0))?;
        Ok(())
    }
}
