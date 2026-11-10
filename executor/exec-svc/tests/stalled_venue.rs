//! A-3: a stalled venue read holds neither the vault lock nor the independent T0 stop gate.
use exec_ipc::{StopCommand, StopMode, StopRequest};
use exec_svc::{read_outside_lock, StopGate};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[test]
fn other_privileged_work_and_stop_requests_proceed_while_the_venue_stalls() {
    let vault = Arc::new(Mutex::new(Vec::<&'static str>::new()));
    let gate = Arc::new(StopGate::new(9).unwrap());
    let reader = {
        let vault = Arc::clone(&vault);
        std::thread::spawn(move || {
            read_outside_lock(
                &vault,
                |v| {
                    v.push("begin");
                    Ok(Some("key-copy"))
                },
                |_key| {
                    std::thread::sleep(Duration::from_secs(2));
                    "late body"
                },
                |v, _plan, body| {
                    v.push(body);
                    Ok(Some(()))
                },
            )
        })
    };
    std::thread::sleep(Duration::from_millis(100)); // the read is now stalled
    let started = Instant::now();
    vault.lock().unwrap().push("ceiling request"); // another privileged request takes the vault
    assert!(
        started.elapsed() < Duration::from_millis(200),
        "vault held across the venue read"
    );
    let reply = gate.process(StopRequest {
        command: StopCommand::Halt,
        runtime_epoch: 9,
        correlation: [7; 16],
    });
    assert!(
        started.elapsed() < Duration::from_millis(200),
        "stop gate waited on the venue"
    );
    assert_eq!(gate.mode(), StopMode::Halted, "{reply:?}");
    reader.join().unwrap().unwrap();
    assert_eq!(
        *vault.lock().unwrap(),
        vec!["begin", "ceiling request", "late body"]
    );
}

#[test]
fn nothing_is_read_when_there_is_no_credential() {
    let vault = Mutex::new(0u32);
    let out = read_outside_lock(
        &vault,
        |_| Ok(None::<()>),
        |_| panic!("must not read"),
        |_, _, ()| Ok(Some(1)),
    );
    assert_eq!(out.unwrap(), None::<i32>);
}
