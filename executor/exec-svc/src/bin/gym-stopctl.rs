//! Local stop-only Windows client, with correlated acknowledgment and deadline.
#[cfg(not(windows))]
fn main() {
    eprintln!("gym-stopctl requires Windows");
    std::process::exit(2);
}
#[cfg(windows)]
fn main() {
    if let Err(message) = client::run() {
        eprintln!("UNACKNOWLEDGED: {message}. Verify protection manually.");
        std::process::exit(2);
    }
}
#[cfg(windows)]
mod client {
    use exec_ipc::{StopCommand, StopReply, StopRequest, StopResult, FRAME_SIZE};
    use std::fs::File;
    use std::io::{Read, Write};
    use std::os::windows::io::FromRawHandle;
    use std::ptr;
    use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
    use windows_sys::Win32::Storage::FileSystem::CreateFileW;
    use std::sync::mpsc;
    use std::thread;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    const PIPE: &str = r"\\.\pipe\TradingGYM.Stop.v1";

    fn correlation() -> [u8; 16] {
        let nanos = SystemTime::now().duration_since(UNIX_EPOCH)
            .map(|t| t.as_nanos()).unwrap_or(0);
        (nanos ^ ((u128::from(std::process::id())) << 64)).to_be_bytes()
    }

    fn exchange(request: StopRequest, budget: Duration) -> Result<StopReply, String> {
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let result = (|| -> Result<StopReply, String> {
                let frame = request.encode().map_err(|_| "invalid stop frame".to_owned())?;
                let wide: Vec<u16> = PIPE.encode_utf16().chain(std::iter::once(0)).collect();
                // Ask only for READ_DATA | WRITE_DATA | SYNCHRONIZE. Generic
                // WRITE also requests FILE_APPEND_DATA (0x4), which on named
                // pipes grants FILE_CREATE_PIPE_INSTANCE and must be denied.
                let raw = unsafe {
                    CreateFileW(
                        wide.as_ptr(), 0x00100003, 0, ptr::null(), 3, 0, ptr::null_mut(),
                    )
                };
                if raw == INVALID_HANDLE_VALUE {
                    // Precise native error is needed to distinguish DACL denial
                    // from pipe absence, busy instances, or name mismatch.
                    let error = std::io::Error::last_os_error();
                    return Err(format!(
                        "stop pipe open failed (Win32={}): {}",
                        error.raw_os_error().unwrap_or(-1), error
                    ));
                }
                let mut pipe = unsafe { File::from_raw_handle(raw.cast()) };
                pipe.write_all(&frame).map_err(|_| "stop request not delivered".to_owned())?;
                let mut response = [0u8; FRAME_SIZE];
                pipe.read_exact(&mut response).map_err(|_| "missing stop acknowledgment".to_owned())?;
                StopReply::decode(&response).map_err(|_| "malformed stop acknowledgment".to_owned())
            })();
            let _ = tx.send(result);
        });
        rx.recv_timeout(budget)
            .map_err(|_| "stop response timed out".to_owned())?
    }

    pub fn run() -> Result<(), String> {
        let mut args = std::env::args().skip(1);
        let command = match args.next().as_deref() {
            Some("status") => StopCommand::Status,
            Some("pause") => StopCommand::PauseEntries,
            Some("exit-only") => StopCommand::ExitOnly,
            Some("halt") => StopCommand::Halt,
            _ => return Err("expected status|pause|exit-only|halt".to_owned()),
        };
        if args.next().is_some() { return Err("unexpected argument".to_owned()); }
        let started = Instant::now();
        // STATUS may answer StaleRuntime with the current epoch; this is
        // discovery, never a successful stop acknowledgment.
        let initial = StopRequest {
            command: StopCommand::Status, runtime_epoch: 1, correlation: correlation(),
        };
        let status = exchange(initial, Duration::from_millis(900))?;
        if status.correlation != initial.correlation
            || status.runtime_epoch == 0
            || !matches!(status.result, StopResult::Ack | StopResult::StaleRuntime)
        {
            return Err("untrusted runtime status".to_owned());
        }
        let remaining = Duration::from_millis(900).saturating_sub(started.elapsed());
        if remaining.is_zero() { return Err("stop budget expired".to_owned()); }
        let request = StopRequest {
            command, runtime_epoch: status.runtime_epoch, correlation: correlation(),
        };
        let reply = exchange(request, remaining)?;
        if !reply.confirms(request) {
            return Err("stop request not acknowledged".to_owned());
        }
        println!("ACKNOWLEDGED: {:?} runtime={} mode={:?}",
            command, reply.runtime_epoch, reply.mode);
        Ok(())
    }
}
