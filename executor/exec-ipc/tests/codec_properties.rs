//! Seeded property tests for every hand-written frame codec (no extra dependencies).
//!
//! For each decoder, thousands of frames are derived from a valid seed by flipping bytes,
//! truncating, extending and by pure noise. Two properties must hold for every input:
//! decoding never panics, and anything that decodes re-encodes to exactly the same bytes
//! (one canonical encoding per value, so a parser cannot be steered by alternative forms).
use exec_ipc::account::{
    decode_request as decode_account_request, encode_request as encode_account_request,
};
use exec_ipc::ceiling::{Ceiling, CeilingCommand, CeilingReply, CeilingRequest};
use exec_ipc::provision::AccountResource;
use exec_ipc::review::{Command, Reply, Request};
use exec_ipc::review_v2::{ReplyV2, RequestV2};
use exec_ipc::{StopCommand, StopMode, StopReply, StopRequest, StopResult};

const CASES: usize = 4000;

/// SplitMix64: tiny, deterministic and good enough to spread mutations.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9e37_79b9_7f4a_7c15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
        z ^ (z >> 31)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

/// Mutations of a valid frame: byte flips (most likely to stay near-valid), resizes and noise.
fn variants(seed: &[u8], salt: u64) -> Vec<Vec<u8>> {
    let mut rng = Rng(0x5eed_0000 ^ salt);
    let mut out = vec![seed.to_vec()];
    for _ in 0..CASES {
        let mut frame = seed.to_vec();
        match rng.below(10) {
            0 => frame.truncate(rng.below(seed.len())),
            1 => frame.extend((0..1 + rng.below(8)).map(|_| rng.next() as u8)),
            2 => frame.iter_mut().for_each(|b| *b = rng.next() as u8),
            _ => {
                for _ in 0..1 + rng.below(3) {
                    let i = rng.below(frame.len());
                    frame[i] = match rng.below(4) {
                        0 => 0,
                        1 => 0xff,
                        2 => frame[i] ^ (1 << rng.below(8)),
                        _ => rng.next() as u8,
                    };
                }
            }
        }
        out.push(frame);
    }
    out
}

/// Runs both properties and returns how many variants decoded, so a test can show it reached valid frames.
fn check<T, E>(
    seed: &[u8],
    salt: u64,
    decode: impl Fn(&[u8]) -> Result<T, E>,
    encode: impl Fn(&T) -> Vec<u8>,
) -> usize {
    let mut accepted = 0;
    for frame in variants(seed, salt) {
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| decode(&frame)));
        let decoded = result.unwrap_or_else(|_| panic!("decoder panicked on {frame:02x?}"));
        if let Ok(value) = decoded {
            accepted += 1;
            assert_eq!(encode(&value), frame, "non-canonical frame accepted");
        }
    }
    // Hundreds of mutated frames decode (2026-11-09: 294..1198 per codec), so canonicality is really exercised.
    assert!(
        accepted >= 100,
        "only {accepted} variants decoded; mutations no longer reach valid frames"
    );
    accepted
}

fn ticket(id: &str) -> exec_ipc::review::Ticket {
    let golden = include_str!("../../../contracts/v1/fixtures/operator-review-v1.hex");
    let reply = unhex(golden.lines().nth(1).unwrap());
    let mut ticket = Reply::decode(&reply, [4; 16]).unwrap().ticket.unwrap();
    ticket.client_id = id.into();
    ticket
}

fn unhex(line: &str) -> Vec<u8> {
    (0..line.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&line[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn stop_frames() {
    let request = StopRequest {
        command: StopCommand::PauseEntries,
        runtime_epoch: 7,
        correlation: [5; 16],
    };
    check(&request.encode().unwrap(), 1, StopRequest::decode, |v| {
        v.encode().unwrap().to_vec()
    });
    let reply = StopReply {
        result: StopResult::Ack,
        mode: StopMode::Paused,
        changed: true,
        runtime_epoch: 7,
        correlation: [5; 16],
    };
    check(&reply.encode().unwrap(), 2, StopReply::decode, |v| {
        v.encode().unwrap().to_vec()
    });
}

#[test]
fn ceiling_frames() {
    let ceiling = Ceiling::from_amount("USDT", 1, 6, "12.345678").unwrap();
    let request = CeilingRequest {
        command: CeilingCommand::Set {
            expected_sequence: 18,
            ceiling: ceiling.clone(),
        },
        correlation: [3; 16],
    };
    check(&request.encode().unwrap(), 3, CeilingRequest::decode, |v| {
        v.encode().unwrap().to_vec()
    });
    let reply = CeilingReply {
        sequence: 19,
        ceiling: Some(ceiling),
        correlation: [2; 16],
    };
    check(
        &reply.encode().unwrap(),
        4,
        |raw| CeilingReply::decode(raw, [2; 16]),
        |v| v.encode().unwrap().to_vec(),
    );
}

#[test]
fn account_request_frames() {
    for (salt, resource) in [
        AccountResource::Balances,
        AccountResource::KnownClientOrder("manual-1".into()),
        AccountResource::OpenOrders {
            page: 1000,
            per_page: 100,
        },
    ]
    .into_iter()
    .enumerate()
    {
        let v2 = encode_account_request(&resource, [1; 16]).unwrap();
        check(
            &v2,
            10 + salt as u64,
            decode_account_request,
            |(resource, correlation, v2)| {
                if *v2 {
                    encode_account_request(resource, *correlation)
                        .unwrap()
                        .to_vec()
                } else {
                    resource.encode(*correlation).unwrap().to_vec()
                }
            },
        );
        let v1 = resource.encode([1; 16]).unwrap();
        check(
            &v1,
            20 + salt as u64,
            AccountResource::decode,
            |(resource, correlation)| resource.encode(*correlation).unwrap().to_vec(),
        );
    }
}

#[test]
fn review_frames_v1_and_v2() {
    let golden = include_str!("../../../contracts/v1/fixtures/operator-review-v1.hex");
    let lines: Vec<_> = golden.lines().collect();
    check(&unhex(lines[0]), 30, Request::decode, |v| {
        v.encode().unwrap().to_vec()
    });
    check(
        &unhex(lines[1]),
        31,
        |raw| Reply::decode(raw, [4; 16]),
        |v| v.encode().unwrap().to_vec(),
    );

    let request = RequestV2(Request {
        command: Command::Approve(Box::new(ticket("New_01"))),
        correlation: [4; 16],
    });
    check(&request.encode().unwrap(), 32, RequestV2::decode, |v| {
        v.encode().unwrap().to_vec()
    });
    let mut reply = Reply::decode(&unhex(lines[1]), [4; 16]).unwrap();
    reply.ticket = Some(ticket("New_01"));
    let reply = ReplyV2(reply).encode_for(&request).unwrap();
    check(
        &reply,
        33,
        |raw| ReplyV2::decode_for(raw, &request),
        |v| v.encode_for(&request).unwrap().to_vec(),
    );
}
