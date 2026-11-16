//! Elevated manual submission of one previously reviewed and prepared native ticket.
#[cfg(windows)]
mod windows {
    use exec_ipc::{
        arm::{ArmCommand, ArmReply, ArmRequest},
        review::{Command, Request, ReviewState},
        review_v2::{valid_submit_client_id, ReplyV2, RequestV2},
        submit::{SubmitReply, SubmitRequest, SubmitState},
        StopMode,
    };
    use exec_svc::windows_control::{exchange_control, random_correlation};
    use std::io;

    fn arguments(args: &[String]) -> io::Result<(String, Option<(u64, u64)>)> {
        let parsed=match args {
            [action,id] if action=="inspect"=>(id.clone(),None),
            [action,id,sequence,epoch] if action=="submit"=>(id.clone(),Some((sequence.parse().map_err(io::Error::other)?,epoch.parse().map_err(io::Error::other)?))),
            _=>return Err(io::Error::other("Usage: gym-submit inspect CLIENT_ID | submit CLIENT_ID PREPARED_SEQUENCE RUNTIME_EPOCH")),
        };
        valid_submit_client_id(&parsed.0).map_err(io::Error::other)?;
        if parsed
            .1
            .is_some_and(|(sequence, epoch)| sequence == 0 || epoch == 0)
        {
            return Err(io::Error::other("zero review version or runtime"));
        }
        Ok(parsed)
    }
    fn bounded<T: Send + 'static>(
        work: impl FnOnce() -> io::Result<T> + Send + 'static,
    ) -> io::Result<T> {
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let _ = tx.send(work());
        });
        rx.recv_timeout(std::time::Duration::from_secs(20))
            .map_err(|_| io::Error::other("native control deadline"))?
    }
    fn status() -> io::Result<ArmReply> {
        let request = ArmRequest {
            command: ArmCommand::Status,
            correlation: random_correlation()?,
        };
        let raw = exchange_control::<{ exec_ipc::arm::REPLY_SIZE }>(
            exec_ipc::provision::PIPE,
            &request.encode().map_err(io::Error::other)?,
        )?;
        ArmReply::decode(&raw, request.correlation).map_err(io::Error::other)
    }
    fn reviewed(id: String) -> io::Result<exec_ipc::review::Reply> {
        let request = RequestV2(Request {
            command: Command::Inspect(id),
            correlation: random_correlation()?,
        });
        let raw = exchange_control::<{ exec_ipc::review::REPLY_SIZE }>(
            exec_ipc::review::PIPE,
            &request.encode().map_err(io::Error::other)?,
        )?;
        Ok(ReplyV2::decode_for(&raw, &request)
            .map_err(io::Error::other)?
            .0)
    }
    pub(super) fn run() -> io::Result<()> {
        use std::io::{BufRead, IsTerminal, Read};
        let (id, submit) = arguments(&std::env::args().skip(1).collect::<Vec<_>>())?;
        let status = bounded(status)?;
        let (sequence, epoch, revision) = if let Some((sequence, epoch)) = submit {
            if status.mode != StopMode::Armed || status.runtime_epoch != epoch {
                return Err(io::Error::other(
                    "native service is not armed in the reviewed runtime",
                ));
            }
            let inspected = id.clone();
            let review = bounded(move || reviewed(inspected))?;
            if review.state != ReviewState::Prepared
                || review.sequence != sequence
                || review.current_epoch != epoch
            {
                return Err(io::Error::other("prepared review changed"));
            }
            println!(
                "PREPARED_TICKET={}\nNATIVE_ARM_REVISION={}",
                serde_json::to_string_pretty(&review.ticket).map_err(io::Error::other)?,
                status.revision
            );
            if !std::io::stdin().is_terminal() {
                return Err(io::Error::other("interactive elevated submission required"));
            }
            let phrase = format!("SUBMIT {id} {sequence} {epoch}");
            eprintln!("Type {phrase} to request this one LIMIT order:");
            let mut answer = String::new();
            std::io::stdin().lock().take(192).read_line(&mut answer)?;
            if answer.trim() != phrase {
                return Err(io::Error::other("submission cancelled"));
            }
            (sequence, epoch, status.revision)
        } else {
            (0, status.runtime_epoch, 0)
        };
        let request = SubmitRequest {
            submit: submit.is_some(),
            client_id: id,
            expected_sequence: sequence,
            runtime_epoch: epoch,
            arm_revision: revision,
            correlation: random_correlation()?,
        };
        let reply = bounded(move || {
            let raw = exchange_control::<{ exec_ipc::submit::REPLY_SIZE }>(
                exec_ipc::provision::PIPE,
                &request.encode().map_err(io::Error::other)?,
            )?;
            SubmitReply::decode_for(&raw, &request).map_err(io::Error::other)
        })?;
        println!("ACKNOWLEDGED state={:?} client_id={} sequence={} runtime={} mode={:?}; no automatic retry",reply.state,reply.client_id,reply.sequence,reply.runtime_epoch,reply.mode);
        if reply.state == SubmitState::Refused {
            return Err(io::Error::other("native submission refused"));
        }
        Ok(())
    }
    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn submission_needs_a_safe_identity_and_explicit_nonzero_review_context() {
            let args = |values: &[&str]| values.iter().map(|s| s.to_string()).collect::<Vec<_>>();
            assert!(arguments(&args(&["submit", "intent_1", "3", "7"])).is_ok());
            for values in [
                vec!["submit", "intent_1"],
                vec!["submit", "old-id", "3", "7"],
                vec!["submit", "intent_1", "0", "7"],
                vec!["submit", "intent_1", "3", "0"],
            ] {
                assert!(arguments(&args(&values)).is_err());
            }
        }
    }
}
fn main() {
    #[cfg(windows)]
    if let Err(error) = windows::run() {
        eprintln!("{error}\nUNACKNOWLEDGED or refused: inspect the same client identity before any further action. Never resubmit an uncertain identity.");
        std::process::exit(2);
    }
    #[cfg(not(windows))]
    {
        eprintln!("gym-submit requires Windows");
        std::process::exit(2);
    }
}
