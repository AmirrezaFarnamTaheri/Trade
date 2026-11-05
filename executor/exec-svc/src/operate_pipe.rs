//! Operator-only review receipts. No key reads, account HTTP or order transport.
use crate::credential_vault::{descriptor, Vault};
use exec_ipc::review::{Reply, Request, ReviewState, PIPE, REQUEST_SIZE};
use std::{
    io,
    sync::{
        atomic::{AtomicBool, AtomicU32, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::windows::named_pipe::{NamedPipeServer, PipeMode, ServerOptions},
    sync::Semaphore,
    time::timeout,
};
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;

#[derive(Clone)]
pub struct Context {
    pub gate: Arc<exec_svc::StopGate>,
    pub user: String,
    pub logon: String,
    pub stop: Arc<AtomicBool>,
    pub failed: Arc<AtomicBool>,
    pub phase: Arc<AtomicU32>,
}
impl Context {
    fn fail(&self) {
        self.phase.store(
            exec_svc::ServiceFailure::OperateListener as u32,
            Ordering::SeqCst,
        );
        self.failed.store(true, Ordering::SeqCst);
        self.stop.store(true, Ordering::SeqCst);
    }
    fn deferred(&self, correlation: [u8; 16]) -> Reply {
        Reply {
            state: ReviewState::Deferred,
            mode: self.gate.mode(),
            correlation,
            current_epoch: self.gate.runtime_epoch(),
            sequence: 0,
            recorded_at_ms: 0,
            ceiling_sequence: 0,
            credential_generation: [0; 16],
            ticket: None,
        }
    }
}
fn create(service: &str, logon: &str, first: bool) -> io::Result<NamedPipeServer> {
    let sd = descriptor(&exec_svc::windows_pipe::stop_pipe_sddl(service, logon)?)?;
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
            .max_instances(16)
            .in_buffer_size(REQUEST_SIZE as u32 + 1)
            .out_buffer_size(exec_ipc::review::REPLY_SIZE as u32)
            .create_with_security_attributes_raw(PIPE, (&mut sa as *mut SECURITY_ATTRIBUTES).cast())
    }
}
async fn handle(
    mut client: NamedPipeServer,
    vault: Arc<Mutex<Vault>>,
    context: Context,
    admitted: bool,
) -> io::Result<()> {
    let mut raw = [0; REQUEST_SIZE + 1];
    let count = timeout(Duration::from_millis(750), client.read(&mut raw))
        .await
        .map_err(|_| io::Error::other("review input deadline"))??;
    exec_svc::windows_pipe::verified_client_logon(&client, &context.logon, &context.user)?;
    let request = Request::decode(&raw[..count]).map_err(io::Error::other)?;
    let reply = if !admitted {
        context.deferred(request.correlation)
    } else {
        match vault.try_lock() {
            Ok(mut owner) => {
                match owner.review(&request, &context.user, &context.logon, &context.gate) {
                    Ok(reply) => reply,
                    Err(error) => {
                        context.fail();
                        return Err(error);
                    }
                }
            }
            Err(std::sync::TryLockError::WouldBlock) => context.deferred(request.correlation),
            Err(std::sync::TryLockError::Poisoned(_)) => {
                context.fail();
                return Err(io::Error::other("review owner poisoned"));
            }
        }
    };
    let raw = reply.encode().map_err(|error| {
        context.fail();
        io::Error::other(error)
    })?;
    timeout(Duration::from_millis(750), client.write_all(&raw))
        .await
        .map_err(|_| io::Error::other("review reply deadline"))??;
    Ok(())
}
async fn serve(
    service: String,
    vault: Arc<Mutex<Vault>>,
    context: Context,
    ready: std::sync::mpsc::Sender<()>,
) -> io::Result<()> {
    let mut listening = create(&service, &context.logon, true)?;
    ready.send(()).map_err(io::Error::other)?;
    let slots = Arc::new(Semaphore::new(8));
    loop {
        let connected = listening.connect().await;
        let replacement = create(&service, &context.logon, false)?;
        let client = std::mem::replace(&mut listening, replacement);
        if let Err(error) = connected {
            if error.raw_os_error() == Some(232) {
                continue;
            }
            return Err(error);
        }
        match slots.clone().try_acquire_owned() {
            Ok(slot) => {
                let owner = vault.clone();
                let scope = context.clone();
                tokio::spawn(async move {
                    let _slot = slot;
                    let _ = handle(client, owner, scope, true).await;
                });
            }
            Err(_) => {
                let _ = handle(client, vault.clone(), context.clone(), false).await;
            }
        }
    }
}
pub fn start(service: &str, vault: Arc<Mutex<Vault>>, context: Context) -> io::Result<()> {
    let (tx, rx) = std::sync::mpsc::channel();
    let service = service.to_owned();
    std::thread::spawn(move || {
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(io::Error::other)
                .and_then(|runtime| runtime.block_on(serve(service, vault, context.clone(), tx)))
        }));
        context.fail();
    });
    rx.recv_timeout(Duration::from_secs(3))
        .map_err(io::Error::other)
}
