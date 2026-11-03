#[cfg(not(windows))]
fn main() {
    eprintln!("gym-provision requires Windows");
    std::process::exit(2);
}
#[cfg(windows)]
#[path = "../windows_control.rs"]
mod windows_control;
#[cfg(windows)]
fn main() {
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(client::run());
    });
    match rx.recv_timeout(std::time::Duration::from_secs(10)) {
        Ok(Ok(())) => println!("COMMITTED: permission UNVERIFIED; executor remains DISARMED"),
        _ => {
            eprintln!("NOT_ACKNOWLEDGED: provisioning failed or timed out; outcome may be committed. No authority granted.");
            std::process::exit(2);
        }
    }
}
#[cfg(windows)]
mod client {
    use exec_ipc::provision::*;
    use std::os::windows::{
        ffi::OsStrExt,
        fs::{MetadataExt, OpenOptionsExt},
        io::{AsRawHandle, FromRawHandle},
    };
    use std::{
        fs::{File, OpenOptions},
        io::{Read, Write},
        ptr,
    };
    use windows_sys::Win32::{
        Foundation::{LocalFree, INVALID_HANDLE_VALUE},
        Security::{Authorization::*, Cryptography::*, *},
        Storage::FileSystem::*,
    };
    struct Secret(Vec<u8>);
    impl Drop for Secret {
        fn drop(&mut self) {
            for b in &mut self.0 {
                unsafe { ptr::write_volatile(b, 0) };
            }
        }
    }
    struct Sd(PSECURITY_DESCRIPTOR);
    impl Drop for Sd {
        fn drop(&mut self) {
            unsafe {
                LocalFree(self.0.cast());
            }
        }
    }
    fn err() -> String {
        "secret file must be private, current-user-owned, regular and non-reparse".into()
    }
    fn private_file(path: &std::path::Path) -> Result<(File, Vec<File>), String> {
        let path = std::path::absolute(path).map_err(|_| err())?;
        let mut parents = Vec::new();
        for parent in path
            .parent()
            .ok_or_else(err)?
            .ancestors()
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
        {
            let dir = OpenOptions::new()
                .read(true)
                .share_mode(FILE_SHARE_READ)
                .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
                .open(parent)
                .map_err(|_| err())?;
            if dir.metadata().map_err(|_| err())?.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT
                != 0
            {
                return Err(err());
            }
            parents.push(dir);
        }
        let file = OpenOptions::new()
            .read(true)
            .access_mode(FILE_GENERIC_READ | READ_CONTROL)
            .share_mode(0)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)
            .map_err(|_| err())?;
        let metadata = file.metadata().map_err(|_| err())?;
        if !metadata.is_file()
            || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || !(1..=MAX_SECRET as u64).contains(&metadata.len())
        {
            return Err(err());
        }
        let user = exec_svc::windows_identity::process_user_sid().map_err(|_| err())?;
        let sddl: Vec<_> = format!("O:{user}D:(A;;FA;;;{user})(A;;FA;;;SY)(A;;FA;;;BA)")
            .encode_utf16()
            .chain(Some(0))
            .collect();
        let mut expected = ptr::null_mut();
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                1,
                &mut expected,
                ptr::null_mut(),
            )
        } == 0
        {
            return Err(err());
        }
        let expected = Sd(expected);
        let mut owner = ptr::null_mut();
        let mut acl = ptr::null_mut();
        let mut sd = ptr::null_mut();
        if unsafe {
            GetSecurityInfo(
                file.as_raw_handle(),
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                ptr::null_mut(),
                &mut acl,
                ptr::null_mut(),
                &mut sd,
            )
        } != 0
        {
            return Err(err());
        }
        let _actual = Sd(sd);
        let mut expected_owner = ptr::null_mut();
        let mut expected_acl = ptr::null_mut();
        let mut p = 0;
        let mut d = 0;
        unsafe {
            if GetSecurityDescriptorOwner(expected.0, &mut expected_owner, &mut d) == 0
                || GetSecurityDescriptorDacl(expected.0, &mut p, &mut expected_acl, &mut d) == 0
                || owner.is_null()
                || acl.is_null()
                || EqualSid(owner, expected_owner) == 0
            {
                return Err(err());
            }
            for i in 0..(*acl).AceCount as u32 {
                let mut raw = ptr::null_mut();
                if GetAce(acl, i, &mut raw) == 0 || (*raw.cast::<ACE_HEADER>()).AceType != 0
                /* ACCESS_ALLOWED_ACE_TYPE */
                {
                    return Err(err());
                }
                let ace = &*raw.cast::<ACCESS_ALLOWED_ACE>();
                let sid = ptr::addr_of!(ace.SidStart).cast_mut().cast();
                let mut allowed = false;
                for j in 0..(*expected_acl).AceCount as u32 {
                    let mut target = ptr::null_mut();
                    if GetAce(expected_acl, j, &mut target) == 0 {
                        return Err(err());
                    }
                    let target = &*target.cast::<ACCESS_ALLOWED_ACE>();
                    if EqualSid(sid, ptr::addr_of!(target.SidStart).cast_mut().cast()) != 0 {
                        allowed = true;
                    }
                }
                if !allowed {
                    return Err(err());
                }
            }
        }
        Ok((file, parents))
    }
    pub fn run() -> Result<(), String> {
        let mut args = std::env::args_os().skip(1);
        if args.next().as_deref() != Some(std::ffi::OsStr::new("--secret-file")) {
            return Err("expected --secret-file PATH".into());
        }
        let path = args.next().ok_or("missing private secret file")?;
        if args.next().is_some() {
            return Err("unexpected argument".into());
        }
        let (file, _parents) = private_file(std::path::Path::new(&path))?;
        let mut secret = Secret(Vec::with_capacity(MAX_SECRET + 1));
        file.take((MAX_SECRET + 1) as u64)
            .read_to_end(&mut secret.0)
            .map_err(|_| "secret read failed")?;
        if !(1..=MAX_SECRET).contains(&secret.0.len()) {
            return Err("secret outside bounds".into());
        }
        let pinned = super::windows_control::pin()?;
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
            return Err("privileged pipe open failed".into());
        }
        let mut pipe = unsafe { File::from_raw_handle(raw) };
        pinned.verify()?;
        super::windows_control::authenticate_pipe(raw, pinned.pid)?;
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
            return Err("OS randomness unavailable".into());
        }
        pipe.write_all(&header(secret.0.len(), correlation).map_err(str::to_owned)?)
            .map_err(|_| "header write failed")?;
        let mut ready = [0; 8];
        pipe.read_exact(&mut ready)
            .map_err(|_| "T2 admission denied")?;
        if &ready != READY {
            return Err("invalid admission response".into());
        }
        pinned.verify()?;
        super::windows_control::authenticate_pipe(raw, pinned.pid)?;
        pipe.write_all(&secret.0)
            .map_err(|_| "secret transfer failed")?;
        drop(secret);
        let mut ack = [0; ACK_SIZE];
        pipe.read_exact(&mut ack)
            .map_err(|_| "metadata commit not acknowledged")?;
        if !confirms(&ack, correlation) {
            return Err("invalid provisioning acknowledgment".into());
        }
        Ok(())
    }
}
