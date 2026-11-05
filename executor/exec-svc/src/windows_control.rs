use std::{
    io,
    os::windows::io::{AsRawHandle, BorrowedHandle},
    time::Duration,
};
use windows_service::{
    service::{Service, ServiceAccess, ServiceState, ServiceType},
    service_manager::{ServiceManager, ServiceManagerAccess},
};
use windows_sys::Win32::{
    Foundation::{CloseHandle, FILETIME, HANDLE},
    System::{
        Pipes::GetNamedPipeServerProcessId,
        Threading::{
            GetProcessTimes, OpenProcess, QueryFullProcessImageNameW, WaitForSingleObject,
            PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE,
        },
    },
};

pub struct Pinned {
    pub service: Service,
    pub process: HANDLE,
    pub pid: u32,
    pub created: u64,
}
impl Drop for Pinned {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.process);
        }
    }
}
fn error() -> String {
    io::Error::last_os_error().to_string()
}

pub fn service(change: bool) -> Result<Service, String> {
    let manager = ServiceManager::local_computer(None::<&str>, ServiceManagerAccess::CONNECT)
        .map_err(|e| e.to_string())?;
    let access = ServiceAccess::QUERY_STATUS | ServiceAccess::QUERY_CONFIG;
    manager
        .open_service(
            "TradingGYMExecutor",
            if change {
                access | ServiceAccess::CHANGE_CONFIG | ServiceAccess::STOP
            } else {
                access
            },
        )
        .map_err(|e| e.to_string())
}

fn same_identity(expected: u32, observed: u32, running: bool) -> bool {
    expected != 0 && expected == observed && running
}

pub fn pin() -> Result<Pinned, String> {
    pin_with_access(true)
}
pub fn pin_readonly() -> Result<Pinned, String> {
    pin_with_access(false)
}
fn pin_with_access(change: bool) -> Result<Pinned, String> {
    let service = service(change)?;
    let config = service.query_config().map_err(|e| e.to_string())?;
    let expected = std::env::var_os("ProgramFiles").ok_or("missing ProgramFiles")?;
    let expected = std::path::PathBuf::from(expected)
        .join("TradingGYM")
        .join("Executor")
        .join("gym-executor.exe");
    let configured = config.executable_path.to_string_lossy();
    if config.service_type != ServiceType::OWN_PROCESS
        || !configured
            .trim_matches('"')
            .eq_ignore_ascii_case(&expected.to_string_lossy())
        || !config.account_name.as_ref().is_some_and(|s| {
            s.to_string_lossy()
                .eq_ignore_ascii_case("NT AUTHORITY\\LocalService")
        })
    {
        return Err("fixed SCM service identity/path mismatch".into());
    }
    let status = service.query_status().map_err(|e| e.to_string())?;
    let pid = status.process_id.ok_or("service has no process")?;
    if !same_identity(pid, pid, status.current_state != ServiceState::Stopped) {
        return Err("executor is not running".into());
    }
    // Keep this exact kernel process object alive; never terminate by recycled PID.
    let process = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION
                | 0x00100000
                | if change { PROCESS_TERMINATE } else { 0 },
            0,
            pid,
        )
    };
    if process.is_null() {
        return Err(error());
    }
    let mut pinned = Pinned {
        service,
        process,
        pid,
        created: 0,
    };
    let mut image = vec![0u16; 32768];
    let mut length = image.len() as u32;
    if unsafe { QueryFullProcessImageNameW(process, 0, image.as_mut_ptr(), &mut length) } == 0 {
        return Err(error());
    }
    let image =
        String::from_utf16(&image[..length as usize]).map_err(|_| "invalid process image")?;
    if !image.eq_ignore_ascii_case(&expected.to_string_lossy()) {
        return Err("process image mismatch".into());
    }
    pinned.created = creation(process)?;
    pinned.verify()?;
    Ok(pinned)
}
fn creation(process: HANDLE) -> Result<u64, String> {
    let mut times = [FILETIME {
        dwLowDateTime: 0,
        dwHighDateTime: 0,
    }; 4];
    let [a, b, c, d] = &mut times;
    if unsafe { GetProcessTimes(process, a, b, c, d) } == 0 {
        return Err(error());
    }
    Ok((u64::from(a.dwHighDateTime) << 32) | u64::from(a.dwLowDateTime))
}
impl Pinned {
    pub fn verify(&self) -> Result<(), String> {
        let status = self.service.query_status().map_err(|e| e.to_string())?;
        if !same_identity(
            self.pid,
            status.process_id.unwrap_or(0),
            status.current_state != ServiceState::Stopped,
        ) || self.exited(Duration::ZERO)
            || creation(self.process)? != self.created
        {
            return Err("executor process identity changed or exited".into());
        }
        Ok(())
    }
    pub fn exited(&self, budget: Duration) -> bool {
        unsafe { WaitForSingleObject(self.process, budget.as_millis() as u32) == 0 }
    }
}
pub fn authenticate_pipe(pipe: BorrowedHandle<'_>, expected_pid: u32) -> Result<(), String> {
    let service = service(false)?;
    let before = service.query_status().map_err(|e| e.to_string())?;
    let mut pid = 0;
    // SAFETY: the borrowed handle remains open through the kernel identity query.
    if unsafe { GetNamedPipeServerProcessId(pipe.as_raw_handle(), &mut pid) } == 0 {
        return Err(error());
    }
    let after = service.query_status().map_err(|e| e.to_string())?;
    if !same_identity(expected_pid, pid, true)
        || !same_identity(
            expected_pid,
            before.process_id.unwrap_or(0),
            before.current_state == ServiceState::Running,
        )
        || !same_identity(
            expected_pid,
            after.process_id.unwrap_or(0),
            after.current_state == ServiceState::Running,
        )
    {
        return Err("stop pipe server is not pinned SCM executor".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_missing_replaced_or_stopped_identity() {
        assert!(same_identity(42, 42, true));
        assert!(!same_identity(42, 43, true));
        assert!(!same_identity(0, 0, true));
        assert!(!same_identity(42, 42, false));
    }
}
