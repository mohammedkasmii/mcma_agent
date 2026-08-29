"""
db/schema.py — SQLite Schema & Connection Management
=====================================================
Single embedded database (data/mcma.db) in WAL mode.

Implements PROJECT_ARCHITECTURE_BLUEPRINT.md §7. Replaces the flat JSON files,
which suffered unguarded read-modify-write races: two employees changing a status
in the same second silently lost one write.

Key invariants:
  - WAL mode + busy_timeout, so concurrent readers never block the poller.
  - Every business write bumps app_state['state_version'] and stamps that value
    into the touched row's changed_version, making the delta API (§7.4) possible.
  - claims are unique on (account_id, category_code, reference): the work item is
    the alert occurrence, not the physical claim (§7.2).
"""

import os
import sqlite3
from typing import Optional

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "mcma.db")

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id    TEXT PRIMARY KEY,
    entity        TEXT NOT NULL CHECK (entity IN ('MCMA','MAMDA')),
    portfolio     TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    base_url      TEXT NOT NULL,
    is_enabled    INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portal_sessions (
    account_id              TEXT PRIMARY KEY REFERENCES accounts(account_id),
    health_status           TEXT NOT NULL DEFAULT 'NEVER_AUTHENTICATED'
                                 CHECK (health_status IN
                                 ('HEALTHY','EXPIRED','NEVER_AUTHENTICATED','UNKNOWN')),
    auth_state_path         TEXT,
    last_validated_at       TEXT,
    last_successful_poll_at TEXT,
    last_poll_outcome       TEXT,
    last_error              TEXT,
    changed_version         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS claims (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id                TEXT NOT NULL REFERENCES accounts(account_id),
    category_code             TEXT NOT NULL,
    category_name             TEXT NOT NULL,
    reference                 TEXT NOT NULL,
    id_sinistre               TEXT,
    date_survenance           TEXT,
    date_survenance_raw       TEXT,
    societaire                TEXT,
    police                    TEXT,
    matricule                 TEXT,
    nature                    TEXT,
    portal_status             TEXT,
    direct_url                TEXT,
    portal_presence           TEXT NOT NULL DEFAULT 'ACTIVE'
                                   CHECK (portal_presence IN
                                   ('ACTIVE','MISSING_PENDING_CONFIRMATION','RESOLVED_ON_PORTAL')),
    consecutive_missing_polls INTEGER NOT NULL DEFAULT 0,
    first_seen_at             TEXT NOT NULL,
    last_seen_at              TEXT NOT NULL,
    changed_version           INTEGER NOT NULL DEFAULT 0,
    UNIQUE (account_id, category_code, reference)
);
CREATE INDEX IF NOT EXISTS ix_claims_version  ON claims(changed_version);
CREATE INDEX IF NOT EXISTS ix_claims_presence ON claims(account_id, portal_presence);

CREATE TABLE IF NOT EXISTS employee_actions (
    claim_id        INTEGER PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
    employee_status TEXT NOT NULL DEFAULT 'TODO'
                         CHECK (employee_status IN ('TODO','IN_PROGRESS','DONE','WAITING')),
    note            TEXT NOT NULL DEFAULT '',
    updated_by      TEXT,
    updated_at      TEXT NOT NULL,
    changed_version INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_actions_version ON employee_actions(changed_version);

CREATE TABLE IF NOT EXISTS poll_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  TEXT NOT NULL REFERENCES accounts(account_id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN
                     ('SUCCESS','PARTIAL','AUTH_FAILED','UNREACHABLE','SKIPPED_WINDOW_CLOSED')),
    error       TEXT
);
CREATE INDEX IF NOT EXISTS ix_pollruns_account ON poll_runs(account_id, started_at);

CREATE TABLE IF NOT EXISTS poll_run_categories (
    poll_run_id   INTEGER NOT NULL REFERENCES poll_runs(id) ON DELETE CASCADE,
    category_code TEXT    NOT NULL,
    category_name TEXT,
    outcome       TEXT    NOT NULL CHECK (outcome IN ('SUCCESS','FAILED','EMPTY')),
    alerts_seen   INTEGER,
    error         TEXT,
    PRIMARY KEY (poll_run_id, category_code)
);

CREATE TABLE IF NOT EXISTS automation_jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     TEXT NOT NULL REFERENCES accounts(account_id),
    claim_id       INTEGER REFERENCES claims(id),
    workflow       TEXT NOT NULL CHECK (workflow IN ('MODE_NORMAL','MODE_CONVENTIONNE')),
    execution_mode TEXT NOT NULL CHECK (execution_mode IN ('PLAN','PREVIEW','DRAFT_WRITE')),
    status         TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK (status IN ('QUEUED','RUNNING','REVIEW_REQUIRED','FAILED','CANCELLED')),
    allowed_writes TEXT NOT NULL DEFAULT '[]',
    requested_by   TEXT,
    payload_json   TEXT,
    result_json    TEXT,
    error_code     TEXT,
    created_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor      TEXT NOT NULL,
    account_id TEXT,
    claim_id   INTEGER,
    job_id     INTEGER,
    details    TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_events(ts);

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    """
    Opens a connection with the pragmas this system depends on.

    check_same_thread=False because FastAPI's threadpool may hand a connection
    to a different worker thread; all writes are serialised through the
    repository layer's single connection plus SQLite's own locking.
    """
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Creates all tables and seeds the state version. Idempotent."""
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO app_state(key, value) VALUES ('state_version', '0')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO app_state(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()


def next_version(conn: sqlite3.Connection) -> int:
    """
    Bumps and returns the global monotonic state version.

    Must be called inside the same transaction as the business write that uses
    it, so a row's changed_version can never point at a version that was never
    committed (§7.4).
    """
    conn.execute(
        "UPDATE app_state SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
        "WHERE key = 'state_version'"
    )
    row = conn.execute(
        "SELECT value FROM app_state WHERE key = 'state_version'"
    ).fetchone()
    return int(row["value"])


def current_version(conn: sqlite3.Connection) -> int:
    """Reads the current state version without bumping it."""
    row = conn.execute(
        "SELECT value FROM app_state WHERE key = 'state_version'"
    ).fetchone()
    return int(row["value"]) if row else 0
