"""The offline first-admin command: hidden prompts, refusal rules, lock,
transaction and secret hygiene."""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from mcma.app import first_admin_cli
from mcma.app.auth import users
from mcma.core.mutex import MutexAcquisitionError, PortableTestOnlyMutex
from mcma.persistence.db import open_database

SECRET = "tr0ub4dor & 3 horses staple"
REPO = Path(__file__).resolve().parents[3]


class Prompts:
    """Stands in for getpass: records the prompts, returns scripted answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0)


@pytest.fixture()
def env(tmp_path):
    (tmp_path / "data").mkdir()
    return {"MCMA_DB_PATH": str(tmp_path / "data" / "mcma.sqlite3"),
            "MCMA_INSTANCE_LOCK_PATH": str(tmp_path / "data" / "mcma.lock")}


def _run(argv, env, tmp_path, getpass_fn=None, *, tty=True, name=None):
    out, err = io.StringIO(), io.StringIO()
    unique = name or f"cli-{tmp_path.name}"
    code = first_admin_cli.run(
        argv, environ=env, getpass_fn=getpass_fn or Prompts(SECRET, SECRET), is_tty=tty, stdout=out, stderr=err,
        mutex_factory=lambda path: PortableTestOnlyMutex(unique),
    )
    return code, out.getvalue(), err.getvalue()


def _db(env):
    return open_database(Path(env["MCMA_DB_PATH"]))


def test_creates_the_admin_and_grants_every_canonical_account(env, tmp_path):
    code, out, err = _run(["Boss"], env, tmp_path)
    assert code == 0 and err == ""
    assert "boss" in out and "4 comptes portail" in out
    conn = _db(env)
    try:
        [row] = conn.execute("SELECT user_id, username, role, active, password_hash FROM users").fetchall()
        assert (row["username"], row["role"], row["active"]) == ("boss", "admin", 1)
        assert conn.execute("SELECT COUNT(*) AS c FROM user_account_access WHERE user_id = ?", (row["user_id"],)).fetchone()["c"] == 4
        assert conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 4
    finally:
        conn.close()


def test_the_password_is_prompted_twice_hidden_and_never_via_input(env, tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(AssertionError("visible input() used")))
    prompts = Prompts(SECRET, SECRET)
    assert _run(["boss"], env, tmp_path, prompts)[0] == 0
    assert prompts.prompts == ["Mot de passe : ", "Confirmez le mot de passe : "]
    assert first_admin_cli.getpass.getpass is __import__("getpass").getpass            # the real hidden-prompt primitive


def test_default_prompt_function_is_getpass():
    import getpass
    import inspect

    assert inspect.signature(first_admin_cli.run).parameters["getpass_fn"].default is getpass.getpass


def test_mismatched_confirmation_creates_nothing(env, tmp_path):
    code, out, err = _run(["boss"], env, tmp_path, Prompts(SECRET, SECRET + "x"))
    assert code == 1 and "pas identiques" in err and out == ""
    conn = _db(env)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 0   # no canonical rows either
    finally:
        conn.close()


@pytest.mark.parametrize("password, fragment", [
    ("short", "au moins 12"), ("boss-is-the-admin!", "nom d'utilisateur"), ("aaaaaaaaaaaaaaaa", "trop simple"),
])
def test_password_policy_is_enforced_with_french_errors(env, tmp_path, password, fragment):
    code, out, err = _run(["boss"], env, tmp_path, Prompts(password, password))
    assert code == 1 and fragment in err and password not in err + out
    assert _users(env) == 0 and _accounts(env) == 0


@pytest.mark.parametrize("name", ["", "ab", "bad name", "a;b", "é"])
def test_invalid_usernames_are_refused_before_any_prompt(env, tmp_path, name):
    prompts = Prompts()
    code, out, err = _run([name], env, tmp_path, prompts)
    assert code == 1 and "nom d'utilisateur" in err.lower() and prompts.prompts == []


def _accounts(env):
    conn = _db(env)
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
    finally:
        conn.close()


def _users(env):
    conn = _db(env)
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    finally:
        conn.close()


def test_refuses_when_any_user_exists_without_prompting_or_changing_anything(env, tmp_path):
    assert _run(["boss"], env, tmp_path)[0] == 0
    prompts = Prompts(SECRET, SECRET)
    code, out, err = _run(["second"], env, tmp_path, prompts)
    assert code == 1 and "existent déjà" in err and "Rien n'a été modifié" in err
    assert prompts.prompts == [] and _users(env) == 1 and _accounts(env) == 4


def test_a_held_application_lock_makes_it_refuse(env, tmp_path):
    holder = PortableTestOnlyMutex("lock-held-elsewhere")
    holder.acquire()
    try:
        out, err = io.StringIO(), io.StringIO()
        prompts = Prompts(SECRET, SECRET)
        code = first_admin_cli.run(["boss"], environ=env, getpass_fn=prompts, is_tty=True, stdout=out, stderr=err,
                                   mutex_factory=lambda path: PortableTestOnlyMutex("lock-held-elsewhere"))
    finally:
        holder.release()
    assert code == 1 and "en cours d'exécution" in err.getvalue() and prompts.prompts == []
    assert not Path(env["MCMA_DB_PATH"]).exists()                     # not even created


def test_the_lock_is_released_afterwards(env, tmp_path):
    assert _run(["boss"], env, tmp_path, name="same-lock")[0] == 0
    assert _run(["other"], env, tmp_path, name="same-lock")[0] == 1   # refused for USERS_EXIST, not for the lock
    PortableTestOnlyMutex("same-lock").acquire()                      # would raise if still held


def test_a_failure_mid_way_rolls_everything_back(env, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError(f"disk exploded near {SECRET}")

    monkeypatch.setattr(users, "_audit", boom)
    code, out, err = _run(["boss"], env, tmp_path)
    assert code == 1 and "RuntimeError" in err and SECRET not in err + out       # type only, no message
    conn = _db(env)
    try:
        for table in ("accounts", "users", "user_account_access", "audit_events"):
            assert conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] == 0
    finally:
        conn.close()


def test_a_non_interactive_stdin_is_refused_so_no_password_can_be_piped(env, tmp_path):
    prompts = Prompts(SECRET, SECRET)
    code, out, err = _run(["boss"], env, tmp_path, prompts, tty=False)
    assert code == 1 and "terminal interactif" in err and prompts.prompts == []


def test_missing_configuration_and_directory_are_reported(tmp_path):
    assert _run(["boss"], {}, tmp_path)[0] == 1
    code, _, err = _run(["boss"], {"MCMA_DB_PATH": str(tmp_path / "nope" / "x.db"),
                                   "MCMA_INSTANCE_LOCK_PATH": str(tmp_path / "nope" / "x.lock")}, tmp_path)
    assert code == 1 and "introuvable" in err


@pytest.mark.parametrize("argv", [["--password", "x"], ["--password=x", "boss"], ["-p", "x"], ["boss", "extra"], []])
def test_the_command_line_can_never_carry_a_password(env, tmp_path, argv):
    code, out, err = _run(argv, env, tmp_path, Prompts())
    assert code == 2 and out == ""
    assert not Path(env["MCMA_DB_PATH"]).exists()


def test_secrets_and_hashes_never_appear_in_any_output(env, tmp_path):
    seen = []
    for index, answers in enumerate(((SECRET, "different"), ("short", "short"), (SECRET, SECRET), (SECRET, SECRET))):
        code, out, err = _run(["boss"], env, tmp_path, Prompts(*answers), name=f"n-{index}")
        seen.append(out + err)
    conn = _db(env)
    try:
        hashes = [r["password_hash"] for r in conn.execute("SELECT password_hash FROM users").fetchall()]
    finally:
        conn.close()
    blob = chr(10).join(seen)
    assert SECRET not in blob and "different" not in blob
    assert len(hashes) == 1 and hashes[0] not in blob and "argon2" not in blob


def test_real_process_refuses_non_interactive_use_and_leaks_nothing(tmp_path):
    """A real interpreter, real argv/stdio: stdin is not a terminal, so it
    refuses; the (would-be) secret is never in argv or any output."""
    (tmp_path / "d").mkdir()
    environment = {**__import__("os").environ, "MCMA_DB_PATH": str(tmp_path / "d" / "m.db"),
                   "MCMA_INSTANCE_LOCK_PATH": str(tmp_path / "d" / "m.lock"), "PYTHONUTF8": "1"}
    argv = [sys.executable, "-m", "mcma.app.first_admin_cli", "boss"]
    result = subprocess.run(argv, cwd=REPO, env=environment, input=f"{SECRET}\n{SECRET}\n", capture_output=True, text=True, timeout=120)
    assert result.returncode == 1 and "terminal interactif" in result.stderr
    assert SECRET not in " ".join(argv) + result.stdout + result.stderr
    assert not (tmp_path / "d" / "m.db").exists()
    assert SECRET not in "".join(environment.values())


def test_the_command_is_not_reachable_through_the_web_app():
    import mcma.app.central_server as central
    import mcma.app.composition as composition

    for module in (central, composition):
        assert "first_admin" not in Path(module.__file__).read_text(encoding="utf-8")
