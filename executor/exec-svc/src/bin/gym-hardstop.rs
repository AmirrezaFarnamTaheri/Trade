//! Elevated local containment only. Never a filled-exit or protection guarantee.
#[cfg(not(windows))]
fn main() {
    eprintln!("gym-hardstop requires Windows");
    std::process::exit(2);
}
#[cfg(windows)]
#[path = "../windows_control.rs"]
mod windows_control;
#[cfg(windows)]
fn main() {
    if std::env::args().skip(1).collect::<Vec<_>>() != ["--acknowledge-loss-of-protection"] {
        eprintln!("Explicit --acknowledge-loss-of-protection required; disables automated exits.");
        std::process::exit(2);
    }
    // SCM RPC, including ControlService on a suspended host, may block.
    // A separate process deadline bounds the caller even when an RPC hangs.
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(contain());
    });
    match rx.recv_timeout(std::time::Duration::from_secs(10)) {
        Ok(Ok(())) => println!(
            "CONFIRMED UNPROTECTED: executor disabled and process exited; reconcile manually."
        ),
        result => {
            eprintln!("HARD STOP NOT CONFIRMED: {result:?}; inspect SCM locally.");
            std::process::exit(2);
        }
    }
}
#[cfg(windows)]
fn contain() -> Result<(), String> {
    use std::{
        ptr,
        time::{Duration, Instant},
    };
    use windows_service::service::{
        ServiceAction, ServiceActionType, ServiceFailureActions, ServiceFailureResetPeriod,
        ServiceStartType, ServiceState,
    };
    use windows_sys::Win32::{
        Foundation::CloseHandle,
        Security::{GetTokenInformation, TokenElevation, TOKEN_ELEVATION, TOKEN_QUERY},
        System::{
            Services::{ChangeServiceConfigW, SERVICE_DISABLED, SERVICE_NO_CHANGE},
            Threading::{GetCurrentProcess, OpenProcessToken, TerminateProcess},
        },
    };
    let mut token = ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        return Err("cannot query elevated token".into());
    }
    let mut elevation = TOKEN_ELEVATION { TokenIsElevated: 0 };
    let mut size = 0;
    let ok = unsafe {
        GetTokenInformation(
            token,
            TokenElevation,
            (&mut elevation as *mut TOKEN_ELEVATION).cast(),
            std::mem::size_of::<TOKEN_ELEVATION>() as u32,
            &mut size,
        )
    };
    unsafe {
        CloseHandle(token);
    }
    if ok == 0 || elevation.TokenIsElevated == 0 {
        return Err("actual elevated OS token required".into());
    }
    let pinned = windows_control::pin()?;
    pinned
        .service
        .update_failure_actions(ServiceFailureActions {
            reset_period: ServiceFailureResetPeriod::Never,
            reboot_msg: Some("".into()),
            command: Some("".into()),
            actions: Some(vec![ServiceAction {
                action_type: ServiceActionType::None,
                delay: Duration::ZERO,
            }]),
        })
        .map_err(|e| e.to_string())?;
    pinned
        .service
        .set_failure_actions_on_non_crash_failures(false)
        .map_err(|e| e.to_string())?;
    let changed = unsafe {
        ChangeServiceConfigW(
            pinned.service.raw_handle(),
            SERVICE_NO_CHANGE,
            SERVICE_DISABLED,
            SERVICE_NO_CHANGE,
            ptr::null(),
            ptr::null(),
            ptr::null_mut(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
        )
    };
    if changed == 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    let actions = pinned
        .service
        .get_failure_actions()
        .map_err(|e| e.to_string())?;
    if pinned
        .service
        .query_config()
        .map_err(|e| e.to_string())?
        .start_type
        != ServiceStartType::Disabled
        || !actions.actions.is_some_and(|a| {
            !a.is_empty() && a.iter().all(|a| a.action_type == ServiceActionType::None)
        })
    {
        return Err("restart policy not disabled".into());
    }
    pinned.verify()?;
    // Never wait on ControlService itself: it can block for tens of seconds.
    std::thread::spawn(|| {
        if let Ok(service) = windows_control::service(true) {
            let _ = service.stop();
        }
    });
    if !pinned.exited(Duration::from_millis(1000)) {
        // The retained handle pins image and creation identity even if SCM changes.
        if unsafe { TerminateProcess(pinned.process, 1) } == 0 && !pinned.exited(Duration::ZERO) {
            return Err(std::io::Error::last_os_error().to_string());
        }
        if !pinned.exited(Duration::from_secs(3)) {
            return Err("process exit not proven".into());
        }
    }
    let until = Instant::now() + Duration::from_secs(2);
    loop {
        let status = pinned.service.query_status().map_err(|e| e.to_string())?;
        if status.current_state == ServiceState::Stopped && status.process_id.unwrap_or(0) == 0 {
            break;
        }
        if Instant::now() >= until {
            return Err("SCM stopped state not proven".into());
        }
        std::thread::sleep(Duration::from_millis(25));
    }
    if pinned
        .service
        .query_config()
        .map_err(|e| e.to_string())?
        .start_type
        != ServiceStartType::Disabled
    {
        return Err("service re-enabled during containment".into());
    }
    Ok(())
}
