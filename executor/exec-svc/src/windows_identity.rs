//! Windows SCM host preflight only. This does not verify a service SID,
//! named-pipe ACL, T2 principal, or any credential isolation.
use std::io;
use std::ptr;
use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, LocalFree};
use windows_sys::Win32::Security::Authorization::ConvertSidToStringSidW;
use windows_sys::Win32::Security::{GetTokenInformation, TokenUser, TOKEN_QUERY, TOKEN_USER};
use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

struct OwnedToken(HANDLE);
impl Drop for OwnedToken {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: OpenProcessToken returns a closeable process token handle.
            unsafe { CloseHandle(self.0) };
        }
    }
}

struct OwnedSidText(*mut u16);
impl Drop for OwnedSidText {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: ConvertSidToStringSidW allocates via LocalAlloc.
            unsafe { LocalFree(self.0.cast()) };
        }
    }
}

/// Probe the OS-issued primary user SID; never trust an environment variable
/// or a command-line claim of the service identity.
pub fn process_user_sid() -> io::Result<String> {
    let mut raw_handle: HANDLE = ptr::null_mut();
    // SAFETY: valid pseudo-handle, token out-pointer, no caller-supplied memory.
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw_handle) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let token = OwnedToken(raw_handle);
    let mut size = 0_u32;
    // SAFETY: documented size-probe call; TokenUser result is variable-length.
    unsafe { GetTokenInformation(token.0, TokenUser, ptr::null_mut(), 0, &mut size) };
    if size < std::mem::size_of::<TOKEN_USER>() as u32 || size > 65_536 {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid token user length"));
    }
    // TOKEN_USER is pointer-aligned, unlike Vec<u8>. Use pointer-sized storage.
    let word_size = std::mem::size_of::<usize>();
    let mut storage = vec![0_usize; (size as usize + word_size - 1) / word_size];
    // SAFETY: storage is aligned, sized at least 'size', token and output live.
    if unsafe {
        GetTokenInformation(token.0, TokenUser, storage.as_mut_ptr().cast(), size, &mut size)
    } == 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: validated TokenUser result begins with the expected TOKEN_USER.
    let user = unsafe { &*storage.as_ptr().cast::<TOKEN_USER>() };
    if user.User.Sid.is_null() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "null token SID"));
    }
    let mut raw_string: *mut u16 = ptr::null_mut();
    // SAFETY: SID is contained in the live token information buffer.
    if unsafe { ConvertSidToStringSidW(user.User.Sid, &mut raw_string) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let text = OwnedSidText(raw_string);
    if text.0.is_null() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "null SID text"));
    }
    let mut count = 0_usize;
    // SAFETY: allocated UTF-16 SID string is terminated; cap defensive scan.
    while count < 256 && unsafe { *text.0.add(count) } != 0 {
        count += 1;
    }
    if count == 256 {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "SID text too long"));
    }
    // SAFETY: valid UTF-16 buffer from ConvertSidToStringSidW.
    let slice = unsafe { std::slice::from_raw_parts(text.0, count) };
    String::from_utf16(slice).map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid SID text"))
}

/// Fail closed for any account other than the Windows LocalService SID.
pub fn is_local_service() -> bool {
    process_user_sid()
        .map(|sid| super::is_local_service_sid(&sid))
        .unwrap_or(false)
}
