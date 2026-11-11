//! OD-5: a privileged-thread fault stops the whole service, and a restart comes up disarmed.
use exec_ipc::StopMode;
use exec_svc::{stopped_exit, supervise_privileged, StopGate};
use std::sync::atomic::{AtomicBool, Ordering};

fn run(recovery: bool, body: impl FnOnce() -> std::io::Result<()>) -> (bool, bool) {
    let (failed, stop) = (AtomicBool::new(false), AtomicBool::new(false));
    supervise_privileged(recovery, &failed, &stop, body);
    (failed.load(Ordering::SeqCst), stop.load(Ordering::SeqCst))
}

#[test]
fn a_panic_or_error_in_t2_fails_and_stops_the_service() {
    assert_eq!(
        run(false, || panic!("forced privileged fault")),
        (true, true)
    );
    assert_eq!(
        run(false, || Err(std::io::Error::other("vault"))),
        (true, true)
    );
    // Even an orderly return outside credential recovery stops the service as failed: T2 must never just end.
    assert_eq!(run(false, || Ok(())), (true, true));
    assert_eq!(
        run(true, || Err(std::io::Error::other("vault"))),
        (true, true)
    );
    assert_eq!(run(true, || Ok(())), (false, true));
}

#[test]
fn the_stop_reports_the_privileged_phase() {
    assert_eq!(stopped_exit(false, true, 1008), (5, Some(1008)));
    assert_eq!(stopped_exit(true, false, 1008), (5, None));
    assert_eq!(stopped_exit(false, false, 1008), (0, None));
}

#[test]
fn a_restart_is_disarmed_whatever_the_previous_mode() {
    let before = StopGate::new(7).unwrap();
    assert_eq!(before.mode(), StopMode::Disarmed);
    let after = StopGate::new(8).unwrap();
    assert_eq!(after.mode(), StopMode::Disarmed);
    assert_ne!(before.runtime_epoch(), after.runtime_epoch());
}
