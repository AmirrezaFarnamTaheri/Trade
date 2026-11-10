//! Stop control is outside the money loop: an atomic, monotone gate with
//! independent request validation. No venue execution or credential handling.
use exec_ipc::{
    ProtocolError, StopCommand, StopMode, StopReply, StopRequest, StopResult, FRAME_SIZE,
};
use std::sync::atomic::{AtomicU8, Ordering};

/// Stable SCM service-specific startup and custody failures; never include credential or request data.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub enum ServiceFailure {
    RestrictedIdentity = 1001,
    ServiceIdentity = 1002,
    OperatorLogon = 1003,
    OperatorUser = 1004,
    StopGate = 1005,
    Vault = 1006,
    PrivilegedPipe = 1007,
    PrivilegedListener = 1008,
    StopListener = 1009,
    CredentialProtection = 1010,
    CiphertextPublication = 1011,
    CiphertextVerification = 1012,
    CredentialCommit = 1013,
    CiphertextCreation = 1014,
    CiphertextWrite = 1015,
    CiphertextSeal = 1016,
    CiphertextRename = 1017,
    OperateListener = 1018,
    IncompleteUpdate = 1019,
}

#[cfg(test)]
mod startup_failure_tests {
    use super::ServiceFailure::*;

    #[test]
    fn startup_failures_have_distinct_stable_service_codes() {
        let codes = [
            RestrictedIdentity,
            ServiceIdentity,
            OperatorLogon,
            OperatorUser,
            StopGate,
            Vault,
            PrivilegedPipe,
            PrivilegedListener,
            StopListener,
            CredentialProtection,
            CiphertextPublication,
            CiphertextVerification,
            CredentialCommit,
            CiphertextCreation,
            CiphertextWrite,
            CiphertextSeal,
            CiphertextRename,
            OperateListener,
            IncompleteUpdate,
        ];
        assert_eq!(
            codes.map(|phase| phase as u32),
            [
                1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014,
                1015, 1016, 1017, 1018, 1019
            ]
        );
    }
}

/// The SCM image folder is administrator-owned; any interrupted publication vetoes startup.
pub fn require_complete_publication(code: &std::path::Path) -> std::io::Result<()> {
    if !std::fs::metadata(code)?.is_dir() {
        return Err(std::io::Error::other("invalid executor code directory"));
    }
    match std::fs::symlink_metadata(code.join("update.pending")) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
        Ok(_) => Err(std::io::Error::other("executor publication incomplete")),
    }
}

/// The LocalService primary user is required but is not sufficient by itself.
/// The SCM host also checks its restricted service-SID membership at runtime.
pub fn is_local_service_sid(sid: &str) -> bool {
    sid == "S-1-5-19"
}

/// A SID from the *OS process token*, not an IPC or configuration claim.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenGroup {
    pub sid: String,
    pub enabled: bool,
}

/// A disabled service SID or an unrestricted service token is not sufficient.
/// `service_sid` must come from Windows LookupAccountNameW for the fixed SCM
/// service name; both SID lists must be retrieved from the actual process token.
pub fn is_restricted_executor_token(
    user_sid: &str,
    service_sid: &str,
    groups: &[TokenGroup],
    restricting_sids: &[String],
) -> bool {
    let suffix = match service_sid.strip_prefix("S-1-5-80-") {
        Some(suffix) => suffix,
        None => return false,
    };
    let pieces: Vec<_> = suffix.split('-').collect();
    if !is_local_service_sid(user_sid)
        || pieces.len() != 5
        || pieces.iter().any(|piece| {
            piece.is_empty()
                || !piece.bytes().all(|byte| byte.is_ascii_digit())
                || piece.parse::<u32>().is_err()
        })
    {
        return false;
    }
    groups
        .iter()
        .any(|group| group.enabled && group.sid == service_sid)
        && restricting_sids.iter().any(|sid| sid == service_sid)
}

#[cfg(windows)]
pub mod windows_identity;

#[cfg(windows)]
pub mod windows_pipe;

#[cfg(windows)]
pub mod windows_control;

/// Runs the privileged (T2) thread body and applies the fail-closed rule (OD-5): a panic or an error marks the
/// service failed, and any return stops the whole service, T0 included. Only an orderly credential-recovery run
/// ends without the failure flag. A restart builds a fresh `StopGate`, which is always `Disarmed`.
pub fn supervise_privileged<F>(
    credential_recovery: bool,
    failed: &std::sync::atomic::AtomicBool,
    stop: &std::sync::atomic::AtomicBool,
    run: F,
) where
    F: FnOnce() -> std::io::Result<()>,
{
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(run));
    if !credential_recovery || !matches!(result, Ok(Ok(()))) {
        failed.store(true, Ordering::SeqCst);
    }
    stop.store(true, Ordering::SeqCst);
}

/// Exit codes reported to the service manager on stop: (Win32 code, service-specific phase code when T2 failed).
pub fn stopped_exit(
    listener_failed: bool,
    privileged_failed: bool,
    phase: u32,
) -> (u32, Option<u32>) {
    let win32 = if listener_failed || privileged_failed {
        5
    } else {
        0
    };
    (win32, privileged_failed.then_some(phase))
}

/// A-3: run a venue read with the vault lock held only to copy the credential out (`begin`) and to record the result
/// (`finish`), never across the read itself, so a stalled venue cannot hold the vault against other privileged work.
pub fn read_outside_lock<V, P, B, R>(
    vault: &std::sync::Mutex<V>,
    begin: impl FnOnce(&mut V) -> std::io::Result<Option<P>>,
    read: impl FnOnce(&P) -> B,
    finish: impl FnOnce(&mut V, P, B) -> std::io::Result<Option<R>>,
) -> std::io::Result<Option<R>> {
    let poisoned = || std::io::Error::other("vault poisoned");
    let Some(plan) = begin(&mut *vault.lock().map_err(|_| poisoned())?)? else {
        return Ok(None);
    };
    let body = read(&plan); // no guard is alive here
    finish(&mut *vault.lock().map_err(|_| poisoned())?, plan, body)
}

/// S-9: who may write a provisioned configuration file (the stop-logon and operator SID files decide who may stop
/// the executor). Pure rule over the owner and the ACEs Windows reports, so it is testable on any OS.
pub mod config_trust {
    pub const SYSTEM: &str = "S-1-5-18";
    pub const ADMINISTRATORS: &str = "S-1-5-32-544";
    pub const TRUSTED_INSTALLER: &str =
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
    /// Rights that change the file's content, attributes, owner or permissions, or delete it.
    pub const WRITE_RIGHTS: u32 = 0x0002
        | 0x0004
        | 0x0010
        | 0x0100
        | 0x0001_0000
        | 0x0004_0000
        | 0x0008_0000
        | 0x1000_0000
        | 0x4000_0000;
    pub const ACCESS_ALLOWED: u8 = 0;
    pub const ACCESS_DENIED: u8 = 1;
    pub const INHERIT_ONLY: u8 = 0x08;

    #[derive(Clone, Debug, PartialEq, Eq)]
    pub struct Ace {
        pub kind: u8,
        pub flags: u8,
        pub mask: u32,
        pub sid: String,
    }

    #[derive(Clone, Debug, PartialEq, Eq)]
    pub enum Untrusted {
        NullDacl,
        Owner(String),
        Writer(String),
        UnknownAce(u8),
    }

    fn trusted(sid: &str) -> bool {
        sid == SYSTEM || sid == ADMINISTRATORS || sid == TRUSTED_INSTALLER
    }

    /// Owner must be SYSTEM, Administrators or TrustedInstaller, and only they may hold any write right.
    pub fn check(owner: &str, dacl: Option<&[Ace]>) -> Result<(), Untrusted> {
        if !trusted(owner) {
            return Err(Untrusted::Owner(owner.to_string()));
        }
        let aces = dacl.ok_or(Untrusted::NullDacl)?;
        for ace in aces {
            if ace.flags & INHERIT_ONLY != 0 || ace.kind == ACCESS_DENIED {
                continue;
            }
            if ace.kind != ACCESS_ALLOWED {
                return Err(Untrusted::UnknownAce(ace.kind));
            }
            if ace.mask & WRITE_RIGHTS != 0 && !trusted(&ace.sid) {
                return Err(Untrusted::Writer(ace.sid.clone()));
            }
        }
        Ok(())
    }
}

pub struct StopGate {
    runtime_epoch: u64,
    mode: AtomicU8,
}

impl StopGate {
    pub fn new(runtime_epoch: u64) -> Result<Self, ProtocolError> {
        if runtime_epoch == 0 {
            return Err(ProtocolError::InvalidIdentity);
        }
        Ok(Self {
            runtime_epoch,
            mode: AtomicU8::new(StopMode::Disarmed as u8),
        })
    }

    pub fn mode(&self) -> StopMode {
        self.mode
            .load(Ordering::SeqCst)
            .try_into()
            .expect("mode only stored by StopGate")
    }

    pub fn runtime_epoch(&self) -> u64 {
        self.runtime_epoch
    }

    /// Linearizable stop: HALT wins over every weaker concurrent request.
    /// This flag must be read before every future venue effect.
    pub fn process(&self, request: StopRequest) -> StopReply {
        let (result, changed) = if request.runtime_epoch != self.runtime_epoch {
            (StopResult::StaleRuntime, false)
        } else {
            match request.command {
                StopCommand::Status => (StopResult::Ack, false),
                command => {
                    let target = match command {
                        StopCommand::PauseEntries => StopMode::Paused as u8,
                        StopCommand::ExitOnly => StopMode::ExitOnly as u8,
                        StopCommand::Halt => StopMode::Halted as u8,
                        StopCommand::Status => unreachable!(),
                    };
                    let old = self.mode.fetch_max(target, Ordering::SeqCst);
                    (StopResult::Ack, old < target)
                }
            }
        };
        StopReply {
            result,
            mode: self.mode(),
            changed,
            runtime_epoch: self.runtime_epoch,
            correlation: request.correlation,
        }
    }

    pub fn process_frame(&self, bytes: &[u8]) -> Result<[u8; FRAME_SIZE], ProtocolError> {
        let request = StopRequest::decode(bytes)?;
        self.process(request).encode()
    }
}

/// Durably replayed, offline-only B2 intents; never grants money authority.
pub mod offline_recovery;

/// Exact service account observations; never spendable balances or permission proof.
pub mod account_observation;

/// Durable service composition with an in-process fake venue, never a live adapter.
pub mod fake_execution;
