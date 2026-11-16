//! Elevated owner control. Inspect first; approval requires an interactive review of both exact file hashes.
#[cfg(windows)]
mod windows {
    use exec_ipc::arm::{ArmCommand, ArmReply, ArmRequest, ArmResult};
    use sha2::{Digest, Sha256};
    use std::{
        io,
        path::{Path, PathBuf},
    };

    fn hex(raw: &[u8]) -> String {
        raw.iter().map(|byte| format!("{byte:02x}")).collect()
    }
    fn digest(text: &str) -> Result<[u8; 32], &'static str> {
        if text.len() != 64 || !text.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err("expected SHA-256 hex");
        }
        let mut out = [0; 32];
        for (index, byte) in out.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&text[2 * index..2 * index + 2], 16)
                .map_err(|_| "invalid SHA-256")?;
        }
        if out == [0; 32] {
            return Err("zero SHA-256 refused");
        }
        Ok(out)
    }

    enum Command {
        Inspect(PathBuf),
        Status,
        Disarm,
        Approve(PathBuf, [u8; 32], [u8; 32]),
    }
    fn command(args: &[String]) -> Result<Command, &'static str> {
        match args {
        [action] if action == "status" => Ok(Command::Status),
        [action] if action == "disarm" => Ok(Command::Disarm),
        [action, path] if action == "inspect" => Ok(Command::Inspect(PathBuf::from(path))),
        [action, path, policy, evidence] if action == "approve" => Ok(Command::Approve(PathBuf::from(path), digest(policy)?, digest(evidence)?)),
        _ => Err("Usage: gym-arm inspect ABSOLUTE_ARM_POLICY_PATH | status | disarm | approve ABSOLUTE_ARM_POLICY_PATH POLICY_SHA256 EVIDENCE_SHA256"),
    }
    }

    fn bounded_json(path: &Path, maximum: u64) -> io::Result<(Vec<u8>, serde_json::Value)> {
        use std::io::Read;
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > maximum {
            return Err(io::Error::other("invalid owner evidence file"));
        }
        let mut raw = Vec::new();
        std::fs::File::open(path)?
            .take(maximum + 1)
            .read_to_end(&mut raw)?;
        if raw.is_empty() || raw.len() as u64 > maximum {
            return Err(io::Error::other("owner evidence bounds"));
        }
        let json =
            serde_json::from_slice(&raw).map_err(|_| io::Error::other("invalid owner JSON"))?;
        Ok((raw, json))
    }

    fn inspect(path: &Path) -> io::Result<([u8; 32], [u8; 32])> {
        let (raw, policy) = bounded_json(path, 8192)?;
        let policy_sha256: [u8; 32] = Sha256::digest(&raw).into();
        exec_svc::arm_control::PolicyFile::open(path, policy_sha256)?;
        let (raw, evidence) = bounded_json(&path.with_file_name("arm-evidence.json"), 16384)?;
        let evidence_sha256: [u8; 32] = Sha256::digest(&raw).into();
        for (name, value) in [("OWNER_POLICY", policy), ("OWNER_ATTESTATIONS", evidence)] {
            let text = serde_json::to_string_pretty(&value).map_err(io::Error::other)?;
            let safe: String = text
                .chars()
                .flat_map(|ch| {
                    if ch.is_ascii() {
                        ch.to_string().chars().collect::<Vec<_>>()
                    } else {
                        ch.escape_unicode().collect()
                    }
                })
                .collect();
            println!("{name}:\n{safe}");
        }
        println!(
            "POLICY_SHA256={}\nEVIDENCE_SHA256={}",
            hex(&policy_sha256),
            hex(&evidence_sha256)
        );
        println!("Review the trade/no-withdraw claim, runtime and credential binding, prospective checkpoint, and referenced artifact path/hash above. Native service measurements and the registered checkpoint date must also pass.");
        Ok((policy_sha256, evidence_sha256))
    }

    #[cfg(windows)]
    pub(super) fn main() {
        let result = command(&std::env::args().skip(1).collect::<Vec<_>>())
            .map_err(io::Error::other)
            .and_then(run);
        if let Err(error) = result {
            eprintln!("{error}\nUNACKNOWLEDGED: inspect current service status before any retry. No automatic approval or retry is performed.");
            std::process::exit(2);
        }
    }

    #[cfg(windows)]
    fn run(command: Command) -> io::Result<()> {
        use std::io::{BufRead, IsTerminal, Read};
        let command = match command {
            Command::Inspect(path) => {
                inspect(&path)?;
                return Ok(());
            }
            Command::Status => ArmCommand::Status,
            Command::Disarm => {
                let status = bounded_exchange(ArmCommand::Status)?;
                ArmCommand::Disarm {
                    runtime_epoch: status.runtime_epoch,
                }
            }
            Command::Approve(path, policy_sha256, evidence_sha256) => {
                let status = bounded_exchange(ArmCommand::Status)?;
                if inspect(&path)? != (policy_sha256, evidence_sha256) {
                    return Err(io::Error::other("owner-reviewed file hash changed"));
                }
                if !std::io::stdin().is_terminal() {
                    return Err(io::Error::other(
                        "interactive elevated owner review required",
                    ));
                }
                let phrase = format!(
                    "APPROVE {} {}",
                    &hex(&policy_sha256)[..12],
                    &hex(&evidence_sha256)[..12]
                );
                eprintln!("Type {phrase} to approve exactly these owner claims and limits:");
                let mut answer = String::new();
                std::io::stdin().lock().take(128).read_line(&mut answer)?;
                if answer.trim() != phrase {
                    return Err(io::Error::other("owner approval cancelled"));
                }
                ArmCommand::Approve {
                    runtime_epoch: status.runtime_epoch,
                    revision: status.revision,
                    policy_sha256,
                    evidence_sha256,
                    policy_path: path
                        .to_str()
                        .ok_or_else(|| io::Error::other("invalid policy path"))?
                        .into(),
                }
            }
        };
        let reply = bounded_exchange(command.clone())?;
        match command {
            ArmCommand::Approve {
                runtime_epoch,
                revision,
                policy_sha256,
                ..
            } => {
                if reply.result != ArmResult::Approved
                    || reply.runtime_epoch != runtime_epoch
                    || reply.revision <= revision
                    || reply.policy_sha256 != policy_sha256
                {
                    return Err(io::Error::other(format!(
                        "arm refused; native blocker mask={:#x}, mode={:?}",
                        reply.blockers, reply.mode
                    )));
                }
            }
            ArmCommand::Disarm { runtime_epoch } => {
                if reply.result != ArmResult::Disarmed
                    || reply.runtime_epoch != runtime_epoch
                    || reply.mode == exec_ipc::StopMode::Armed
                {
                    return Err(io::Error::other("disarm not acknowledged"));
                }
            }
            ArmCommand::Status => {}
        }
        println!("ACKNOWLEDGED mode={:?} runtime={} revision={} blockers={:#x} policy_sha256={} record_digest={} expires_at_ms={}", reply.mode, reply.runtime_epoch, reply.revision, reply.blockers, hex(&reply.policy_sha256), hex(&reply.record_digest), reply.expires_at_ms);
        Ok(())
    }

    #[cfg(windows)]
    fn bounded_exchange(command: ArmCommand) -> io::Result<ArmReply> {
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            if tx.send(exchange(command)).is_err() { /* caller timed out */ }
        });
        rx.recv_timeout(std::time::Duration::from_secs(5))
            .map_err(|_| io::Error::other("privileged arm control timed out"))?
    }

    #[cfg(windows)]
    fn exchange(command: ArmCommand) -> io::Result<ArmReply> {
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
        let pinned = windows_control::pin_readonly().map_err(io::Error::other)?;
        let name: Vec<u16> = exec_ipc::provision::PIPE
            .encode_utf16()
            .chain(Some(0))
            .collect();
        // SAFETY: fixed NUL-terminated pipe name, no inherited handles; successful handle is owned below.
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
            return Err(io::Error::last_os_error());
        }
        // SAFETY: CreateFileW returned a new valid owned handle.
        let mut pipe = unsafe { File::from_raw_handle(raw) };
        pinned.verify().map_err(io::Error::other)?;
        windows_control::authenticate_pipe(pipe.as_handle(), pinned.pid)
            .map_err(io::Error::other)?;
        let mut correlation = [0; 16];
        // SAFETY: the RNG receives a valid 16-byte writable buffer and the system-provider flag.
        if unsafe {
            BCryptGenRandom(
                ptr::null_mut(),
                correlation.as_mut_ptr(),
                16,
                BCRYPT_USE_SYSTEM_PREFERRED_RNG,
            )
        } != 0
        {
            return Err(io::Error::other("system RNG failed"));
        }
        pipe.write_all(
            &ArmRequest {
                command,
                correlation,
            }
            .encode()
            .map_err(io::Error::other)?,
        )?;
        let mut raw = [0; exec_ipc::arm::REPLY_SIZE];
        pipe.read_exact(&mut raw)?;
        pinned.verify().map_err(io::Error::other)?;
        windows_control::authenticate_pipe(pipe.as_handle(), pinned.pid)
            .map_err(io::Error::other)?;
        ArmReply::decode(&raw, correlation).map_err(io::Error::other)
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn approval_requires_both_explicit_owner_hashes() {
            let args = |parts: &[&str]| {
                parts
                    .iter()
                    .map(|value| value.to_string())
                    .collect::<Vec<_>>()
            };
            let hash = "ab".repeat(32);
            assert!(command(&args(&["approve", "D:/data/arm-policy.json", &hash, &hash])).is_ok());
            for parts in [
                vec!["approve"],
                vec!["approve", "x", &hash],
                vec!["approve", "x", "bad", &hash],
                vec!["approve", "x", &"00".repeat(32), &hash],
            ] {
                assert!(command(&args(&parts)).is_err());
            }
            assert!(command(&args(&["status"])).is_ok());
        }
    }
}

#[cfg(windows)]
fn main() {
    windows::main();
}

#[cfg(not(windows))]
fn main() {
    eprintln!("gym-arm requires Windows");
    std::process::exit(2);
}
