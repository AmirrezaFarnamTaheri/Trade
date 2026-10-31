//! Restricted Windows SCM host identity preflight, using the OS process token.
//! This does not verify named-pipe ACLs, T2 principal or credential isolation.
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


/// Derive the fixed service SID from Windows account lookup, not from an
/// environment variable, config file, IPC message, or installer output.
pub fn executor_service_sid_from_os() -> io::Result<String> {
    use windows_sys::Win32::Security::LookupAccountNameW;
    let name: Vec<u16> = "NT SERVICE\\TradingGYMExecutor"
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();
    let mut sid_len = 0_u32;
    let mut domain_len = 0_u32;
    let mut sid_use = 0;
    // SAFETY: documented sizing probe; both output lengths start at zero.
    let probe = unsafe {
        LookupAccountNameW(
            ptr::null(), name.as_ptr(), ptr::null_mut(), &mut sid_len,
            ptr::null_mut(), &mut domain_len, &mut sid_use,
        )
    };
    if probe != 0 || io::Error::last_os_error().raw_os_error() != Some(122)
        || sid_len == 0 || sid_len > 1024 || domain_len > 4096
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid service SID lookup size"));
    }
    let words = (sid_len as usize + std::mem::size_of::<usize>() - 1)
        / std::mem::size_of::<usize>();
    let mut sid_memory = vec![0_usize; words];
    let mut domain = vec![0_u16; domain_len as usize];
    let domain_ptr = if domain.is_empty() { ptr::null_mut() } else { domain.as_mut_ptr() };
    // SAFETY: SID storage is aligned and sized using the OS-provided length.
    let found = unsafe {
        LookupAccountNameW(
            ptr::null(), name.as_ptr(), sid_memory.as_mut_ptr().cast(),
            &mut sid_len, domain_ptr, &mut domain_len, &mut sid_use,
        )
    };
    if found == 0 { return Err(io::Error::last_os_error()); }
    if sid_len < 8 || sid_len as usize > sid_memory.len() * std::mem::size_of::<usize>() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid service SID length"));
    }
    sid_text(sid_memory.as_mut_ptr().cast())
}

fn sid_text(sid: *mut std::ffi::c_void) -> io::Result<String> {
    if sid.is_null() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "null token group SID"));
    }
    let mut raw_string: *mut u16 = ptr::null_mut();
    // SAFETY: SID comes from Windows token information or LookupAccountNameW.
    if unsafe { ConvertSidToStringSidW(sid, &mut raw_string) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let text = OwnedSidText(raw_string);
    if text.0.is_null() {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "null SID text"));
    }
    let mut count = 0_usize;
    while count < 256 && unsafe { *text.0.add(count) } != 0 { count += 1; }
    if count == 256 {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "SID text too long"));
    }
    let slice = unsafe { std::slice::from_raw_parts(text.0, count) };
    String::from_utf16(slice).map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid SID text"))
}

fn current_token_groups(kind: windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS)
    -> io::Result<Vec<super::TokenGroup>>
{
    use windows_sys::Win32::Security::{SID_AND_ATTRIBUTES, TOKEN_GROUPS};
    let mut raw_handle: HANDLE = ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw_handle) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let token = OwnedToken(raw_handle);
    let mut size = 0_u32;
    // SAFETY: sizing probe; token is a process token with TOKEN_QUERY only.
    let probe = unsafe { GetTokenInformation(token.0, kind, ptr::null_mut(), 0, &mut size) };
    if probe != 0 || io::Error::last_os_error().raw_os_error() != Some(122)
        || (size as usize) < std::mem::size_of::<TOKEN_GROUPS>()
        || size > 1_048_576
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid token groups size"));
    }
    let word = std::mem::size_of::<usize>();
    let mut aligned = vec![0_usize; (size as usize + word - 1) / word];
    let allocated = aligned.len() * word;
    // SAFETY: an aligned buffer with the OS-requested capacity.
    let ok = unsafe { GetTokenInformation(token.0, kind, aligned.as_mut_ptr().cast(), size, &mut size) };
    if ok == 0 { return Err(io::Error::last_os_error()); }
    let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    if (size as usize) < offset || (size as usize) > allocated {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "token groups length changed"));
    }
    let base = aligned.as_ptr().cast::<TOKEN_GROUPS>();
    // SAFETY: GetTokenInformation returned a TOKEN_GROUPS header.
    let count = unsafe { (*base).GroupCount as usize };
    let available = (size as usize - offset) / std::mem::size_of::<SID_AND_ATTRIBUTES>();
    if count > available {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "token group count exceeds buffer"));
    }
    // SAFETY: count is bounded by returned OS memory, and both structs have
    // compatible C alignment with the aligned Vec<usize> backing allocation.
    let pointer = unsafe { std::ptr::addr_of!((*base).Groups).cast::<SID_AND_ATTRIBUTES>() };
    let entries = unsafe { std::slice::from_raw_parts(pointer, count) };
    let mut out = Vec::with_capacity(count);
    for entry in entries {
        out.push(super::TokenGroup {
            sid: sid_text(entry.Sid)?,
            enabled: (entry.Attributes & 0x4) != 0, // SE_GROUP_ENABLED
        });
    }
    Ok(out)
}

/// The SCM host refuses RUNNING unless the current *OS process token* has:
/// - LocalService as its primary user;
/// - the exact service SID enabled in ordinary group membership;
/// - the same service SID in its restricting SID list.
///
/// This does not certify the operator logon SID, pipe ACL, T2, credentials,
/// private data ACLs or funded safety. It is a strictly stronger bootstrap gate.
pub fn is_restricted_executor_service() -> bool {
    use windows_sys::Win32::Security::{TokenGroups, TokenRestrictedSids};
    (|| -> io::Result<bool> {
        let user_sid = process_user_sid()?;
        let service_sid = executor_service_sid_from_os()?;
        let groups = current_token_groups(TokenGroups)?;
        let restricted = current_token_groups(TokenRestrictedSids)?;
        let restricting_sids = restricted.into_iter().map(|g| g.sid).collect::<Vec<_>>();
        Ok(super::is_restricted_executor_token(
            &user_sid, &service_sid, &groups, &restricting_sids,
        ))
    })().unwrap_or(false)
}


/// Query the Windows TokenUser of the currently impersonated named-pipe
/// client, never a supplied user name or group. The server must call this
/// synchronously before RevertToSelf and before applying a stop request.
pub fn impersonated_thread_user_sid() -> io::Result<String> {
    use windows_sys::Win32::System::Threading::{GetCurrentThread, OpenThreadToken};
    let mut raw_token: HANDLE = ptr::null_mut();
    if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut raw_token) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let token = OwnedToken(raw_token);
    let mut size = 0_u32;
    let probe = unsafe {
        GetTokenInformation(token.0, TokenUser, ptr::null_mut(), 0, &mut size)
    };
    if probe != 0 || io::Error::last_os_error().raw_os_error() != Some(122)
        || size < std::mem::size_of::<TOKEN_USER>() as u32 || size > 65_536
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid client TokenUser size"));
    }
    let word = std::mem::size_of::<usize>();
    let mut aligned = vec![0_usize; (size as usize + word - 1) / word];
    if unsafe {
        GetTokenInformation(token.0, TokenUser, aligned.as_mut_ptr().cast(), size, &mut size)
    } == 0 {
        return Err(io::Error::last_os_error());
    }
    if (size as usize) < std::mem::size_of::<TOKEN_USER>() ||
        (size as usize) > aligned.len() * word
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "client TokenUser length changed"));
    }
    let user = unsafe { &*aligned.as_ptr().cast::<TOKEN_USER>() };
    sid_text(user.User.Sid)
}

/// Read the OS-issued logon SID of the currently impersonated named-pipe
/// client. This MUST be called synchronously on the same thread after the
/// server has read from that client's pipe and before RevertToSelf. Never use
/// process token or a client-supplied field as the authorized identity.
pub fn impersonated_thread_logon_sid() -> io::Result<String> {
    use windows_sys::Win32::Security::{
        GetTokenInformation, SID_AND_ATTRIBUTES, TOKEN_GROUPS, TOKEN_QUERY,
        TokenLogonSid,
    };
    use windows_sys::Win32::System::Threading::{GetCurrentThread, OpenThreadToken};

    let mut raw_token: HANDLE = ptr::null_mut();
    // OpenAsSelf=TRUE is required when the client requests identification-only
    // SQOS; otherwise opening a token while impersonating can fail.
    if unsafe { OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, 1, &mut raw_token) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let token = OwnedToken(raw_token);
    let mut length = 0_u32;
    let sizing_result = unsafe {
        GetTokenInformation(token.0, TokenLogonSid, ptr::null_mut(), 0, &mut length)
    };
    if sizing_result != 0 || io::Error::last_os_error().raw_os_error() != Some(122)
        || length < std::mem::size_of::<TOKEN_GROUPS>() as u32 || length > 65_536
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid client logon SID size"));
    }
    // The token's SID pointers require pointer-aligned storage.
    let word = std::mem::size_of::<usize>();
    let mut storage = vec![0_usize; (length as usize + word - 1) / word];
    let allocated = storage.len() * word;
    if unsafe {
        GetTokenInformation(token.0, TokenLogonSid, storage.as_mut_ptr().cast(),
                            length, &mut length)
    } == 0 {
        return Err(io::Error::last_os_error());
    }
    let groups = storage.as_ptr().cast::<TOKEN_GROUPS>();
    let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    if (length as usize) < offset || (length as usize) > allocated {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid client token groups"));
    }
    // TokenLogonSid is a singleton OS-issued SID, not arbitrary TokenGroups.
    let count = unsafe { (*groups).GroupCount as usize };
    let capacity = (length as usize - offset) / std::mem::size_of::<SID_AND_ATTRIBUTES>();
    if count != 1 || capacity < 1 {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "ambiguous client logon SID"));
    }
    let entry = unsafe { &*std::ptr::addr_of!((*groups).Groups).cast::<SID_AND_ATTRIBUTES>() };
    if (entry.Attributes & 0xC000_0000) != 0xC000_0000 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "untrusted client logon group"));
    }
    let sid = sid_text(entry.Sid)?;
    let components: Vec<&str> = sid.split('-').collect();
    if components.len() != 6 || components[..4] != ["S", "1", "5", "5"]
        || components[4..].iter().any(|part| part.is_empty()
            || !part.bytes().all(|b| b.is_ascii_digit()))
    {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "malformed client logon SID"));
    }
    Ok(sid)
}
