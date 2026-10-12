"""write_transaction: rollback on body failure AND on COMMIT failure, the
original exception always wins, BaseException still rolls back."""

import sqlite3

import pytest

from mcma.app.auth.users import write_transaction


class ScriptedConn:
    def __init__(self, fail_on=(), rollback_fails=False):
        self.statements, self.fail_on, self.rollback_fails = [], set(fail_on), rollback_fails

    def execute(self, sql):
        self.statements.append(sql)
        if sql == "ROLLBACK" and self.rollback_fails:
            raise RuntimeError("rollback broke")
        if sql in self.fail_on:
            raise RuntimeError(f"{sql} failed")


def test_success_is_begin_then_commit_only():
    conn = ScriptedConn()
    with write_transaction(conn):
        pass
    assert conn.statements == ["BEGIN IMMEDIATE", "COMMIT"]


def test_begin_failure_propagates_without_rollback():
    conn = ScriptedConn(fail_on={"BEGIN IMMEDIATE"})
    with pytest.raises(RuntimeError, match="BEGIN IMMEDIATE failed"):
        with write_transaction(conn):
            pytest.fail("body must not run")
    assert conn.statements == ["BEGIN IMMEDIATE"]


def test_body_exception_rolls_back_and_propagates():
    conn = ScriptedConn()
    with pytest.raises(ValueError):
        with write_transaction(conn):
            raise ValueError("body")
    assert conn.statements == ["BEGIN IMMEDIATE", "ROLLBACK"]


def test_commit_failure_attempts_rollback_and_the_commit_error_wins():
    conn = ScriptedConn(fail_on={"COMMIT"})
    with pytest.raises(RuntimeError, match="COMMIT failed"):
        with write_transaction(conn):
            pass
    assert conn.statements == ["BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"]


def test_secondary_rollback_error_never_replaces_the_original():
    body = ScriptedConn(rollback_fails=True)
    with pytest.raises(ValueError, match="original"):
        with write_transaction(body):
            raise ValueError("original")
    commit = ScriptedConn(fail_on={"COMMIT"}, rollback_fails=True)
    with pytest.raises(RuntimeError, match="COMMIT failed"):
        with write_transaction(commit):
            pass


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_base_exceptions_still_roll_back(exc):
    conn = ScriptedConn()
    with pytest.raises(exc):
        with write_transaction(conn):
            raise exc()
    assert conn.statements == ["BEGIN IMMEDIATE", "ROLLBACK"]


def test_a_real_commit_failure_leaves_the_connection_out_of_a_transaction(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE child (pid INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)")
    with pytest.raises(sqlite3.IntegrityError):
        with write_transaction(conn):
            conn.execute("INSERT INTO child VALUES (99)")      # violates the FK only at COMMIT
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0
    with write_transaction(conn):                              # and the connection is perfectly usable
        conn.execute("INSERT INTO parent VALUES (1)")
    assert conn.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 1
    conn.close()
