//! Durable, single-process-writer event ledger primitives.
//!
//! This crate cannot submit, sign or cancel venue orders. Each append returns
//! only after an SQLite FULL-synchronous transaction commits. The exact stored
//! bytes are chained; parsing and authorization are separate, future layers.

use fs2::FileExt;
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use sha2::{Digest, Sha256};
use std::error::Error;
use std::fmt;
use std::fs::{File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const MAX_EVENT_BYTES: usize = 1024 * 1024;
const SCHEMA_VERSION: i64 = 1;
const GENESIS: [u8; 32] = [0; 32];

/// SHA-256(previous_hash || u64_be(length) || exact_event_bytes).
pub fn hash_event(previous_hash: &[u8; 32], event_bytes: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(previous_hash);
    hasher.update((event_bytes.len() as u64).to_be_bytes());
    hasher.update(event_bytes);
    hasher.finalize().into()
}

/// Verify a sequence without parsing or reserializing the data.
pub fn verify_chain<'a>(
    genesis_hash: [u8; 32],
    events: impl IntoIterator<Item = &'a [u8]>,
    expected_head: [u8; 32],
) -> bool {
    let mut current = genesis_hash;
    for event in events {
        current = hash_event(&current, event);
    }
    current == expected_head
}

#[derive(Debug)]
pub enum LedgerError {
    Sqlite(rusqlite::Error),
    Io(io::Error),
    WriterLocked,
    UnsupportedSchema(i64),
    InvalidSize(usize),
    Configuration(&'static str),
    Integrity { sequence: u64, reason: &'static str },
}

impl fmt::Display for LedgerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Sqlite(err) => write!(f, "sqlite: {err}"),
            Self::Io(err) => write!(f, "io: {err}"),
            Self::WriterLocked => write!(f, "another Executor already owns this writer lock"),
            Self::UnsupportedSchema(v) => write!(f, "unsupported ledger schema version {v}"),
            Self::InvalidSize(n) => write!(f, "invalid event length {n}"),
            Self::Configuration(why) => write!(f, "unsafe ledger configuration: {why}"),
            Self::Integrity { sequence, reason } => {
                write!(f, "ledger integrity failure at sequence {sequence}: {reason}")
            }
        }
    }
}

impl Error for LedgerError {}

impl From<rusqlite::Error> for LedgerError {
    fn from(err: rusqlite::Error) -> Self {
        Self::Sqlite(err)
    }
}

impl From<io::Error> for LedgerError {
    fn from(err: io::Error) -> Self {
        Self::Io(err)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LedgerEntry {
    pub sequence: u64,
    pub event_bytes: Vec<u8>,
    pub previous_hash: [u8; 32],
    pub event_hash: [u8; 32],
}

/// Single-writer API with a process-lifetime advisory lock. The service ACLs
/// remain the authoritative access boundary once the Windows host is built.
pub struct Ledger {
    conn: Connection,
    _writer_lock: File,
    sequence: u64,
    head_hash: [u8; 32],
}

fn lock_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(".writer.lock");
    PathBuf::from(name)
}

fn checked_hash(bytes: Vec<u8>, sequence: u64) -> Result<[u8; 32], LedgerError> {
    bytes.try_into().map_err(|_| LedgerError::Integrity {
        sequence,
        reason: "hash is not 32 bytes",
    })
}

fn load_verified(conn: &Connection) -> Result<(Vec<LedgerEntry>, [u8; 32]), LedgerError> {
    let mut stmt = conn.prepare(
        "SELECT sequence,event_bytes,previous_hash,event_hash FROM ledger_events ORDER BY sequence",
    )?;
    let mut rows = stmt.query([])?;
    let mut events = Vec::new();
    let mut previous = GENESIS;
    while let Some(row) = rows.next()? {
        let raw_sequence: i64 = row.get(0)?;
        let expected = events.len() as u64 + 1;
        if raw_sequence < 1 || raw_sequence as u64 != expected {
            return Err(LedgerError::Integrity { sequence: expected, reason: "missing or out-of-order sequence" });
        }
        let event_bytes: Vec<u8> = row.get(1)?;
        if event_bytes.is_empty() || event_bytes.len() > MAX_EVENT_BYTES {
            return Err(LedgerError::Integrity { sequence: expected, reason: "invalid event length" });
        }
        let prev_hash = checked_hash(row.get(2)?, expected)?;
        let event_hash = checked_hash(row.get(3)?, expected)?;
        if prev_hash != previous {
            return Err(LedgerError::Integrity { sequence: expected, reason: "broken previous hash" });
        }
        if hash_event(&previous, &event_bytes) != event_hash {
            return Err(LedgerError::Integrity { sequence: expected, reason: "stored-byte hash mismatch" });
        }
        events.push(LedgerEntry { sequence: expected, event_bytes, previous_hash: prev_hash, event_hash });
        previous = event_hash;
    }
    Ok((events, previous))
}

impl Ledger {
    /// Open only with WAL and synchronous=FULL. A corrupted or future-version
    /// ledger fails closed before any append is possible.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, LedgerError> {
        let path = path.as_ref();
        let lock = OpenOptions::new().create(true).read(true).write(true).open(lock_path(path))?;
        if let Err(err) = lock.try_lock_exclusive() {
            return Err(if err.kind() == io::ErrorKind::WouldBlock
                || err.raw_os_error() == fs2::lock_contended_error().raw_os_error()
            {
                LedgerError::WriterLocked
            } else {
                LedgerError::Io(err)
            });
        }
        let mut conn = Connection::open(path)?;
        conn.busy_timeout(Duration::from_secs(5))?;
        let mode: String = conn.query_row("PRAGMA journal_mode=WAL", [], |r| r.get(0))?;
        if !mode.eq_ignore_ascii_case("wal") {
            return Err(LedgerError::Configuration("WAL mode unavailable"));
        }
        conn.execute_batch("PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;")?;
        let sync: i64 = conn.query_row("PRAGMA synchronous", [], |r| r.get(0))?;
        if sync != 2 {
            return Err(LedgerError::Configuration("synchronous=FULL was not applied"));
        }
        let version: i64 = conn.query_row("PRAGMA user_version", [], |r| r.get(0))?;
        match version {
            0 => {
                let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
                tx.execute_batch(include_str!("../schema.sql"))?;
                tx.commit()?;
            }
            SCHEMA_VERSION => {}
            unknown => return Err(LedgerError::UnsupportedSchema(unknown)),
        }
        let trigger_count: i64 = conn.query_row(
            concat!(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND ",
                "name IN ('ledger_events_no_update', 'ledger_events_no_delete')"
            ),
            [], |r| r.get(0),
        )?;
        if trigger_count != 2 {
            return Err(LedgerError::Configuration("append-only guards missing"));
        }
        let (events, head_hash) = load_verified(&conn)?;
        Ok(Self { conn, _writer_lock: lock, sequence: events.len() as u64, head_hash })
    }

    /// Commit raw, already validated event bytes before returning an identity.
    /// No venue action may be attempted if this returns an error.
    pub fn append(&mut self, event_bytes: &[u8]) -> Result<LedgerEntry, LedgerError> {
        if event_bytes.is_empty() || event_bytes.len() > MAX_EVENT_BYTES {
            return Err(LedgerError::InvalidSize(event_bytes.len()));
        }
        let tx = self.conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: Option<(i64, Vec<u8>)> = tx.query_row(
            "SELECT sequence,event_hash FROM ledger_events ORDER BY sequence DESC LIMIT 1",
            [], |r| Ok((r.get(0)?, r.get(1)?)),
        ).optional()?;
        let consistent = match current {
            None => self.sequence == 0 && self.head_hash == GENESIS,
            Some((seq, hash)) => seq >= 1 && seq as u64 == self.sequence
                && checked_hash(hash, self.sequence)? == self.head_hash,
        };
        if !consistent {
            return Err(LedgerError::Integrity { sequence: self.sequence + 1, reason: "head changed outside writer" });
        }
        let sequence = self.sequence.checked_add(1).ok_or(LedgerError::Configuration("sequence exhausted"))?;
        let sequence_i64 = i64::try_from(sequence).map_err(|_| LedgerError::Configuration("sequence exhausted"))?;
        let previous_hash = self.head_hash;
        let event_hash = hash_event(&previous_hash, event_bytes);
        tx.execute(
            "INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?1,?2,?3,?4)",
            params![sequence_i64, event_bytes, previous_hash.as_slice(), event_hash.as_slice()],
        )?;
        tx.commit()?;
        self.sequence = sequence;
        self.head_hash = event_hash;
        Ok(LedgerEntry { sequence, event_bytes: event_bytes.to_vec(), previous_hash, event_hash })
    }

    /// Verify the entire chain, also detecting changes to the head while open.
    pub fn verify(&self) -> Result<[u8; 32], LedgerError> {
        let (events, head) = load_verified(&self.conn)?;
        if events.len() as u64 != self.sequence || head != self.head_hash {
            return Err(LedgerError::Integrity { sequence: self.sequence + 1, reason: "head changed outside writer" });
        }
        Ok(head)
    }

    /// Read a verified, strictly ordered suffix for one-way projections.
    pub fn replay_from(&self, after_sequence: u64) -> Result<Vec<LedgerEntry>, LedgerError> {
        self.verify()?;
        let (events, _) = load_verified(&self.conn)?;
        Ok(events.into_iter().filter(|event| event.sequence > after_sequence).collect())
    }

    /// Diagnostic mode values; callers may not lower these settings.
    pub fn pragmas(&self) -> Result<(String, i64), LedgerError> {
        let mode = self.conn.query_row("PRAGMA journal_mode", [], |r| r.get(0))?;
        let sync = self.conn.query_row("PRAGMA synchronous", [], |r| r.get(0))?;
        Ok((mode, sync))
    }
}
