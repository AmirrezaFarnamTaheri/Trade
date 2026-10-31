//! Windows-only stop pipe listener. No default ACL and no remote clients.
//! Installation, restricted service identity and token/ACL self-tests are still
//! prerequisites to deployment. Call from a dedicated runtime/thread.
use crate::StopGate;
use exec_ipc::FRAME_SIZE;
use std::ffi::c_void;
use std::io;
use std::ptr;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::windows::named_pipe::{NamedPipeServer, PipeMode, ServerOptions};
use tokio::sync::Semaphore;
use tokio::time::timeout;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::{PSECURITY_DESCRIPTOR, SECURITY_ATTRIBUTES};

pub const STOP_PIPE_NAME: &str = r"\\.\pipe\TradingGYM.Stop.v1";
const CLIENT_DEADLINE: Duration = Duration::from_millis(750);

fn valid_sid_parts(sid: &str) -> bool {
    sid.starts_with("S-1-5-") && sid.split('-').skip(1).all(|v| !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit()))
}

/// Only explicitly provisioned service and operator logon SIDs are allowed.
/// An operator ACE intentionally omits FILE_CREATE_PIPE_INSTANCE (0x4) and
/// WRITE_DAC. Generic write is unsafe here because it includes pipe creation.
pub fn stop_pipe_sddl(service_sid: &str, logon_sid: &str) -> io::Result<String> {
    if !valid_sid_parts(service_sid) || !service_sid.starts_with("S-1-5-80-")
        || !valid_sid_parts(logon_sid) || !logon_sid.starts_with("S-1-5-5-")
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "expected service SID and logon SID"));
    }
    Ok(format!(
        "D:P(A;;GA;;;SY)(A;;GA;;;{service_sid})(A;;0x00100003;;;{logon_sid})"
    ))
}

struct Descriptor(PSECURITY_DESCRIPTOR);
impl Drop for Descriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: the descriptor is returned by ConvertStringSecurityDescriptor...
            // and Windows requires exactly LocalFree to release it.
            unsafe { LocalFree(self.0.cast()) };
        }
    }
}

fn create_pipe(service_sid: &str, logon_sid: &str, first: bool) -> io::Result<NamedPipeServer> {
    let sddl = stop_pipe_sddl(service_sid, logon_sid)?;
    let wide: Vec<u16> = sddl.encode_utf16().chain(std::iter::once(0)).collect();
    let mut raw: PSECURITY_DESCRIPTOR = ptr::null_mut();
    // SAFETY: wide is NUL-terminated and raw is a valid out-parameter.
    let ok = unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(wide.as_ptr(), 1, &mut raw, ptr::null_mut())
    };
    if ok == 0 {
        return Err(io::Error::last_os_error());
    }
    let descriptor = Descriptor(raw);
    let mut attrs = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor.0,
        bInheritHandle: 0,
    };
    let mut options = ServerOptions::new();
    options
        .pipe_mode(PipeMode::Message)
        .reject_remote_clients(true)
        .first_pipe_instance(first)
        .max_instances(64)
        .in_buffer_size(128)
        .out_buffer_size(128);
    // SAFETY: attrs and descriptor remain valid until CreateNamedPipeW returns.
    // Never use ServerOptions::create() because its default DACL is too broad.
    unsafe {
        options.create_with_security_attributes_raw(
            STOP_PIPE_NAME,
            (&mut attrs as *mut SECURITY_ATTRIBUTES).cast::<c_void>(),
        )
    }
}

async fn handle_client(mut client: NamedPipeServer, gate: Arc<StopGate>) -> io::Result<()> {
    let mut buf = [0_u8; FRAME_SIZE + 1];
    let received = timeout(CLIENT_DEADLINE, client.read(&mut buf))
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "stop request read timeout"))??;
    if received != FRAME_SIZE {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid stop message size"));
    }
    let reply = gate
        .process_frame(&buf[..received])
        .map_err(|err| io::Error::new(io::ErrorKind::InvalidData, err))?;
    timeout(CLIENT_DEADLINE, client.write_all(&reply))
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "stop acknowledgment timeout"))??;
    Ok(())
}

/// Call on a dedicated thread/runtime, independently of future proposal or
/// reconciliation loops. Requires verified SIDs from privileged setup.
pub async fn serve_stop_only(
    gate: Arc<StopGate>,
    service_sid: &str,
    logon_sid: &str,
    ready: Option<std::sync::mpsc::Sender<()>>,
) -> io::Result<()> {
    let mut listening = create_pipe(service_sid, logon_sid, true)?;
    // SCM RUNNING may only follow successful secure instance creation.
    if let Some(ready) = ready { let _ = ready.send(()); }
    let slots = Arc::new(Semaphore::new(16));
    loop {
        let connect_result = listening.connect().await;
        // Retain the first instance until a replacement is available; do
        // not tear down the emergency channel after a local client abort.
        let replacement = loop {
            match create_pipe(service_sid, logon_sid, false) {
                Ok(pipe) => break pipe,
                Err(_) => tokio::time::sleep(Duration::from_millis(50)).await,
            }
        };
        let connected = std::mem::replace(&mut listening, replacement);
        if connect_result.is_err() {
            // Windows ERROR_NO_DATA (232) can occur after client disconnect.
            // This is not a reason to terminate the stop-only listener.
            continue;
        }
        if let Ok(slot) = slots.clone().try_acquire_owned() {
            let state = gate.clone();
            tokio::spawn(async move {
                let _slot = slot;
                let _ = handle_client(connected, state).await;
            });
        }
        // At capacity, drop the connection; never queue unbounded requests.
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strictly_scoped_sddl_has_no_default_everyone_or_pipe_create_ace() {
        let value = stop_pipe_sddl(
            "S-1-5-80-123-456-789-111-222",
            "S-1-5-5-100-200",
        ).unwrap();
        assert!(!value.contains("(D;;GA;;;NU)"));
        assert!(value.contains("D:P(A;;GA;;;SY)"));
        assert!(value.contains("(A;;0x00100003;;;S-1-5-5-100-200)"));
        assert!(!value.contains(";;;WD"));
        assert!(!value.contains(";;;AU"));
        assert!(stop_pipe_sddl("S-1-5-18", "S-1-5-5-100-200").is_err());
        assert!(stop_pipe_sddl("S-1-5-80-1", "S-1-5-21-1").is_err());
        assert!(stop_pipe_sddl("S-1-5-80-1) (A;;GA;;;WD", "S-1-5-5-100-200").is_err());
    }
}
