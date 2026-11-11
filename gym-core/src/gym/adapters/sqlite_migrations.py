"""Execute fixed schema scripts without releasing the caller's migration lock."""
import sqlite3
from time import monotonic, sleep


def enable_wal(conn: sqlite3.Connection) -> None:
    # First-open journal changes can return BUSY without honoring busy_timeout.
    deadline = monotonic() + 5
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY or monotonic() >= deadline:
                raise
            sleep(0.01)


def execute_schema(conn: sqlite3.Connection, script: str) -> None:
    # executescript commits first, even inside an explicit transaction.
    statement = ""
    for char in script:
        statement += char
        if char == ";" and sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete SQLite schema statement")
