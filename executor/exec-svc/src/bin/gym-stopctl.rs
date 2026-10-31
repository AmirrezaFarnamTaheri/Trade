//! Local stop-only Windows client, with correlated acknowledgment and deadline.
#[cfg(not(windows))]
fn main() {
    eprintln!("gym-stopctl requires Windows");
    std::process::exit(2);
}
#[cfg(windows)]
fn main() {
    if let Err(message) = client::run() {
        eprintln!("UNACKNOWLEDGED: {message}. Verify protection manually.");
        std::process::exit(2);
    }
}
#[cfg(windows)]
mod client {
    use exec_ipc::{StopCommand, StopReply, StopRequest, StopResult, FRAME_SIZE};
    use std::fs::OpenOptions;
    use std::io::{Read, Write};
    use std::sync::mpsc;
    use std::thread;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    const PIPE: &str = r"\\.\pipe\TradingGYM.Stop.v1";

    fn correlation() -> [u8; 16] {
        let nanos = SystemTime::now().duration_since(UNIX_EPOCH)
            .map(|t| t.as_nanos()).unwrap_or(0);
        (nanos ^ ((u128::from(std::process::id())) << 64)).to_be_bytes()
    }

    fn exchange(request: StopRequest, budget: Duration) -> Result<StopReply, String> {
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let result = (|| -> Result<StopReply, String> {
                let frame = request.encode().map_err(|_| "invalid stop frame".to_owned())?;
                let mut pipe = OpenOptions::new().read(true).write(true).open(PIPE)
                    .map_err(|_| "stop pipe unavailable or not authorized".to_owned())?;
                pipe.write_all(&frame).map_err(|_| "stop request not delivered".to_owned())?;
                let mut response = [0u8; FRAME_SIZE];
                pipe.read_exact(&mut response).map_err(|_| "missing stop acknowledgment".to_owned())?;
                StopReply::decode(&response).map_err(|_| "malformed stop acknowledgment".to_owned())
            })();
            let _ = tx.send(result);
        });
        rx.recv_timeout(budget)
            .map_err(|_| "stop response timed out".to_owned())?
    }

    pub fn run() -> Result<(), String> {
        let mut args = std::env::args().skip(1);
        let command = match args.next().as_deref() {
            Some("status") => StopCommand::Status,
            Some("pause") => StopCommand::PauseEntries,
            Some("exit-only") => StopCommand::ExitOnly,
            Some("halt") => StopCommand::Halt,
            _ => return Err("expected status|pause|exit-only|halt".to_owned()),
        };
        if args.next().is_some() { return Err("unexpected argument".to_owned()); }
        let started = Instant::now();
        // STATUS may answer StaleRuntime with the current epoch; this is
        // discovery, never a successful stop acknowledgment.
        let initial = StopRequest {
            command: StopCommand::Status, runtime_epoch: 1, correlation: correlation(),
        };
        let status = exchange(initial, Duration::from_millis(900))?;
        if status.correlation != initial.correlation
            || status.runtime_epoch == 0
            || !matches!(status.result, StopResult::Ack | StopResult::StaleRuntime)
        {
            return Err("untrusted runtime status".to_owned());
        }
        let remaining = Duration::from_millis(900).saturating_sub(started.elapsed());
        if remaining.is_zero() { return Err("stop budget expired".to_owned()); }
        let request = StopRequest {
            command, runtime_epoch: status.runtime_epoch, correlation: correlation(),
        };
        let reply = exchange(request, remaining)?;
        if !reply.confirms(request) {
            return Err("stop request not acknowledged".to_owned());
        }
        println!("ACKNOWLEDGED: {:?} runtime={} mode={:?}",
            command, reply.runtime_epoch, reply.mode);
        Ok(())
    }
}
