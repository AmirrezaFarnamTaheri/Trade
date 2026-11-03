//! Service-only, fixed-origin GET transport. A response is observation, never permission proof.
use crate::credential_vault::{Secret, Vault};
use exec_ipc::provision::{AccountResource, MAX_ACCOUNT_BODY};
use std::{
    ffi::c_void,
    io, ptr,
    time::{Duration, Instant},
};
use windows_sys::Win32::Networking::WinHttp::*;

fn uncertain() -> io::Error {
    io::Error::other("account observation unavailable")
}
struct Handle(*mut c_void);
impl Handle {
    fn checked(raw: *mut c_void) -> io::Result<Self> {
        if raw.is_null() {
            Err(uncertain())
        } else {
            Ok(Self(raw))
        }
    }
}
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe {
            WinHttpCloseHandle(self.0);
        }
    }
}
struct Header(Vec<u16>);
impl Drop for Header {
    fn drop(&mut self) {
        for unit in &mut self.0 {
            unsafe {
                ptr::write_volatile(unit, 0);
            }
        }
    }
}
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}
fn option(handle: &Handle, name: u32, value: u32) -> io::Result<()> {
    if unsafe { WinHttpSetOption(handle.0, name, (&value as *const u32).cast(), 4) } == 0 {
        Err(uncertain())
    } else {
        Ok(())
    }
}
fn success(value: i32) -> io::Result<()> {
    if value == 0 {
        Err(uncertain())
    } else {
        Ok(())
    }
}

fn key_header(key: &Secret) -> io::Result<Header> {
    if !(1..=exec_ipc::provision::MAX_SECRET).contains(&key.0.len())
        || !key.0.iter().all(|b| (0x21..=0x7e).contains(b))
    {
        return Err(uncertain());
    }
    let mut header = Header("X-API-Key: ".encode_utf16().collect());
    header.0.extend(key.0.iter().map(|b| u16::from(*b)));
    header.0.extend([13, 10, 0]);
    Ok(header)
}
fn finish_observation(body: Secret, key: &Secret, elapsed: Duration) -> io::Result<Secret> {
    if elapsed >= Duration::from_secs(12)
        || !(1..=MAX_ACCOUNT_BODY).contains(&body.0.len())
        || key.0.is_empty()
        || body.0.windows(key.0.len()).any(|bytes| bytes == key.0)
    {
        return Err(uncertain());
    }
    Ok(body)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn header_injection_and_out_of_bounds_keys_fail_before_winhttp() {
        for key in [
            b"".as_slice(),
            b"a\r\nInjected: x",
            b"has space",
            b"nul\0",
            b"\xff",
        ] {
            assert!(key_header(&Secret(key.to_vec())).is_err());
        }
        assert!(key_header(&Secret(vec![b'a'; exec_ipc::provision::MAX_SECRET + 1])).is_err());
        assert!(key_header(&Secret(b"synthetic-not-a-key".to_vec())).is_ok());
    }
    #[test]
    fn response_bound_deadline_and_credential_echo_fail_closed() {
        let key = Secret(b"synthetic-not-a-key".to_vec());
        for size in [1, MAX_ACCOUNT_BODY] {
            assert!(finish_observation(Secret(vec![b'x'; size]), &key, Duration::ZERO).is_ok());
        }
        for size in [0, MAX_ACCOUNT_BODY + 1] {
            assert!(finish_observation(Secret(vec![b'x'; size]), &key, Duration::ZERO).is_err());
        }
        assert!(
            finish_observation(Secret(b"unknown".to_vec()), &key, Duration::from_secs(12)).is_err()
        );
        assert!(finish_observation(
            Secret(b"prefix synthetic-not-a-key suffix".to_vec()),
            &key,
            Duration::ZERO
        )
        .is_err());
        assert_eq!(uncertain().to_string(), "account observation unavailable");
    }
}

pub fn read(vault: &Vault, resource: &AccountResource) -> io::Result<Secret> {
    let path = wide(&resource.path().map_err(|_| uncertain())?);
    let key = vault.load_current_secret()?.ok_or_else(uncertain)?;
    let header = key_header(&key)?;
    let started = Instant::now();
    unsafe {
        let session = Handle::checked(WinHttpOpen(
            wide("TradingGYM-observer/1").as_ptr(),
            WINHTTP_ACCESS_TYPE_NO_PROXY,
            ptr::null(),
            ptr::null(),
            0,
        ))?;
        success(WinHttpSetTimeouts(session.0, 2000, 2000, 2000, 2000))?;
        option(&session, WINHTTP_OPTION_CONNECT_RETRIES, 0)?;
        let connection = Handle::checked(WinHttpConnect(
            session.0,
            wide("api.wallex.ir").as_ptr(),
            443,
            0,
        ))?;
        let request = Handle::checked(WinHttpOpenRequest(
            connection.0,
            wide("GET").as_ptr(),
            path.as_ptr(),
            ptr::null(),
            ptr::null(),
            ptr::null(),
            WINHTTP_FLAG_SECURE,
        ))?;
        option(&request, WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT, 3000)?;
        option(&request, WINHTTP_OPTION_MAX_RESPONSE_HEADER_SIZE, 32768)?;
        option(
            &request,
            WINHTTP_OPTION_REDIRECT_POLICY,
            WINHTTP_OPTION_REDIRECT_POLICY_NEVER,
        )?;
        option(
            &request,
            WINHTTP_OPTION_DISABLE_FEATURE,
            WINHTTP_DISABLE_REDIRECTS | WINHTTP_DISABLE_AUTHENTICATION | WINHTTP_DISABLE_COOKIES,
        )?;
        // Native certificate validation is unchanged. No proxy, auth negotiation, redirect or request body.
        success(WinHttpSendRequest(
            request.0,
            header.0.as_ptr(),
            (header.0.len() - 1) as u32,
            ptr::null(),
            0,
            0,
            0,
        ))?;
        drop(header);
        success(WinHttpReceiveResponse(request.0, ptr::null_mut()))?;
        let mut status = 0u32;
        let mut size = 4;
        success(WinHttpQueryHeaders(
            request.0,
            WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
            ptr::null(),
            (&mut status as *mut u32).cast(),
            &mut size,
            ptr::null_mut(),
        ))?;
        if status != 200 {
            return Err(uncertain());
        }
        let mut body = Secret(Vec::new());
        let mut chunk = Secret(vec![0; 16384]);
        loop {
            if started.elapsed() >= Duration::from_secs(12) {
                return Err(uncertain());
            }
            let mut count = 0;
            success(WinHttpReadData(
                request.0,
                chunk.0.as_mut_ptr().cast(),
                chunk.0.len() as u32,
                &mut count,
            ))?;
            if count == 0 {
                break;
            }
            if body.0.len() + count as usize > MAX_ACCOUNT_BODY {
                return Err(uncertain());
            }
            body.0.extend_from_slice(&chunk.0[..count as usize]);
        }
        finish_observation(body, &key, started.elapsed())
    }
}
