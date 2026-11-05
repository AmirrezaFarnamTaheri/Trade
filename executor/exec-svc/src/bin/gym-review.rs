//! Fixed authenticated operator channel. Input/output are bounded native frames.
#[cfg(not(windows))]
fn main() {
    eprintln!("gym-review requires Windows");
    std::process::exit(2);
}
#[cfg(windows)]
fn main() {
    if std::env::args_os().len() != 1 {
        eprintln!("gym-review accepts only a bounded request on stdin");
        std::process::exit(2);
    }
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(exchange());
    });
    match rx.recv_timeout(std::time::Duration::from_secs(5)) {
        Ok(Ok(raw)) => {
            use std::io::Write;
            let stdout = std::io::stdout();
            let mut out = std::io::BufWriter::new(stdout.lock());
            let result = (|| -> std::io::Result<()> {
                write!(out,"{{\"source\":\"EXECUTOR_SERVICE_REVIEW\",\"funded_authority\":false,\"order_submitted\":false,\"raw_reply_hex\":\"")?;
                for byte in raw {
                    write!(out, "{byte:02x}")?;
                }
                writeln!(out, "\"}}")?;
                out.flush()
            })();
            if result.is_err() {
                std::process::exit(2);
            }
        }
        _ => {
            eprintln!("UNACKNOWLEDGED: review may have committed. Inspect the same client identity before any manual retry. No order was submitted by this helper.");
            std::process::exit(2);
        }
    }
}
#[cfg(windows)]
fn exchange() -> Result<Vec<u8>, ()> {
    use exec_ipc::review::*;
    use exec_svc::windows_control;
    use std::{
        fs::File,
        io::{Read, Write},
        os::windows::io::{AsHandle, FromRawHandle},
        ptr,
    };
    use windows_sys::Win32::{Foundation::INVALID_HANDLE_VALUE, Storage::FileSystem::*};
    let mut input = Vec::new();
    std::io::stdin()
        .take(REQUEST_SIZE as u64 + 1)
        .read_to_end(&mut input)
        .map_err(|_| ())?;
    let request = Request::decode(&input).map_err(|_| ())?;
    let pinned = windows_control::pin_readonly().map_err(|_| ())?;
    let name: Vec<u16> = PIPE.encode_utf16().chain(Some(0)).collect();
    let raw = unsafe {
        CreateFileW(
            name.as_ptr(),
            0x00100003,
            0,
            ptr::null(),
            OPEN_EXISTING,
            SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION,
            ptr::null_mut(),
        )
    };
    if raw == INVALID_HANDLE_VALUE {
        return Err(());
    }
    let mut pipe = unsafe { File::from_raw_handle(raw) };
    pinned.verify().map_err(|_| ())?;
    windows_control::authenticate_pipe(pipe.as_handle(), pinned.pid).map_err(|_| ())?;
    pipe.write_all(&input).map_err(|_| ())?;
    let mut raw = vec![0; REPLY_SIZE];
    pipe.read_exact(&mut raw).map_err(|_| ())?;
    let reply = Reply::decode(&raw, request.correlation).map_err(|_| ())?;
    reply.validate_for(&request).map_err(|_| ())?;
    pinned.verify().map_err(|_| ())?;
    windows_control::authenticate_pipe(pipe.as_handle(), pinned.pid).map_err(|_| ())?;
    Ok(raw)
}
