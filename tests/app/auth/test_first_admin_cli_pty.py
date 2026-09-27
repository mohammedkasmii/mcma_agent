"""The real command on a real pseudo-terminal (POSIX): the password prompts
do not echo, and the typed password appears nowhere in the terminal output.
Skipped on Windows, where there is no pty; it runs on Linux and in the
deployment image."""

import os
import select
import sys
import time
from pathlib import Path

import pytest

pty = pytest.importorskip("pty", reason="POSIX pseudo-terminals only")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="no pty on Windows")

REPO = Path(__file__).resolve().parents[3]
SECRET = "pty-secret phrase 12345"


def _drive(tmp_path, answers):
    (tmp_path / "d").mkdir(exist_ok=True)
    env = {**os.environ, "MCMA_DB_PATH": str(tmp_path / "d" / "m.db"),
           "MCMA_INSTANCE_LOCK_PATH": str(tmp_path / "d" / "m.lock"), "PYTHONUTF8": "1"}
    pid, fd = pty.fork()
    if pid == 0:                                        # child: the real command, on the pty
        os.chdir(REPO)
        os.execvpe(sys.executable, [sys.executable, "-m", "mcma.app.first_admin_cli", "boss"], env)
    transcript = b""
    pending = list(answers)
    deadline = time.time() + 90
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            transcript += chunk
            if pending and transcript.rstrip().endswith(b":"):
                os.write(fd, pending.pop(0).encode() + b"\n")
                transcript += b"<ANSWER-SENT>"
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), transcript.decode("utf-8", "replace")


def test_the_password_is_typed_hidden_and_never_echoed(tmp_path):
    code, transcript = _drive(tmp_path, [SECRET, SECRET])
    assert code == 0, transcript
    assert "Mot de passe :" in transcript and "Confirmez le mot de passe :" in transcript
    assert SECRET not in transcript                     # no echo on the terminal
    assert "boss" in transcript and "4 comptes portail" in transcript
    from mcma.persistence.db import open_database

    conn = open_database(tmp_path / "d" / "m.db")
    try:
        rows = conn.execute("SELECT username, role FROM users").fetchall()
        assert [(r["username"], r["role"]) for r in rows] == [("boss", "admin")]
    finally:
        conn.close()


def test_a_mismatch_on_a_real_terminal_creates_nothing(tmp_path):
    code, transcript = _drive(tmp_path, [SECRET, SECRET + "x"])
    assert code == 1 and "pas identiques" in transcript and SECRET not in transcript
    from mcma.persistence.db import open_database

    conn = open_database(tmp_path / "d" / "m.db")
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0
    finally:
        conn.close()
