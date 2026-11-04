#[cfg(not(windows))]
fn main() {
    eprintln!("gym-account-read requires Windows");
    std::process::exit(2);
}
#[cfg(windows)]
use exec_svc::windows_control;
#[cfg(windows)]
fn main() {
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(run());
    });
    match rx.recv_timeout(std::time::Duration::from_secs(20)) {
        Ok(Ok(body)) => {
            // Hex preserves unknown/incomplete venue bytes without treating them as trusted JSON or terminal text.
            use std::io::Write;
            let stdout = std::io::stdout();
            let mut out = std::io::BufWriter::new(stdout.lock());
            let result = (|| -> std::io::Result<()> {
                write!(out, "{{\"source\":\"EXECUTOR_SERVICE_WINHTTP\",\"state\":\"RAW_UNPARSED\",\"permission_status\":\"UNVERIFIED\",\"funded_authority\":false,\"raw_body_hex\":\"")?;
                for byte in body {
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
            eprintln!("NOT_VERIFIED: account observation unavailable; no authority granted");
            std::process::exit(2);
        }
    }
}
#[cfg(windows)]
fn run() -> Result<Vec<u8>, ()> {
    use exec_ipc::provision::*;
    use std::{
        fs::File,
        io::{Read, Write},
        os::windows::{
            ffi::OsStrExt,
            io::{AsHandle, FromRawHandle},
        },
        ptr,
    };
    use windows_sys::Win32::{
        Foundation::INVALID_HANDLE_VALUE, Security::Cryptography::*, Storage::FileSystem::*,
    };
    let args: Vec<String> = std::env::args().skip(1).collect();
    let resource = match args.as_slice() {
        [kind] if kind == "balances" => AccountResource::Balances,
        [kind] if kind == "fees" => AccountResource::Fees,
        [kind, id] if kind == "known-client-order" => AccountResource::KnownClientOrder(id.clone()),
        _ => return Err(()),
    };
    resource.path().map_err(|_| ())?;
    let pinned = windows_control::pin().map_err(|_| ())?;
    let wide: Vec<_> = std::ffi::OsStr::new(PIPE)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let raw = unsafe {
        CreateFileW(
            wide.as_ptr(),
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
    let mut correlation = [0; 16];
    if unsafe {
        BCryptGenRandom(
            ptr::null_mut(),
            correlation.as_mut_ptr(),
            16,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    } != 0
    {
        return Err(());
    }
    pipe.write_all(&resource.encode(correlation).map_err(|_| ())?)
        .map_err(|_| ())?;
    let mut reply = [0; ACCOUNT_REPLY_SIZE];
    pipe.read_exact(&mut reply).map_err(|_| ())?;
    let len = parse_account_reply(&reply, correlation).map_err(|_| ())?;
    let mut body = vec![0; len];
    pipe.read_exact(&mut body).map_err(|_| ())?;
    pinned.verify().map_err(|_| ())?;
    windows_control::authenticate_pipe(pipe.as_handle(), pinned.pid).map_err(|_| ())?;
    Ok(body)
}
