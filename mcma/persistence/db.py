"""
mcma.persistence.db -- the sole sqlite3 connection factory and forward-only
migration runner (INC-10, ADR-0005/0006, DATA_MODEL.md §1/§10).

WAL mode, foreign_keys=ON, and a busy_timeout are applied to EVERY
connection this factory returns -- there is no other way to obtain a
connection to this database from within mcma. A single application writer
(one Uvicorn worker) is an operational/deployment invariant, not something
this module can enforce by itself; INC-11's OS mutex is the real
single-writer guarantee.

Migrations are forward-only SQL files under mcma/persistence/migrations/,
named `NNNN_description.sql`, applied in filename order inside one
transaction each, and recorded in `schema_migrations`. Re-running the
runner against an already-migrated database is a no-op (idempotent) --
already-applied versions are skipped, never re-executed.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Result:
    """The rows of one statement, already fetched.

    A live sqlite3.Cursor must not escape the lock: the C layer resets a
    connection's statements when the next one runs, so a cursor fetched
    later -- after another thread has executed something -- is reading from
    a statement that may already have been reset. Materializing inside the
    lock is what makes `conn.execute(...).fetchone()` safe to write at every
    call site without each one having to know about threading.
    """

    __slots__ = ("_rows", "lastrowid", "rowcount")

    def __init__(self, rows, lastrowid, rowcount) -> None:
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, size=None):
        return list(self._rows if size is None else self._rows[:size])

    def __iter__(self):
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class SerializedConnection:
    """One sqlite3 connection, safe to use from several threads at once.

    WHY THIS EXISTS. connect()'s `check_same_thread=False` let sync FastAPI
    handlers run on Starlette's worker threads, and the note below said that
    was safe "as long as callers never share ONE connection across genuinely
    concurrent writers without serializing access". Nothing serialized it.
    With the V1 dashboard that held: it issued one request at a time. The V2
    employee UI does not -- the shell fetches accounts, claims and jobs
    concurrently on first paint and holds an SSE stream whose generator also
    reads this connection from the event loop. Several threads then drove one
    connection simultaneously and CPython's sqlite3 raised
    `InterfaceError: bad parameter or other API misuse`, surfacing wherever
    it happened to land -- in practice inside _get_principal's user lookup,
    which made an authentication failure out of a concurrency bug.

    The fix is to serialize at the connection boundary, which is the only
    place that can see every caller. An explicit transaction holds the lock
    from BEGIN through COMMIT/ROLLBACK, so a multi-statement transaction --
    transition(), acquire_lease(), a migration -- can no longer be
    interleaved with another thread's statements on the same connection.
    That is strictly stronger than what existed before, and it is what makes
    "one process, one API connection" a correct model rather than one that
    happened to work while only one request was ever in flight.

    Deliberately NOT changed: still one process, still one API connection and
    a separate runner connection, still WAL, still busy_timeout. No pool, no
    per-request connection, no thread-local connection -- each of those would
    change the single-writer and account-lease model this system's safety
    arguments rest on.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # Re-entrant: a thread inside a transaction still runs its own
        # statements through execute() and must not block on itself.
        self._lock = threading.RLock()
        self._in_transaction = False

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        with self._lock:
            self._conn.row_factory = value

    def execute(self, sql: str, parameters=()) -> _Result:
        verb = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""

        if verb == "BEGIN":
            # Held until COMMIT/ROLLBACK releases it.
            self._lock.acquire()
            try:
                result = self._run(sql, parameters)
            except BaseException:
                self._lock.release()
                raise
            self._in_transaction = True
            return result

        if verb in ("COMMIT", "END", "ROLLBACK"):
            try:
                return self._run(sql, parameters)
            finally:
                if self._in_transaction:
                    self._in_transaction = False
                    # Released even if the COMMIT itself failed: the
                    # transaction is over either way, and a leaked lock
                    # would deadlock every later request.
                    self._lock.release()

        with self._lock:
            return self._run(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters) -> _Result:
        with self._lock:
            cursor = self._conn.executemany(sql, seq_of_parameters)
            return _Result(cursor.fetchall(), cursor.lastrowid, cursor.rowcount)

    def _run(self, sql: str, parameters) -> _Result:
        cursor = self._conn.execute(sql, parameters)
        return _Result(cursor.fetchall(), cursor.lastrowid, cursor.rowcount)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def connect(db_path: Path) -> SerializedConnection:
    """Opens one connection with the mandatory PRAGMAs applied. The parent
    directory is created if missing (the DB path itself is never created
    inside a served directory -- that is a caller/config responsibility,
    see mcma.core.config.Settings.db_path).

    `check_same_thread=False`: mcma.app (FastAPI/Starlette, from INC-13's
    onboarding endpoint onward) dispatches sync request handlers onto a
    worker thread distinct from the one that opened this connection --
    sqlite3's default same-thread restriction would otherwise raise on
    every such request. Safe under this project's single-writer model (one
    Uvicorn worker, INC-11's OS mutex, WAL mode) BECAUSE the returned
    SerializedConnection serializes access; the raw connection is never
    handed out. There is still no pool -- each caller opens what it needs."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    conn = SerializedConnection(raw)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _migration_files() -> list[Path]:
    return sorted(_MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if exists is None:
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def _split_statements(sql: str) -> list[str]:
    """Splits a migration file into individual statements on top-level `;`.
    Deliberately simple: migrations in this project are plain DDL (CREATE
    TABLE/INDEX, ALTER TABLE ADD COLUMN) with no triggers, no string
    literals containing `;`, and no embedded comments after the last
    statement on a line ending in `;`. Comment lines (`--`) are dropped
    first so a `;` inside a comment can never split a statement."""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    cleaned = "\n".join(lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


class MigrationForeignKeyViolation(RuntimeError):
    """Raised when a migration's own PRAGMA foreign_key_check finds a
    violation before that migration is allowed to commit (correction
    batch, INC-12 accounts/automation_jobs rebuild). Never silently
    committed -- the migration's transaction is rolled back first."""


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    """Applies every not-yet-applied migration file, in filename order, each
    inside its own transaction (the file's DDL plus its schema_migrations
    row commit or roll back together -- SQLite DDL is transactional).
    conn.executescript() is deliberately NOT used: it commits any pending
    transaction before running and does not compose with an explicit
    BEGIN/COMMIT, which would silently defeat the atomicity this function
    promises. Returns the list of newly-applied version strings (empty if
    the database was already current -- a replay is always safe).

    `PRAGMA foreign_keys` is turned OFF for the duration of each
    migration's own transaction (SQLite refuses to change it inside an
    active transaction, so this happens immediately before BEGIN, and it
    is always restored to ON immediately after COMMIT/ROLLBACK, before
    control returns to the caller or the next migration runs) -- this is
    SQLite's own documented safe procedure for a migration that rebuilds
    a table via create-copy-drop-rename (correction batch: automation_jobs'
    CHECK constraint cannot be altered any other way). A migration that
    performs such a rebuild MUST verify PRAGMA foreign_key_check itself
    finds nothing before this function will let it commit."""
    applied = _applied_versions(conn)
    newly_applied: list[str] = []
    for path in _migration_files():
        version = path.stem
        if version in applied:
            continue
        statements = _split_statements(path.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        try:
            for statement in statements:
                conn.execute(statement)
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationForeignKeyViolation(
                    f"migration {version} left {len(violations)} foreign-key violation(s): {list(violations)!r}"
                )
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _utcnow()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
        newly_applied.append(version)
    return newly_applied


def open_database(db_path: Path) -> SerializedConnection:
    """The one entry point application code uses: connect + migrate."""
    conn = connect(db_path)
    run_migrations(conn)
    return conn
