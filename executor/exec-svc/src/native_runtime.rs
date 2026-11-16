//! Native observation and safety workers; neither accepts caller-supplied account facts.
use crate::{
    credential_vault::{random_id, Vault},
    operate_pipe::Context,
};
use std::{
    io,
    sync::{atomic::Ordering, Arc, Mutex},
    time::Duration,
};

fn now_ms() -> io::Result<u64> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(io::Error::other)?
        .as_millis()
        .try_into()
        .map_err(io::Error::other)
}
fn failed(context: &Context) {
    context.gate.disarm();
    context.phase.store(
        exec_svc::ServiceFailure::PrivilegedListener as u32,
        Ordering::SeqCst,
    );
    context.failed.store(true, Ordering::SeqCst);
    context.stop.store(true, Ordering::SeqCst);
}
fn observe(vault: &Mutex<Vault>, context: &Context) -> io::Result<()> {
    let Some((resources, symbols)) = vault
        .lock()
        .map_err(|_| io::Error::other("vault poisoned"))?
        .poll_plan()
    else {
        return Ok(());
    };
    for symbol in symbols {
        let start = now_ms()?;
        let body = crate::service_account::public_depth(&symbol);
        if !vault
            .lock()
            .map_err(|_| io::Error::other("vault poisoned"))?
            .record_native_market(
                &symbol,
                body.as_ref().ok().map(|body| body.0.as_slice()),
                start,
                now_ms()?,
            )
        {
            return Ok(());
        }
    }
    for resource in resources {
        if context.stop.load(Ordering::SeqCst) {
            return Ok(());
        }
        let id = random_id()?;
        let epoch = context.gate.runtime_epoch();
        let saved = exec_svc::read_outside_lock(
            vault,
            |v| v.begin_account_read(&resource, id, epoch),
            |plan| crate::service_account::read(&plan.key, &resource),
            |v, plan, body| v.finish_account_read(plan, &resource, body, id, epoch),
        )?;
        if saved.is_none() {
            return Ok(());
        }
    }
    vault
        .lock()
        .map_err(|_| io::Error::other("vault poisoned"))?
        .observation_cycle_complete();
    Ok(())
}

pub fn start(vault: Arc<Mutex<Vault>>, context: Context) -> io::Result<()> {
    let observer = vault.clone();
    let observed = context.clone();
    std::thread::Builder::new()
        .name("executor-native-observer".into())
        .spawn(move || {
            let result =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> io::Result<()> {
                    while !observed.stop.load(Ordering::SeqCst) {
                        observe(&observer, &observed)?;
                        for _ in 0..50 {
                            if observed.stop.load(Ordering::SeqCst) {
                                return Ok(());
                            }
                            std::thread::sleep(Duration::from_millis(100));
                        }
                    }
                    Ok(())
                }));
            if !observed.stop.load(Ordering::SeqCst) || !matches!(result, Ok(Ok(()))) {
                failed(&observed);
            }
        })?;
    std::thread::Builder::new()
        .name("executor-native-safety".into())
        .spawn(move || {
            let result =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> io::Result<()> {
                    while !context.stop.load(Ordering::SeqCst) {
                        match vault.try_lock() {
                            Ok(mut vault) => vault.safety_tick()?,
                            Err(std::sync::TryLockError::WouldBlock) => {}
                            Err(std::sync::TryLockError::Poisoned(_)) => {
                                return Err(io::Error::other("vault poisoned"))
                            }
                        }
                        std::thread::sleep(Duration::from_millis(100));
                    }
                    Ok(())
                }));
            if !context.stop.load(Ordering::SeqCst) || !matches!(result, Ok(Ok(()))) {
                failed(&context);
            }
        })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, AtomicU32};

    #[test]
    fn worker_fault_stops_the_host_without_weakening_a_halt() {
        let gate = Arc::new(exec_svc::StopGate::new(7).unwrap());
        gate.process(exec_ipc::StopRequest {
            command: exec_ipc::StopCommand::Halt,
            runtime_epoch: 7,
            correlation: [1; 16],
        });
        let context = Context {
            gate,
            user: String::new(),
            logon: String::new(),
            stop: Arc::new(AtomicBool::new(false)),
            failed: Arc::new(AtomicBool::new(false)),
            phase: Arc::new(AtomicU32::new(0)),
        };
        failed(&context);
        assert!(context.stop.load(Ordering::SeqCst));
        assert!(context.failed.load(Ordering::SeqCst));
        assert_eq!(context.gate.mode(), exec_ipc::StopMode::Halted);
        assert_eq!(
            context.phase.load(Ordering::SeqCst),
            exec_svc::ServiceFailure::PrivilegedListener as u32
        );
    }
}
