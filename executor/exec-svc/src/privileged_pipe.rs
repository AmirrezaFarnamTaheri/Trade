use crate::credential_vault::{descriptor, Secret, Vault};
use exec_ipc::provision::*;
use std::{io, os::windows::io::AsRawHandle, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::windows::named_pipe::{NamedPipeServer, PipeMode, ServerOptions},
    time::timeout,
};
use windows_sys::Win32::{
    Security::{RevertToSelf, SECURITY_ATTRIBUTES},
    System::Pipes::ImpersonateNamedPipeClient,
};
const DEADLINE: Duration = Duration::from_secs(3);

fn create(sid: &str, first: bool) -> io::Result<NamedPipeServer> {
    // Administrators get data access, not FILE_CREATE_PIPE_INSTANCE (0x4).
    let sd = descriptor(&format!(
        "D:P(A;;GA;;;SY)(A;;GA;;;{sid})(A;;0x00100083;;;BA)"
    ))?;
    let mut sa = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: sd.0,
        bInheritHandle: 0,
    };
    unsafe {
        ServerOptions::new()
            .pipe_mode(PipeMode::Message)
            .reject_remote_clients(true)
            .first_pipe_instance(first)
            .max_instances(2)
            .in_buffer_size(8192)
            .out_buffer_size(128)
            .create_with_security_attributes_raw(PIPE, (&mut sa as *mut SECURITY_ATTRIBUTES).cast())
    }
}
fn admit(pipe: &NamedPipeServer) -> io::Result<()> {
    if unsafe { ImpersonateNamedPipeClient(pipe.as_raw_handle()) } == 0 {
        return Err(io::Error::last_os_error());
    }
    // No await, no DPAPI, and no filesystem operation while impersonating.
    let result = exec_svc::windows_identity::impersonated_elevated_administrator();
    if unsafe { RevertToSelf() } == 0 {
        std::process::abort();
    }
    result
}
enum Request {
    Provision(Secret, [u8; 16]),
    Account(AccountResource, [u8; 16]),
}
async fn receive(pipe: &mut NamedPipeServer, mode: StartupMode) -> io::Result<Request> {
    let mut hello = [0; ACCOUNT_REQUEST_SIZE + 1];
    let count = pipe.read(&mut hello).await?;
    admit(pipe)?;
    if hello[..count].starts_with(b"TGAREAD1") {
        if !mode.allows_account_read() {
            return Err(io::Error::other("recovery accepts provisioning only"));
        }
        let (resource, correlation) =
            AccountResource::decode(&hello[..count]).map_err(io::Error::other)?;
        return Ok(Request::Account(resource, correlation));
    }
    let (length, correlation) = parse_header(&hello[..count]).map_err(io::Error::other)?;
    pipe.write_all(READY).await?;
    let mut secret = Secret(vec![0; MAX_SECRET + 1]);
    let count = pipe.read(&mut secret.0).await?;
    if count != length {
        return Err(io::Error::other("invalid secret message length"));
    }
    secret.0.truncate(count);
    admit(pipe)?;
    Ok(Request::Provision(secret, correlation))
}
pub async fn serve(
    sid: &str,
    ready: std::sync::mpsc::Sender<()>,
    mode: StartupMode,
) -> io::Result<()> {
    let mut vault = if mode != StartupMode::CredentialRecovery {
        Vault::open(sid)?
    } else {
        Vault::open_mode(sid, mode)?
    };
    let mut listening = create(sid, true)?;
    ready
        .send(())
        .map_err(|_| io::Error::other("service startup cancelled"))?;
    loop {
        let result = listening.connect().await;
        let replacement = create(sid, false)?;
        let mut client = std::mem::replace(&mut listening, replacement);
        match result {
            Ok(()) => {
                if let Ok(Ok(request)) = timeout(DEADLINE, receive(&mut client, mode)).await {
                    match request {
                        Request::Provision(secret, correlation) => {
                            // A vault error is fatal, including an uncertain journal commit.
                            let generation = vault.provision(secret)?;
                            let _ = timeout(
                                DEADLINE,
                                client.write_all(&committed(correlation, generation)),
                            )
                            .await;
                            if mode == StartupMode::CredentialRecovery {
                                return Ok(());
                            }
                        }
                        Request::Account(resource, correlation) => {
                            // This T2 thread may block; independent authenticated T0 never waits on it.
                            if let Ok(body) = crate::service_account::read(&vault, &resource) {
                                let reply = account_reply(body.0.len(), correlation)
                                    .map_err(io::Error::other)?;
                                let _ = timeout(DEADLINE, async {
                                    client.write_all(&reply).await?;
                                    for chunk in body.0.chunks(16384) {
                                        client.write_all(chunk).await?;
                                    }
                                    io::Result::Ok(())
                                })
                                .await;
                            }
                        }
                    }
                }
            }
            Err(e) if e.raw_os_error() == Some(232) => {}
            Err(e) => return Err(e),
        }
    }
}
