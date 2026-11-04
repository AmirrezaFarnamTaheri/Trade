use exec_svc::offline_recovery::{CredentialMetadata, CredentialPermission, DurableOrderJournal};
use std::os::windows::{
    ffi::{OsStrExt, OsStringExt},
    fs::{MetadataExt, OpenOptionsExt},
    io::AsRawHandle,
};
use std::{
    fs::{File, OpenOptions},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    ptr,
};
use windows_sys::Win32::{
    Foundation::LocalFree,
    Security::{Authorization::*, Cryptography::*, *},
    Storage::FileSystem::*,
    System::Com::CoTaskMemFree,
    UI::Shell::{FOLDERID_ProgramData, SHGetKnownFolderPath},
};

pub struct Secret(pub Vec<u8>);
impl Drop for Secret {
    fn drop(&mut self) {
        for b in &mut self.0 {
            unsafe { ptr::write_volatile(b, 0) };
        }
    }
}
pub struct Descriptor(pub PSECURITY_DESCRIPTOR);
impl Drop for Descriptor {
    fn drop(&mut self) {
        unsafe {
            LocalFree(self.0.cast());
        }
    }
}
pub fn descriptor(sddl: &str) -> io::Result<Descriptor> {
    let wide: Vec<_> = sddl.encode_utf16().chain(Some(0)).collect();
    let mut sd = ptr::null_mut();
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            wide.as_ptr(),
            1,
            &mut sd,
            ptr::null_mut(),
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(Descriptor(sd))
}
fn denied() -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        "untrusted credential vault",
    )
}
fn sddl(sid: &str, directory: bool, immutable: bool) -> String {
    let flags = if directory { "OICI" } else { "" };
    let access = if immutable { "FR" } else { "FA" };
    let owner = if directory { "BA" } else { "LS" };
    format!("O:{owner}D:P(A;{flags};RC;;;OW)(A;{flags};FA;;;SY)(A;{flags};FA;;;BA)(A;{flags};{access};;;{sid})")
}
fn check(file: &File, expected: &str) -> io::Result<()> {
    let info = file.metadata()?;
    if info.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(denied());
    }
    let mut owner = ptr::null_mut();
    let mut acl = ptr::null_mut();
    let mut sd = ptr::null_mut();
    let code = unsafe {
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
    };
    if code != 0 {
        return Err(io::Error::from_raw_os_error(code as i32));
    }
    let actual = Descriptor(sd);
    let expected = descriptor(expected)?;
    let mut wanted_owner = ptr::null_mut();
    let mut defaulted = 0;
    let mut wanted_acl = ptr::null_mut();
    let mut present = 0;
    let mut control = 0;
    let mut revision = 0;
    unsafe {
        if GetSecurityDescriptorOwner(expected.0, &mut wanted_owner, &mut defaulted) == 0
            || GetSecurityDescriptorDacl(expected.0, &mut present, &mut wanted_acl, &mut defaulted)
                == 0
            || GetSecurityDescriptorControl(actual.0, &mut control, &mut revision) == 0
            || control & SE_DACL_PROTECTED == 0
            || owner.is_null()
            || acl.is_null()
            || wanted_acl.is_null()
            || EqualSid(owner, wanted_owner) == 0
        {
            return Err(denied());
        }
        let actual_acl = std::slice::from_raw_parts(acl.cast::<u8>(), (*acl).AclSize as usize);
        let expected_acl =
            std::slice::from_raw_parts(wanted_acl.cast::<u8>(), (*wanted_acl).AclSize as usize);
        if actual_acl != expected_acl {
            return Err(denied());
        }
    }
    Ok(())
}
fn open_read(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .access_mode(FILE_GENERIC_READ | READ_CONTROL)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)
        .open(path)
}
pub fn random_id() -> io::Result<[u8; 16]> {
    let mut out = [0; 16];
    if unsafe {
        BCryptGenRandom(
            ptr::null_mut(),
            out.as_mut_ptr(),
            16,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    } != 0
        || out == [0; 16]
    {
        return Err(io::Error::other("OS randomness unavailable"));
    }
    Ok(out)
}
fn generation_name(id: &[u8; 16]) -> String {
    id.iter().map(|b| format!("{b:02x}")).collect::<String>() + ".dpapi"
}
fn digest(ciphertext: &[u8]) -> [u8; 32] {
    exec_store::hash_event(&[0; 32], ciphertext)
}
fn verify_digest(ciphertext: &[u8], expected: &[u8; 32]) -> io::Result<()> {
    if &digest(ciphertext) != expected {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "vault ciphertext digest mismatch",
        ));
    }
    Ok(())
}
struct Dpapi(CRYPT_INTEGER_BLOB);
impl Drop for Dpapi {
    fn drop(&mut self) {
        if !self.0.pbData.is_null() {
            for i in 0..self.0.cbData as usize {
                unsafe { ptr::write_volatile(self.0.pbData.add(i), 0) };
            }
            unsafe {
                LocalFree(self.0.pbData.cast());
            }
        }
    }
}
fn require_service_identity() -> io::Result<()> {
    // DPAPI must use the restricted SCM process identity, never a client token.
    if !exec_svc::windows_identity::is_restricted_executor_service() {
        return Err(denied());
    }
    let mut thread_token = ptr::null_mut();
    use windows_sys::Win32::System::Threading::{GetCurrentThread, OpenThreadToken};
    if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut thread_token) } != 0 {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(thread_token);
        }
        return Err(denied());
    }
    if io::Error::last_os_error().raw_os_error() != Some(1008) {
        return Err(denied());
    }
    Ok(())
}
fn protect(secret: &mut Secret) -> io::Result<Vec<u8>> {
    require_service_identity()?;
    let input = CRYPT_INTEGER_BLOB {
        cbData: secret.0.len() as u32,
        pbData: secret.0.as_mut_ptr(),
    };
    let mut output = Dpapi(CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: ptr::null_mut(),
    });
    if unsafe {
        CryptProtectData(
            &input,
            ptr::null(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output.0,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if output.0.pbData.is_null() || output.0.cbData == 0 || output.0.cbData > 16384 {
        return Err(io::Error::other("invalid DPAPI output"));
    }
    Ok(unsafe { std::slice::from_raw_parts(output.0.pbData, output.0.cbData as usize) }.to_vec())
}
fn unprotect(mut ciphertext: Vec<u8>) -> io::Result<Secret> {
    require_service_identity()?;
    if !(1..=16384).contains(&ciphertext.len()) {
        return Err(denied());
    }
    let input = CRYPT_INTEGER_BLOB {
        cbData: ciphertext.len() as u32,
        pbData: ciphertext.as_mut_ptr(),
    };
    let mut output = Dpapi(CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: ptr::null_mut(),
    });
    if unsafe {
        CryptUnprotectData(
            &input,
            ptr::null_mut(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output.0,
        )
    } == 0
    {
        return Err(io::Error::other("committed credential decryption failed"));
    }
    if output.0.pbData.is_null()
        || !(1..=exec_ipc::provision::MAX_SECRET as u32).contains(&output.0.cbData)
    {
        return Err(denied());
    }
    Ok(Secret(
        unsafe { std::slice::from_raw_parts(output.0.pbData, output.0.cbData as usize) }.to_vec(),
    ))
}
pub struct Vault {
    root: PathBuf,
    sid: String,
    _directories: Vec<File>,
    journal: DurableOrderJournal,
    mode: exec_ipc::provision::StartupMode,
}
impl Vault {
    pub fn open(sid: &str) -> io::Result<Self> {
        Self::open_mode(sid, exec_ipc::provision::StartupMode::Normal)
    }
    pub fn open_mode(sid: &str, mode: exec_ipc::provision::StartupMode) -> io::Result<Self> {
        if !exec_svc::windows_identity::is_restricted_executor_service() {
            return Err(denied());
        }
        let mut raw = ptr::null_mut();
        if unsafe { SHGetKnownFolderPath(&FOLDERID_ProgramData, 0, ptr::null_mut(), &mut raw) } < 0
        {
            return Err(denied());
        }
        let mut length = 0;
        while length < 32768 && unsafe { *raw.add(length) } != 0 {
            length += 1;
        }
        let root = if length < 32768 {
            PathBuf::from(std::ffi::OsString::from_wide(unsafe {
                std::slice::from_raw_parts(raw, length)
            }))
        } else {
            unsafe {
                CoTaskMemFree(raw.cast());
            }
            return Err(denied());
        };
        unsafe {
            CoTaskMemFree(raw.cast());
        }
        let root = root.join("TradingGYM").join("Executor").join("Vault");
        let mut directories = Vec::new();
        for ancestor in root.ancestors().collect::<Vec<_>>().into_iter().rev() {
            let handle = open_read(ancestor)?;
            if !handle.metadata()?.is_dir()
                || handle.metadata()?.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
            {
                return Err(denied());
            }
            directories.push(handle);
        }
        check(directories.last().unwrap(), &sddl(sid, true, false))?;
        let mut pending = Vec::new();
        // Existing ledger and lock files must have the vault's restricted inherited ACL.
        for entry in std::fs::read_dir(&root)? {
            let entry = entry?;
            let file = open_read(&entry.path())?;
            if !file.metadata()?.is_file() {
                return Err(denied());
            }
            if entry.file_name().to_string_lossy().ends_with(".dpapi") {
                check(&file, &sddl(sid, false, true))?;
            } else if entry.file_name().to_string_lossy().ends_with(".pending") {
                if check(&file, &sddl(sid, false, false)).is_err() {
                    check(&file, &sddl(sid, false, true))?;
                }
                pending.push(entry.path());
            } else {
                // SQLite's inherited ACE flags differ from protected generation files.
                check_inherited(&file, sid)?;
            }
        }
        // Recovery must never create a replacement for a lost ledger.
        if mode == exec_ipc::provision::StartupMode::CredentialRecovery {
            let ledger = open_read(&root.join("credentials.sqlite"))?;
            check_inherited(&ledger, sid)?;
            if ledger.metadata()?.len() == 0 {
                return Err(denied());
            }
        }
        let journal = DurableOrderJournal::open(root.join("credentials.sqlite"))
            .map_err(|_| io::Error::other("credential ledger open failed"))?;
        // The exclusive journal writer lock must precede crash-leftover cleanup.
        for path in pending {
            std::fs::remove_file(path)?;
        }
        let vault = Self {
            root,
            sid: sid.to_owned(),
            _directories: directories,
            journal,
            mode,
        };
        if mode.allows_account_read() {
            drop(vault.load_current_secret()?);
        } else if let Some(metadata) = vault.journal.credential_metadata() {
            // Missing or machine-bound DPAPI is recoverable; altered bytes/ACLs are not.
            match vault.load_ciphertext(metadata) {
                Ok(_) => {}
                Err(e) if e.kind() == io::ErrorKind::NotFound => {}
                Err(e) => return Err(e),
            }
        } else {
            return Err(denied());
        }
        Ok(vault)
    }
    // No caller-supplied generation and no fallback to a previous/revoked key.
    pub fn load_current_secret(&self) -> io::Result<Option<Secret>> {
        require_service_identity()?;
        if !self.mode.allows_account_read() {
            return Err(denied());
        }
        self.journal
            .credential_metadata()
            .map(|metadata| unprotect(self.load_ciphertext(metadata)?))
            .transpose()
    }
    fn load_ciphertext(&self, metadata: &CredentialMetadata) -> io::Result<Vec<u8>> {
        let mut file = open_read(&self.root.join(generation_name(&metadata.generation)))?;
        check(&file, &sddl(&self.sid, false, true))?;
        if !(1..=16384).contains(&file.metadata()?.len()) {
            return Err(denied());
        }
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        verify_digest(&bytes, &metadata.ciphertext_digest)?;
        Ok(bytes)
    }
    pub fn provision(&mut self, mut secret: Secret) -> io::Result<[u8; 16]> {
        if !(1..=exec_ipc::provision::MAX_SECRET).contains(&secret.0.len()) {
            return Err(denied());
        }
        let ciphertext = protect(&mut secret)?;
        drop(secret);
        let generation = random_id()?;
        let final_path = self.root.join(generation_name(&generation));
        let temporary = self
            .root
            .join(format!("{}.pending", generation_name(&generation)));
        let sd = descriptor(&sddl(&self.sid, false, false))?;
        let sa = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: sd.0,
            bInheritHandle: 0,
        };
        let wide: Vec<_> = temporary.as_os_str().encode_wide().chain(Some(0)).collect();
        let raw = unsafe {
            CreateFileW(
                wide.as_ptr(),
                FILE_GENERIC_WRITE | READ_CONTROL | WRITE_DAC,
                0,
                &sa,
                CREATE_NEW,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH,
                ptr::null_mut(),
            )
        };
        if raw == windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        use std::os::windows::io::FromRawHandle;
        let mut file = unsafe { File::from_raw_handle(raw) };
        let publication = (|| -> io::Result<()> {
            file.write_all(&ciphertext)?;
            file.sync_all()?;
            let immutable = descriptor(&sddl(&self.sid, false, true))?;
            let mut acl = ptr::null_mut();
            let mut present = 0;
            let mut defaulted = 0;
            if unsafe {
                GetSecurityDescriptorDacl(immutable.0, &mut present, &mut acl, &mut defaulted)
            } == 0
            {
                return Err(io::Error::last_os_error());
            }
            let code = unsafe {
                SetSecurityInfo(
                    file.as_raw_handle(),
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                    ptr::null_mut(),
                    ptr::null_mut(),
                    acl,
                    ptr::null_mut(),
                )
            };
            if code != 0 {
                return Err(io::Error::from_raw_os_error(code as i32));
            }
            file.sync_all()?;
            drop(file);
            let destination: Vec<_> = final_path
                .as_os_str()
                .encode_wide()
                .chain(Some(0))
                .collect();
            // Same-directory atomic, no replacement. WRITE_THROUGH is Windows' rename durability gate.
            if unsafe { MoveFileExW(wide.as_ptr(), destination.as_ptr(), MOVEFILE_WRITE_THROUGH) }
                == 0
            {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        })();
        if let Err(error) = publication {
            std::fs::remove_file(&temporary).map_err(|_| {
                io::Error::other("credential publication failed; orphan cleanup failed")
            })?;
            return Err(error);
        }
        // Keep sealed ciphertext if a journal commit has an uncertain outcome.
        let metadata = CredentialMetadata {
            generation,
            ciphertext_digest: digest(&ciphertext),
            permission: CredentialPermission::Unverified,
        };
        if let Err(error) = self.load_ciphertext(&metadata) {
            std::fs::remove_file(&final_path).map_err(|_| {
                io::Error::other("credential verification failed; orphan cleanup failed")
            })?;
            return Err(error);
        }
        self.journal
            .commit_credential(metadata)
            .map_err(|_| io::Error::other("credential metadata commit failed"))?;
        Ok(generation)
    }
}
fn check_inherited(file: &File, sid: &str) -> io::Result<()> {
    // Normalize inherited-only flag bits and protection on a private descriptor copy;
    // the actual ACL still must contain exactly these four ACEs and no others.
    let mut owner = ptr::null_mut();
    let mut acl = ptr::null_mut();
    let mut sd = ptr::null_mut();
    let code = unsafe {
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
    };
    if code != 0 {
        return Err(io::Error::from_raw_os_error(code as i32));
    }
    let actual = Descriptor(sd);
    if acl.is_null() {
        return Err(denied());
    }
    unsafe {
        for i in 0..(*acl).AceCount as u32 {
            let mut ace = ptr::null_mut();
            if GetAce(acl, i, &mut ace) == 0 {
                return Err(denied());
            }
            let header = &mut *ace.cast::<ACE_HEADER>();
            if u32::from(header.AceFlags) != INHERITED_ACE {
                return Err(denied());
            }
            header.AceFlags = 0;
        }
        if SetSecurityDescriptorControl(actual.0, SE_DACL_PROTECTED, SE_DACL_PROTECTED) == 0 {
            return Err(denied());
        }
    }
    // Compare the normalized owner/DACL bytes directly against the expected descriptor.
    let expected = descriptor(&sddl(sid, false, false))?;
    let mut wanted_owner = ptr::null_mut();
    let mut wanted_acl = ptr::null_mut();
    let mut p = 0;
    let mut d = 0;
    unsafe {
        if GetSecurityDescriptorOwner(expected.0, &mut wanted_owner, &mut d) == 0
            || GetSecurityDescriptorDacl(expected.0, &mut p, &mut wanted_acl, &mut d) == 0
            || EqualSid(owner, wanted_owner) == 0
        {
            return Err(denied());
        }
        if std::slice::from_raw_parts(acl.cast::<u8>(), (*acl).AclSize as usize)
            != std::slice::from_raw_parts(wanted_acl.cast::<u8>(), (*wanted_acl).AclSize as usize)
        {
            return Err(denied());
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    #[test]
    fn ordinary_process_cannot_open_vault_or_use_service_dpapi() {
        assert!(!exec_svc::windows_identity::is_restricted_executor_service());
        assert!(super::Vault::open("S-1-5-18").is_err());
        assert!(super::Vault::open_mode(
            "S-1-5-18",
            exec_ipc::provision::StartupMode::CredentialRecovery
        )
        .is_err());
        assert!(super::protect(&mut super::Secret(b"synthetic test bytes".to_vec())).is_err());
        assert!(super::unprotect(b"synthetic ciphertext".to_vec()).is_err());
    }
    #[test]
    fn ciphertext_corruption_and_truncation_fail_closed() {
        let ciphertext = b"synthetic ciphertext, not a credential";
        let hash = super::digest(ciphertext);
        assert!(super::verify_digest(ciphertext, &hash).is_ok());
        assert!(super::verify_digest(&ciphertext[..3], &hash).is_err());
        assert!(super::verify_digest(b"different", &hash).is_err());
    }
}
