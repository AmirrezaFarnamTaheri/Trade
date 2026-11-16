//! Durable, single-process-writer event ledger primitives.
//!
//! This crate cannot submit, sign or cancel venue orders. Each append returns
//! only after an SQLite FULL-synchronous transaction commits. The exact stored
//! bytes are chained; parsing and authorization are separate, future layers.
#![forbid(unsafe_code)]

use fs2::FileExt;
use rusqlite::{params, Connection, OpenFlags, OptionalExtension, TransactionBehavior};
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
                write!(
                    f,
                    "ledger integrity failure at sequence {sequence}: {reason}"
                )
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
    path: PathBuf,
    _writer_lock: File,
    sequence: u64,
    head_hash: [u8; 32],
}

/// A disposable projection rebuilt only from a fully decoded, hash-verified prefix.
pub struct IdentityIndex<'a> {
    conn: &'a Connection,
}

impl IdentityIndex<'_> {
    pub fn contains(&self, scope: &str, key: &[u8]) -> Result<bool, LedgerError> {
        Ok(self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM temp.audit_identities WHERE scope=?1 AND identity=?2)",
            params![scope, key],
            |row| row.get(0),
        )?)
    }

    pub fn remember(&self, scope: &str, key: &[u8], sequence: u64) -> Result<(), LedgerError> {
        self.conn.execute(
            "INSERT OR IGNORE INTO temp.audit_identities(scope,identity,sequence) VALUES(?1,?2,?3)",
            params![scope, key, sqlite_sequence(sequence)?],
        )?;
        Ok(())
    }

    pub fn keys(&self, scope: &str) -> Result<Vec<Vec<u8>>, LedgerError> {
        let count: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM temp.audit_identities WHERE scope=?1",
            [scope],
            |row| row.get(0),
        )?;
        if count > (MAX_EVENT_BYTES / 16) as i64 {
            return Err(LedgerError::Configuration(
                "legacy checkpoint identity history exceeds event bound",
            ));
        }
        let mut stmt = self.conn.prepare(
            "SELECT identity FROM temp.audit_identities WHERE scope=?1 ORDER BY identity",
        )?;
        let keys = stmt
            .query_map([scope], |row| row.get(0))?
            .collect::<Result<_, _>>()?;
        Ok(keys)
    }
}

fn sqlite_sequence(sequence: u64) -> Result<i64, LedgerError> {
    i64::try_from(sequence).map_err(|_| LedgerError::Configuration("sequence exhausted"))
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

fn load_verified(
    conn: &Connection,
    after_sequence: u64,
) -> Result<(u64, [u8; 32], Vec<LedgerEntry>), LedgerError> {
    let mut visible = Vec::new();
    let (sequence, previous) = visit_verified(conn, |entry| {
        if entry.sequence > after_sequence {
            visible.push(entry);
        }
        Ok(())
    })?;
    Ok((sequence, previous, visible))
}

fn visit_verified(
    conn: &Connection,
    mut visit: impl FnMut(LedgerEntry) -> Result<(), LedgerError>,
) -> Result<(u64, [u8; 32]), LedgerError> {
    let mut stmt = conn.prepare(
        "SELECT sequence,event_bytes,previous_hash,event_hash FROM ledger_events ORDER BY sequence",
    )?;
    let mut rows = stmt.query([])?;
    let mut sequence = 0_u64;
    let mut previous = GENESIS;
    while let Some(row) = rows.next()? {
        let raw_sequence: i64 = row.get(0)?;
        let expected = sequence
            .checked_add(1)
            .ok_or(LedgerError::Configuration("sequence exhausted"))?;
        if raw_sequence < 1 || raw_sequence as u64 != expected {
            return Err(LedgerError::Integrity {
                sequence: expected,
                reason: "missing or out-of-order sequence",
            });
        }
        let event_bytes: Vec<u8> = row.get(1)?;
        if event_bytes.is_empty() || event_bytes.len() > MAX_EVENT_BYTES {
            return Err(LedgerError::Integrity {
                sequence: expected,
                reason: "invalid event length",
            });
        }
        let prev_hash = checked_hash(row.get(2)?, expected)?;
        let event_hash = checked_hash(row.get(3)?, expected)?;
        if prev_hash != previous {
            return Err(LedgerError::Integrity {
                sequence: expected,
                reason: "broken previous hash",
            });
        }
        if hash_event(&previous, &event_bytes) != event_hash {
            return Err(LedgerError::Integrity {
                sequence: expected,
                reason: "stored-byte hash mismatch",
            });
        }
        visit(LedgerEntry {
            sequence: expected,
            event_bytes,
            previous_hash: prev_hash,
            event_hash,
        })?;
        previous = event_hash;
        sequence = expected;
    }
    Ok((sequence, previous))
}

impl Ledger {
    /// Open only with WAL and synchronous=FULL. A corrupted or future-version
    /// ledger fails closed before any append is possible.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, LedgerError> {
        Self::open_verified(path.as_ref(), u64::MAX, None).map(|(ledger, _)| ledger)
    }

    /// Open and return the full verified history in one pass for startup projections.
    pub fn open_and_replay(
        path: impl AsRef<Path>,
    ) -> Result<(Self, Vec<LedgerEntry>), LedgerError> {
        Self::open_verified(path.as_ref(), 0, None)
    }

    /// Verify every chain byte, retaining only the latest checkpoint and its suffix for projection.
    pub fn open_after_checkpoint(
        path: impl AsRef<Path>,
        magic: &[u8; 8],
    ) -> Result<(Self, Vec<LedgerEntry>), LedgerError> {
        Self::open_after_checkpoints(path, &[magic])
    }

    pub fn open_after_checkpoints(
        path: impl AsRef<Path>,
        magics: &[&[u8; 8]],
    ) -> Result<(Self, Vec<LedgerEntry>), LedgerError> {
        Self::open_verified(path.as_ref(), 0, Some(magics))
    }

    pub fn tip(&self) -> (u64, [u8; 32]) {
        (self.sequence, self.head_hash)
    }

    fn open_verified(
        path: &Path,
        after_sequence: u64,
        checkpoint_magics: Option<&[&[u8; 8]]>,
    ) -> Result<(Self, Vec<LedgerEntry>), LedgerError> {
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(lock_path(path))?;
        if let Err(err) = lock.try_lock_exclusive() {
            return Err(
                if err.kind() == io::ErrorKind::WouldBlock
                    || err.raw_os_error() == fs2::lock_contended_error().raw_os_error()
                {
                    LedgerError::WriterLocked
                } else {
                    LedgerError::Io(err)
                },
            );
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
            return Err(LedgerError::Configuration(
                "synchronous=FULL was not applied",
            ));
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
            [],
            |r| r.get(0),
        )?;
        if trigger_count != 2 {
            return Err(LedgerError::Configuration("append-only guards missing"));
        }
        let after_sequence = if let Some(magics) = checkpoint_magics {
            let mut latest = 0;
            for magic in magics {
                let sequence: i64 = conn.query_row("SELECT sequence-1 FROM ledger_events WHERE substr(event_bytes,1,8)=?1 ORDER BY sequence DESC LIMIT 1",
                    [magic.as_slice()], |row| row.get(0)).optional()?.unwrap_or(0);
                latest = latest.max(sequence);
            }
            latest
                .try_into()
                .map_err(|_| LedgerError::Configuration("invalid checkpoint sequence"))?
        } else {
            after_sequence
        };
        let (sequence, head_hash, events) = load_verified(&conn, after_sequence)?;
        Ok((
            Self {
                conn,
                path: std::fs::canonicalize(path)?,
                _writer_lock: lock,
                sequence,
                head_hash,
            },
            events,
        ))
    }

    /// Commit raw, already validated event bytes before returning an identity.
    /// No venue action may be attempted if this returns an error.
    pub fn append(&mut self, event_bytes: &[u8]) -> Result<LedgerEntry, LedgerError> {
        self.append_identified(event_bytes, &[])
    }

    /// Update the disposable identity index in the same commit as its authoritative bytes.
    pub fn append_identified(
        &mut self,
        event_bytes: &[u8],
        identities: &[(&str, &[u8])],
    ) -> Result<LedgerEntry, LedgerError> {
        if event_bytes.is_empty() || event_bytes.len() > MAX_EVENT_BYTES {
            return Err(LedgerError::InvalidSize(event_bytes.len()));
        }
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: Option<(i64, Vec<u8>)> = tx
            .query_row(
                "SELECT sequence,event_hash FROM ledger_events ORDER BY sequence DESC LIMIT 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let consistent = match current {
            None => self.sequence == 0 && self.head_hash == GENESIS,
            Some((seq, hash)) => {
                seq >= 1
                    && seq as u64 == self.sequence
                    && checked_hash(hash, self.sequence)? == self.head_hash
            }
        };
        if !consistent {
            return Err(LedgerError::Integrity {
                sequence: self.sequence + 1,
                reason: "head changed outside writer",
            });
        }
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or(LedgerError::Configuration("sequence exhausted"))?;
        let sequence_i64 = i64::try_from(sequence)
            .map_err(|_| LedgerError::Configuration("sequence exhausted"))?;
        let previous_hash = self.head_hash;
        let event_hash = hash_event(&previous_hash, event_bytes);
        tx.execute(
            "INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?1,?2,?3,?4)",
            params![sequence_i64, event_bytes, previous_hash.as_slice(), event_hash.as_slice()],
        )?;
        let indexed: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_identity_tip')", [], |row| row.get(0))?;
        if indexed {
            let consistent: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM ledger_identity_tip WHERE singleton=1 AND sequence=?1 AND event_hash=?2)", params![sqlite_sequence(self.sequence)?, self.head_hash.as_slice()], |row| row.get(0))?;
            if !consistent {
                return Err(LedgerError::Configuration(
                    "identity index does not cover the committed prefix",
                ));
            }
            for (scope, key) in identities {
                tx.execute("INSERT OR IGNORE INTO ledger_identities(scope,identity,sequence) VALUES(?1,?2,?3)", params![scope,key,sequence_i64])?;
            }
            tx.execute(
                "UPDATE ledger_identity_tip SET sequence=?1,event_hash=?2 WHERE singleton=1",
                params![sequence_i64, event_hash.as_slice()],
            )?;
        } else if !identities.is_empty() {
            return Err(LedgerError::Configuration(
                "identity index has not been verified",
            ));
        }
        tx.commit()?;
        self.sequence = sequence;
        self.head_hash = event_hash;
        Ok(LedgerEntry {
            sequence,
            event_bytes: event_bytes.to_vec(),
            previous_hash,
            event_hash,
        })
    }

    pub fn audit_path(&self) -> PathBuf {
        self.path.clone()
    }

    /// Startup already verified the whole chain; retain only a committed checkpoint's named pages.
    pub fn checkpoint_pages(&self, first: u64, last: u64) -> Result<Vec<LedgerEntry>, LedgerError> {
        if first == 0 || last < first || last > self.sequence {
            return Err(LedgerError::Configuration("invalid checkpoint page range"));
        }
        let mut stmt = self.conn.prepare("SELECT sequence,event_bytes,previous_hash,event_hash FROM ledger_events WHERE sequence BETWEEN ?1 AND ?2 ORDER BY sequence")?;
        let mut rows = stmt.query(params![sqlite_sequence(first)?, sqlite_sequence(last)?])?;
        let mut result = Vec::new();
        let mut expected = first;
        let mut previous = None;
        while let Some(row) = rows.next()? {
            let sequence: i64 = row.get(0)?;
            let event_bytes: Vec<u8> = row.get(1)?;
            let previous_hash = checked_hash(row.get(2)?, expected)?;
            let event_hash = checked_hash(row.get(3)?, expected)?;
            if sequence < 1
                || sequence as u64 != expected
                || event_bytes.is_empty()
                || event_bytes.len() > MAX_EVENT_BYTES
                || previous.is_some_and(|hash| hash != previous_hash)
                || hash_event(&previous_hash, &event_bytes) != event_hash
            {
                return Err(LedgerError::Integrity {
                    sequence: expected,
                    reason: "invalid checkpoint page bytes",
                });
            }
            result.push(LedgerEntry {
                sequence: expected,
                event_bytes,
                previous_hash,
                event_hash,
            });
            previous = Some(event_hash);
            expected += 1;
        }
        if expected != last + 1 {
            return Err(LedgerError::Integrity {
                sequence: expected,
                reason: "missing checkpoint page",
            });
        }
        Ok(result)
    }

    /// Independent connection, full byte verification, full caller decode, and atomic index publication.
    /// BEGIN IMMEDIATE keeps the target prefix fixed while normal readers remain available in WAL mode.
    pub fn audit_prefix(
        path: &Path,
        expected_tip: (u64, [u8; 32]),
        mut visit: impl FnMut(&LedgerEntry, &IdentityIndex<'_>) -> Result<(), LedgerError>,
    ) -> Result<(), LedgerError> {
        let mut conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE)?;
        conn.busy_timeout(Duration::from_secs(30))?;
        conn.execute_batch("PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;")?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute_batch("CREATE TEMP TABLE audit_identities(scope TEXT NOT NULL,identity BLOB NOT NULL,sequence INTEGER NOT NULL,PRIMARY KEY(scope,identity)) WITHOUT ROWID;")?;
        let identities = IdentityIndex { conn: &tx };
        let actual_tip = visit_verified(&tx, |entry| visit(&entry, &identities))?;
        if actual_tip != expected_tip {
            return Err(LedgerError::Integrity {
                sequence: actual_tip.0,
                reason: "audit prefix changed",
            });
        }
        tx.execute_batch("CREATE TABLE IF NOT EXISTS ledger_identities(scope TEXT NOT NULL,identity BLOB NOT NULL,sequence INTEGER NOT NULL REFERENCES ledger_events(sequence),PRIMARY KEY(scope,identity)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ledger_identity_tip(singleton INTEGER PRIMARY KEY CHECK(singleton=1),sequence INTEGER NOT NULL,event_hash BLOB NOT NULL);
DELETE FROM ledger_identities;
INSERT INTO ledger_identities SELECT * FROM temp.audit_identities;
DELETE FROM ledger_identity_tip;")?;
        tx.execute(
            "INSERT INTO ledger_identity_tip VALUES(1,?1,?2)",
            params![sqlite_sequence(expected_tip.0)?, expected_tip.1.as_slice()],
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn identity_seen(&self, scope: &str, key: &[u8]) -> Result<bool, LedgerError> {
        let covered: bool = self.conn.query_row("SELECT EXISTS(SELECT 1 FROM ledger_identity_tip WHERE singleton=1 AND sequence=?1 AND event_hash=?2)", params![sqlite_sequence(self.sequence)?,self.head_hash.as_slice()], |row| row.get(0))?;
        if !covered {
            return Err(LedgerError::Configuration("identity index is not current"));
        }
        Ok(self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM ledger_identities WHERE scope=?1 AND identity=?2)",
            params![scope, key],
            |row| row.get(0),
        )?)
    }

    /// Verify a saved backup anchor against all current bytes, including checkpoint events.
    pub fn verify_anchor(&self, anchor: (u64, [u8; 32])) -> Result<(), LedgerError> {
        let mut matched = anchor == (0, GENESIS);
        let tip = visit_verified(&self.conn, |entry| {
            if entry.sequence == anchor.0 {
                matched = entry.event_hash == anchor.1;
            }
            Ok(())
        })?;
        if !matched || tip != self.tip() {
            return Err(LedgerError::Integrity {
                sequence: anchor.0,
                reason: "backup anchor does not match the verified ledger",
            });
        }
        Ok(())
    }

    /// Verify the entire chain, also detecting changes to the head while open.
    pub fn verify(&self) -> Result<[u8; 32], LedgerError> {
        let (sequence, head, _) = load_verified(&self.conn, u64::MAX)?;
        if sequence != self.sequence || head != self.head_hash {
            return Err(LedgerError::Integrity {
                sequence: self.sequence + 1,
                reason: "head changed outside writer",
            });
        }
        Ok(head)
    }

    /// Read a verified, strictly ordered suffix for one-way projections.
    pub fn replay_from(&self, after_sequence: u64) -> Result<Vec<LedgerEntry>, LedgerError> {
        let (sequence, head, events) = load_verified(&self.conn, after_sequence)?;
        if sequence != self.sequence || head != self.head_hash {
            return Err(LedgerError::Integrity {
                sequence: self.sequence + 1,
                reason: "head changed outside writer",
            });
        }
        Ok(events)
    }

    /// Diagnostic mode values; callers may not lower these settings.
    pub fn pragmas(&self) -> Result<(String, i64), LedgerError> {
        let mode = self
            .conn
            .query_row("PRAGMA journal_mode", [], |r| r.get(0))?;
        let sync = self
            .conn
            .query_row("PRAGMA synchronous", [], |r| r.get(0))?;
        Ok((mode, sync))
    }
}
