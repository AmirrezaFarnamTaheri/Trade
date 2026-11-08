//! Operator-installed R0 Python in a no-capability AppContainer. No profile creation here.
use std::io;
use std::path::Path;

#[cfg(windows)]
pub const PROFILE: &str = "TradingGym.Research.R0";
#[cfg(windows)]
pub const WALL_MS: u32 = 300_000;
#[cfg(windows)]
pub const MEMORY_BYTES: usize = 512 * 1024 * 1024;

pub fn launch(root: &Path, probe: bool) -> io::Result<u32> {
    #[cfg(windows)]
    {
        windows::launch(root, probe)
    }
    #[cfg(not(windows))]
    {
        let _ = (root, probe);
        Err(io::Error::other("Windows AppContainer required"))
    }
}

#[cfg(windows)]
mod windows {
    use super::*;
    use std::{
        ffi::OsStr,
        fs::{self, File, OpenOptions},
        mem::{size_of, zeroed},
        os::windows::{ffi::OsStrExt, fs::OpenOptionsExt},
        ptr,
    };
    use windows_sys::Win32::{
        Foundation::*,
        Security::{Authorization::*, Isolation::*, *},
        Storage::FileSystem::*,
        System::{Com::CoTaskMemFree, JobObjects::*, Pipes::CreatePipe, Threading::*},
        UI::Shell::{FOLDERID_LocalAppData, SHGetKnownFolderPath},
    };

    struct Handle(HANDLE);
    impl Drop for Handle {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
    struct Sid(PSID);
    impl Drop for Sid {
        fn drop(&mut self) {
            unsafe {
                FreeSid(self.0);
            }
        }
    }
    struct Local(*mut core::ffi::c_void);
    impl Drop for Local {
        fn drop(&mut self) {
            unsafe {
                LocalFree(self.0);
            }
        }
    }
    struct Attributes(Vec<usize>);
    impl Drop for Attributes {
        fn drop(&mut self) {
            unsafe {
                DeleteProcThreadAttributeList(self.0.as_mut_ptr().cast());
            }
        }
    }
    // Every early error after CreateProcess must kill the still-suspended child.
    struct Child {
        process: Handle,
        thread: Handle,
    }
    impl Drop for Child {
        fn drop(&mut self) {
            unsafe {
                TerminateProcess(self.process.0, 125);
            }
        }
    }
    fn fail(message: &str) -> io::Error {
        io::Error::new(io::ErrorKind::PermissionDenied, message)
    }
    fn check(ok: i32) -> io::Result<()> {
        if ok == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
    fn wide(s: impl AsRef<OsStr>) -> io::Result<Vec<u16>> {
        let mut s: Vec<u16> = s.as_ref().encode_wide().collect();
        if s.contains(&0) {
            return Err(fail("NUL in installation path"));
        }
        s.push(0);
        Ok(s)
    }
    fn environment() -> io::Result<Vec<u16>> {
        let mut raw = ptr::null_mut();
        let hr =
            unsafe { SHGetKnownFolderPath(&FOLDERID_LocalAppData, 0, ptr::null_mut(), &mut raw) };
        if hr < 0 {
            return Err(fail("operator LocalAppData lookup failed"));
        }
        if raw.is_null() {
            return Err(fail("operator LocalAppData missing"));
        }
        let mut block: Vec<u16> = "LOCALAPPDATA=".encode_utf16().collect();
        let mut length = 0;
        unsafe {
            while length < 32768 && *raw.add(length) != 0 {
                block.push(*raw.add(length));
                length += 1;
            }
            CoTaskMemFree(raw.cast());
        }
        if length == 0 || length == 32768 {
            return Err(fail("invalid operator LocalAppData"));
        }
        block.extend([0, 0]);
        Ok(block)
    }
    #[test]
    fn child_environment_contains_only_os_resolved_profile_location() {
        let block = environment().unwrap();
        assert!(block.ends_with(&[0, 0]));
        assert!(!block[..block.len() - 2].contains(&0));
        let text = String::from_utf16(&block[..block.len() - 2]).unwrap();
        assert!(text.starts_with("LOCALAPPDATA="));
        assert!(Path::new(text.strip_prefix("LOCALAPPDATA=").unwrap()).is_absolute());
    }
    fn sid_text(sid: PSID) -> io::Result<String> {
        if sid.is_null() || unsafe { IsValidSid(sid) } == 0 {
            return Err(fail("invalid SID"));
        }
        let mut text = ptr::null_mut();
        check(unsafe { ConvertSidToStringSidW(sid, &mut text) })?;
        let _allocation = Local(text.cast());
        let mut len = 0;
        while len < 256 && unsafe { *text.add(len) } != 0 {
            len += 1;
        }
        if len == 256 {
            return Err(fail("invalid SID text"));
        }
        Ok(String::from_utf16_lossy(unsafe {
            std::slice::from_raw_parts(text, len)
        }))
    }
    fn trusted(sid: PSID) -> io::Result<bool> {
        Ok(matches!(
            sid_text(sid)?.as_str(),
            "S-1-5-18"
                | "S-1-5-32-544"
                | "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
        ))
    }

    // Keep no-write/no-delete shared handles alive through child exit; reject links and writable ancestors.
    fn protect(path: &Path, contents: bool, held: &mut Vec<File>) -> io::Result<()> {
        use std::os::windows::io::AsRawHandle;
        let f = OpenOptions::new()
            .access_mode(READ_CONTROL | FILE_READ_ATTRIBUTES)
            .share_mode(FILE_SHARE_READ)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)?;
        let h = f.as_raw_handle();
        let mut info: BY_HANDLE_FILE_INFORMATION = unsafe { zeroed() };
        check(unsafe { GetFileInformationByHandle(h, &mut info) })?;
        if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0 && info.nNumberOfLinks != 1)
        {
            return Err(fail("reparse point or multiply-linked installation/input"));
        }
        let mut owner = ptr::null_mut();
        let mut acl = ptr::null_mut();
        let mut sd = ptr::null_mut();
        let status = unsafe {
            GetSecurityInfo(
                h,
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                ptr::null_mut(),
                &mut acl,
                ptr::null_mut(),
                &mut sd,
            )
        };
        if status != 0 {
            return Err(io::Error::from_raw_os_error(status as i32));
        }
        let _sd = Local(sd);
        if acl.is_null() || !trusted(owner)? {
            return Err(fail("untrusted owner or null DACL"));
        }
        // Ancestors may allow creating unrelated siblings, never replacing this protected child.
        let writes = if contents {
            0x500d0156u32
        } else {
            0x500d0040u32
        };
        for index in 0..unsafe { (*acl).AceCount } {
            let mut ace = ptr::null_mut();
            check(unsafe { GetAce(acl, index as u32, &mut ace) })?;
            let header = unsafe { &*ace.cast::<ACE_HEADER>() };
            if header.AceFlags & 0x08 != 0 {
                continue;
            } // INHERIT_ONLY_ACE is not effective on this object.
            match header.AceType {
                0 => {
                    let allowed = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
                    if allowed.Mask & writes != 0
                        && !trusted((&allowed.SidStart as *const u32).cast_mut().cast())?
                    {
                        return Err(fail(
                            "installation/input or ancestor grants untrusted mutation",
                        ));
                    }
                }
                1 => (), // Denies cannot grant mutation; all allow ACEs are checked independently.
                _ => return Err(fail("unsupported ACL ACE; explicit simple ACL required")),
            }
        }
        held.push(f);
        if held.len() > 30_000 {
            return Err(fail("installation exceeds validation limit"));
        }
        Ok(())
    }
    fn tree(path: &Path, held: &mut Vec<File>, depth: usize) -> io::Result<()> {
        if depth > 32 {
            return Err(fail("installation tree too deep"));
        }
        protect(path, true, held)?;
        if path.is_dir() {
            for entry in fs::read_dir(path)? {
                tree(&entry?.path(), held, depth + 1)?;
            }
        }
        Ok(())
    }
    fn token_data(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> io::Result<Vec<usize>> {
        let mut size = 0;
        unsafe {
            GetTokenInformation(token, class, ptr::null_mut(), 0, &mut size);
        }
        if size == 0 || size > 65536 {
            return Err(fail("invalid token information length"));
        }
        let mut data = vec![0usize; (size as usize).div_ceil(size_of::<usize>())];
        check(unsafe {
            GetTokenInformation(token, class, data.as_mut_ptr().cast(), size, &mut size)
        })?;
        Ok(data)
    }
    fn verify_token(process: HANDLE, expected: PSID) -> io::Result<()> {
        let mut raw = ptr::null_mut();
        check(unsafe { OpenProcessToken(process, TOKEN_QUERY, &mut raw) })?;
        let token = Handle(raw);
        let app = token_data(token.0, TokenIsAppContainer)?;
        if unsafe { *app.as_ptr().cast::<u32>() } != 1 {
            return Err(fail("actual child is not an AppContainer"));
        }
        let data = token_data(token.0, TokenAppContainerSid)?;
        let sid = unsafe { &*data.as_ptr().cast::<TOKEN_APPCONTAINER_INFORMATION>() };
        if sid.TokenAppContainer.is_null()
            || unsafe { EqualSid(sid.TokenAppContainer, expected) } == 0
        {
            return Err(fail("actual child AppContainer SID mismatch"));
        }
        let caps = token_data(token.0, TokenCapabilities)?;
        if unsafe { (*caps.as_ptr().cast::<TOKEN_GROUPS>()).GroupCount } != 0 {
            return Err(fail("actual child has capabilities"));
        }
        let integrity = token_data(token.0, TokenIntegrityLevel)?;
        let label = unsafe { &*integrity.as_ptr().cast::<TOKEN_MANDATORY_LABEL>() };
        let n = unsafe { *GetSidSubAuthorityCount(label.Label.Sid) };
        if n == 0 || unsafe { *GetSidSubAuthority(label.Label.Sid, n as u32 - 1) } > 0x1000 {
            return Err(fail("actual child integrity exceeds Low"));
        }
        Ok(())
    }
    fn pipe(child_reads: bool) -> io::Result<(Handle, File)> {
        use std::os::windows::io::FromRawHandle;
        let mut read = ptr::null_mut();
        let mut write = ptr::null_mut();
        let sa = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: ptr::null_mut(),
            bInheritHandle: 1,
        };
        check(unsafe { CreatePipe(&mut read, &mut write, &sa, 0) })?;
        let (child, parent) = if child_reads {
            (Handle(read), Handle(write))
        } else {
            (Handle(write), Handle(read))
        };
        check(unsafe { SetHandleInformation(parent.0, HANDLE_FLAG_INHERIT, 0) })?;
        let file = unsafe { File::from_raw_handle(parent.0) };
        std::mem::forget(parent);
        Ok((child, file))
    }
    pub fn launch(root: &Path, probe: bool) -> io::Result<u32> {
        // No UNC, device paths, relative paths, ADS or command-line metacharacter ambiguity.
        let text = root
            .to_str()
            .ok_or_else(|| fail("installation path must be Unicode"))?;
        let b = text.as_bytes();
        if b.len() < 4
            || !b[0].is_ascii_alphabetic()
            || &b[1..3] != b":\\"
            || text[3..].contains([':', '"', '\r', '\n'])
            || root.components().any(|c| {
                matches!(
                    c,
                    std::path::Component::ParentDir | std::path::Component::CurDir
                )
            })
        {
            return Err(fail("explicit local absolute installation path required"));
        }
        let mut held = Vec::new();
        for parent in root.ancestors().skip(1) {
            protect(parent, false, &mut held)?;
        }
        tree(root, &mut held, 0)?;
        let runtime = root.join("runtime");
        let inputs = root.join("inputs");
        let pths: Vec<_> = fs::read_dir(&runtime)?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().is_some_and(|e| e == "_pth"))
            .collect();
        if pths.len() != 1 {
            return Err(fail("exactly one embeddable CPython _pth required"));
        }
        let stem = pths[0]
            .file_stem()
            .and_then(|s| s.to_str())
            .ok_or_else(|| fail("invalid CPython _pth"))?;
        if !stem.starts_with("python3")
            || !stem[7..].bytes().all(|b| b.is_ascii_digit())
            || stem.len() < 9
            || !runtime.join(format!("{stem}.dll")).is_file()
            || !runtime.join(format!("{stem}.zip")).is_file()
            || fs::read_to_string(&pths[0])?.replace("\r\n", "\n")
                != format!("{stem}.zip\n.\nLib\\site-packages\n")
        {
            return Err(fail(
                "runtime must use fixed isolated _pth, local stdlib and protected package only",
            ));
        }
        let python = runtime.join("python.exe");
        if !python.is_file()
            || runtime.join("pyvenv.cfg").exists()
            || !runtime
                .join("Lib/site-packages/gym/services/research_worker.py")
                .is_file()
        {
            return Err(fail(
                "protected self-contained CPython + R0 package missing",
            ));
        }
        let names: Vec<_> = fs::read_dir(&inputs)?
            .map(|e| e.map(|v| v.file_name()))
            .collect::<Result<_, _>>()?;
        if names.len() != 2
            || !names
                .iter()
                .all(|n| n == "market.db" || n == "research.sqlite3")
        {
            return Err(fail(
                "published input must contain only two standalone SQLite snapshots",
            ));
        }
        for name in ["market.db", "research.sqlite3"] {
            let path = inputs.join(name);
            if !path.is_file() {
                return Err(fail("snapshot is not a file"));
            }
            use std::io::Read;
            let mut header = [0u8; 20];
            File::open(path)?.read_exact(&mut header)?;
            if &header[..16] != b"SQLite format 3\0" || header[18] != 1 || header[19] != 1 {
                return Err(fail("snapshot is not standalone rollback-mode SQLite"));
            }
        }
        let mut sid = ptr::null_mut();
        let hr =
            unsafe { DeriveAppContainerSidFromAppContainerName(wide(PROFILE)?.as_ptr(), &mut sid) };
        if hr < 0 {
            return Err(fail("cannot derive operator-installed AppContainer SID"));
        }
        let sid = Sid(sid);
        if fs::read_to_string(root.join("binding.txt"))?.trim() != sid_text(sid.0)? {
            return Err(fail("protected profile binding mismatch"));
        }
        let (stdin, input) = pipe(true)?;
        let (stdout, output) = pipe(false)?;
        let (stderr, errors) = pipe(false)?;
        let mut handles = [stdin.0, stdout.0, stderr.0];
        let mut caps = SECURITY_CAPABILITIES {
            AppContainerSid: sid.0,
            Capabilities: ptr::null_mut(),
            CapabilityCount: 0,
            Reserved: 0,
        };
        let mut bytes = 0;
        unsafe {
            InitializeProcThreadAttributeList(ptr::null_mut(), 2, 0, &mut bytes);
        }
        if bytes == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut storage = vec![0usize; bytes.div_ceil(size_of::<usize>())];
        let list = storage.as_mut_ptr().cast();
        check(unsafe { InitializeProcThreadAttributeList(list, 2, 0, &mut bytes) })?;
        let _attributes = Attributes(storage);
        check(unsafe {
            UpdateProcThreadAttribute(
                list,
                0,
                PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES as usize,
                (&mut caps as *mut SECURITY_CAPABILITIES).cast(),
                size_of::<SECURITY_CAPABILITIES>(),
                ptr::null_mut(),
                ptr::null(),
            )
        })?;
        check(unsafe {
            UpdateProcThreadAttribute(
                list,
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
                handles.as_mut_ptr().cast(),
                size_of_val(&handles),
                ptr::null_mut(),
                ptr::null(),
            )
        })?;
        let job = Handle(unsafe { CreateJobObjectW(ptr::null(), ptr::null()) });
        if job.0.is_null() {
            return Err(io::Error::last_os_error());
        }
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_JOB_MEMORY
            | JOB_OBJECT_LIMIT_JOB_TIME
            | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION;
        limits.BasicLimitInformation.ActiveProcessLimit = 1;
        limits.BasicLimitInformation.PerJobUserTimeLimit = WALL_MS as i64 * 10_000;
        limits.ProcessMemoryLimit = MEMORY_BYTES;
        limits.JobMemoryLimit = MEMORY_BYTES;
        check(unsafe {
            SetInformationJobObject(
                job.0,
                JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                size_of_val(&limits) as u32,
            )
        })?;
        let mut startup: STARTUPINFOEXW = unsafe { zeroed() };
        startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = stdin.0;
        startup.StartupInfo.hStdOutput = stdout.0;
        startup.StartupInfo.hStdError = stderr.0;
        startup.lpAttributeList = list;
        let exe = wide(&python)?;
        let mut command = wide(format!(
            "\"{}\" -I -S -B -m gym.services.research_worker \"{}\"{}",
            python.display(),
            inputs.display(),
            if probe { " --boundary-probe" } else { "" }
        ))?;
        // Windows requires this location to resolve the AppContainer; inherit no caller variables.
        let mut environment = environment()?;
        let mut process: PROCESS_INFORMATION = unsafe { zeroed() };
        check(unsafe {
            CreateProcessW(
                exe.as_ptr(),
                command.as_mut_ptr(),
                ptr::null(),
                ptr::null(),
                1,
                CREATE_SUSPENDED
                    | CREATE_UNICODE_ENVIRONMENT
                    | EXTENDED_STARTUPINFO_PRESENT
                    | CREATE_NO_WINDOW,
                environment.as_mut_ptr().cast(),
                wide(&runtime)?.as_ptr(),
                &startup.StartupInfo,
                &mut process,
            )
        })?;
        let child = Child {
            process: Handle(process.hProcess),
            thread: Handle(process.hThread),
        };
        drop((stdin, stdout, stderr));
        verify_token(child.process.0, sid.0)?;
        check(unsafe { AssignProcessToJobObject(job.0, child.process.0) })?;
        eprintln!("R0 child PID={} AppContainer={} capabilities=0 (verified suspended); live boundaries NOT_VERIFIED", process.dwProcessId, sid_text(sid.0)?);
        if unsafe { ResumeThread(child.thread.0) } == u32::MAX {
            return Err(io::Error::last_os_error());
        }
        // Only fresh anonymous pipes reach Python; no caller/service handles are duplicated.
        std::thread::spawn(move || {
            let _ = io::copy(&mut io::stdin().lock(), &mut { input });
        });
        let (sent, received) = std::sync::mpsc::channel();
        let errors_sent = sent.clone();
        std::thread::spawn(move || {
            let result = io::copy(&mut { output }, &mut io::stdout().lock());
            let _ = sent.send(result);
        });
        std::thread::spawn(move || {
            let result = io::copy(&mut { errors }, &mut io::stderr().lock());
            let _ = errors_sent.send(result);
        });
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(WALL_MS as u64);
        match unsafe { WaitForSingleObject(child.process.0, WALL_MS) } {
            WAIT_OBJECT_0 => {
                let mut code = 0;
                check(unsafe { GetExitCodeProcess(child.process.0, &mut code) })?;
                for _ in 0..2 {
                    received
                        .recv_timeout(deadline.saturating_duration_since(std::time::Instant::now()))
                        .map_err(|_| {
                            io::Error::new(
                                io::ErrorKind::TimedOut,
                                "stdio forwarding did not finish",
                            )
                        })??;
                }
                Ok(code)
            }
            WAIT_TIMEOUT => {
                check(unsafe { TerminateJobObject(job.0, 124) })?;
                Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "R0 wall time exceeded",
                ))
            }
            _ => Err(io::Error::last_os_error()),
        }
    }
}
