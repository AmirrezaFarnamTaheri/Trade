//! Fixed administrator-only ceiling control. Never arms a session or contacts a venue.
#[cfg(not(windows))]
fn main() {
    eprintln!("gym-ceiling requires Windows");
    std::process::exit(2);
}

#[cfg(windows)]
fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let command = match command(&args) {
        Ok(command) => command,
        Err(()) => {
            eprintln!("Usage: gym-ceiling get | set CURRENCY UNIT_EPOCH DECIMALS AMOUNT EXPECTED_SEQUENCE\nAmounts are exact. A recorded ceiling does not enable funded trading.");
            std::process::exit(2);
        }
    };
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(exchange(command));
    });
    match rx.recv_timeout(std::time::Duration::from_secs(5)) {
        Ok(Ok(reply)) => {
            match reply.ceiling {
                Some(value) => println!("{{\"source\":\"EXECUTOR_SERVICE\",\"state\":\"RECORDED\",\"sequence\":{},\"ceiling\":{{\"currency\":\"{}\",\"unit_epoch\":{},\"decimals\":{},\"amount\":\"{}\",\"capital_quanta\":\"{}\"}},\"ceiling_protection\":\"UNQUALIFIED\",\"funded_authority\":false}}", reply.sequence, value.currency, value.unit_epoch, value.decimals, value.amount().expect("validated ceiling reply"), value.capital_quanta),
                None => println!("{{\"source\":\"EXECUTOR_SERVICE\",\"state\":\"UNSET\",\"sequence\":0,\"ceiling\":null,\"ceiling_protection\":\"UNQUALIFIED\",\"funded_authority\":false}}"),
            }
        }
        _ => {
            eprintln!("UNACKNOWLEDGED: a requested ceiling change may have committed. Read status before any manual retry. No funded authority granted.");
            std::process::exit(2);
        }
    }
}

#[cfg(windows)]
fn command(args: &[String]) -> Result<exec_ipc::ceiling::CeilingCommand, ()> {
    use exec_ipc::ceiling::{Ceiling, CeilingCommand};
    match args {
        [action] if action == "get" => Ok(CeilingCommand::Get),
        [action, currency, epoch, decimals, amount, sequence] if action == "set" => {
            Ok(CeilingCommand::Set {
                expected_sequence: sequence.parse().map_err(|_| ())?,
                ceiling: Ceiling::from_amount(
                    currency,
                    epoch.parse().map_err(|_| ())?,
                    decimals.parse().map_err(|_| ())?,
                    amount,
                )
                .map_err(|_| ())?,
            })
        }
        _ => Err(()),
    }
}

#[cfg(windows)]
fn exchange(
    command: exec_ipc::ceiling::CeilingCommand,
) -> Result<exec_ipc::ceiling::CeilingReply, ()> {
    use exec_ipc::ceiling::{CeilingReply, CeilingRequest, SIZE};
    use exec_svc::windows_control;
    use std::{
        fs::File,
        io::{Read, Write},
        os::windows::io::{AsHandle, FromRawHandle},
        ptr,
    };
    use windows_sys::Win32::{
        Foundation::INVALID_HANDLE_VALUE, Security::Cryptography::*, Storage::FileSystem::*,
    };
    let pinned = windows_control::pin().map_err(|_| ())?;
    let name: Vec<u16> = exec_ipc::provision::PIPE
        .encode_utf16()
        .chain(Some(0))
        .collect();
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
    let request = CeilingRequest {
        command,
        correlation,
    };
    pipe.write_all(&request.encode().map_err(|_| ())?)
        .map_err(|_| ())?;
    let mut raw = [0; SIZE];
    pipe.read_exact(&mut raw).map_err(|_| ())?;
    pinned.verify().map_err(|_| ())?;
    windows_control::authenticate_pipe(pipe.as_handle(), pinned.pid).map_err(|_| ())?;
    let reply = CeilingReply::decode(&raw, correlation).map_err(|_| ())?;
    if let exec_ipc::ceiling::CeilingCommand::Set {
        expected_sequence,
        ceiling,
    } = request.command
    {
        if reply.sequence <= expected_sequence || reply.ceiling.as_ref() != Some(&ceiling) {
            return Err(());
        }
    }
    Ok(reply)
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    #[test]
    fn cli_does_not_accept_implicit_amount_scale_or_overwrite_version() {
        let args = |values: &[&str]| values.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert!(command(&args(&["get"])).is_ok());
        assert!(command(&args(&["set", "USDT", "1", "6", "0", "0"])).is_ok());
        for values in [
            vec!["set", "USDT", "6", "1"],
            vec!["set", "USDT", "1", "6", "1e3", "0"],
            vec!["set", "USDT", "1", "20", "1", "0"],
            vec!["set", "USDT", "1", "6", "1", "-1"],
            vec!["set", "USDT", "0", "6", "1", "0"],
        ] {
            assert!(command(&args(&values)).is_err());
        }
    }
}
