import json
from pathlib import Path

import pytest

from mcma.app.workstation_runner.session_store import (
    MAX_CIPHERTEXT_BYTES, MAX_ENVELOPE_PLAINTEXT_BYTES, MAX_STORAGE_STATE_BYTES,
    SESSION_FORMAT_VERSION, InvalidStorageState, UnknownWorkstationAccount,
    WorkstationSessionStore, default_sessions_dir, validate_storage_state,
)
from mcma.core.dpapi import DpapiUnavailable
from tests.app.workstation_runner._fakes import InMemoryCryptoBackend, WrongUserCryptoBackend

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"

_MARKER = "SECRET-COOKIE-VALUE-MARKER-zzz"


def _storage_state(marker: str = _MARKER) -> dict:
    return {
        "cookies": [{"name": "session", "value": marker, "domain": "sinauto.mamda-mcma.ma", "path": "/"}],
        "origins": [],
    }


# --------------------------------------------------------------------- #
# round trip / isolation
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("account_id", [OUJDA, NADOR])
def test_save_then_load_round_trips_for_both_allowed_accounts(tmp_path, account_id):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    state = _storage_state()
    store.save(account_id, state)
    assert store.load(account_id) == state


def test_oujda_and_nador_sessions_are_isolated(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state("oujda-marker"))
    store.save(NADOR, _storage_state("nador-marker"))
    assert store.load(OUJDA)["cookies"][0]["value"] == "oujda-marker"
    assert store.load(NADOR)["cookies"][0]["value"] == "nador-marker"
    store.clear(OUJDA)
    assert store.load(OUJDA) is None
    assert store.load(NADOR) is not None


def test_load_missing_file_returns_none(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    assert store.load(OUJDA) is None
    assert store.has_saved_session(OUJDA) is False


def test_separate_file_per_account(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state())
    store.save(NADOR, _storage_state())
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [f"{NADOR}.bin", f"{OUJDA}.bin"]


# --------------------------------------------------------------------- #
# account binding / unknown accounts
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_account", ["acct-mamda-oujda", "acct-mcma-fes", "", "ACCT-MCMA-OUJDA", None, 123])
def test_disallowed_account_ids_are_rejected(tmp_path, bad_account):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    with pytest.raises(UnknownWorkstationAccount):
        store.save(bad_account, _storage_state())
    with pytest.raises(UnknownWorkstationAccount):
        store.load(bad_account)


def test_wrong_account_cannot_decrypt_or_reuse_another_accounts_envelope(tmp_path):
    """Copying acct-mcma-oujda's ciphertext file onto acct-mcma-nador's path
    must not let it be read back as Nador's session: the account id is
    bound INSIDE the encrypted envelope, not just implied by the filename."""
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state("oujda-marker"))
    oujda_bytes = (tmp_path / f"{OUJDA}.bin").read_bytes()
    (tmp_path / f"{NADOR}.bin").write_bytes(oujda_bytes)
    assert store.load(NADOR) is None


# --------------------------------------------------------------------- #
# corruption / version / shape failures -- fail closed
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("corrupt", [
    lambda b: b[:-5],
    lambda b: b[:10] + b"\xff" * 10 + b[20:],
    lambda b: b"not even our format" + b,
    lambda b: b"",
])
def test_load_fails_closed_on_corrupt_ciphertext(tmp_path, corrupt):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state())
    path = tmp_path / f"{OUJDA}.bin"
    path.write_bytes(corrupt(path.read_bytes()))
    assert store.load(OUJDA) is None


def test_load_fails_closed_on_wrong_windows_user(tmp_path):
    WorkstationSessionStore(tmp_path, InMemoryCryptoBackend()).save(OUJDA, _storage_state())
    reader = WorkstationSessionStore(tmp_path, WrongUserCryptoBackend())
    assert reader.load(OUJDA) is None


def test_load_fails_closed_on_unsupported_version(tmp_path):
    backend = InMemoryCryptoBackend()
    path = tmp_path / f"{OUJDA}.bin"
    payload = json.dumps({
        "format_version": 999, "account_id": OUJDA, "storage_state": _storage_state(),
    }).encode("utf-8")
    path.write_bytes(backend.protect(payload))
    assert WorkstationSessionStore(tmp_path, backend).load(OUJDA) is None


@pytest.mark.parametrize("bad_state", [
    "not-a-dict",
    123,
    None,
    {"cookies": "not-a-list", "origins": []},
    {"cookies": [], "origins": "not-a-list"},
    {"cookies": [], "origins": [], "unexpected": "field"},
])
def test_save_rejects_invalid_storage_state_shape(tmp_path, bad_state):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    with pytest.raises(InvalidStorageState):
        store.save(OUJDA, bad_state)
    assert not (tmp_path / f"{OUJDA}.bin").exists()


def test_save_rejects_oversized_storage_state(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    huge = {"cookies": [{"name": "x", "value": "y" * MAX_STORAGE_STATE_BYTES}], "origins": []}
    with pytest.raises(InvalidStorageState):
        store.save(OUJDA, huge)


def test_load_fails_closed_on_oversized_ciphertext_file(tmp_path):
    """An absurdly large file must be refused on its stat()'d size alone --
    never read into memory or handed to DPAPI/json."""
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    path = tmp_path / f"{OUJDA}.bin"
    path.write_bytes(b"x" * (MAX_CIPHERTEXT_BYTES + 1))
    assert store.load(OUJDA) is None


def test_load_fails_closed_on_oversized_decrypted_plaintext(tmp_path):
    """A ciphertext file small enough to pass the file-size bound but whose
    DECRYPTED plaintext exceeds the envelope bound must still fail closed,
    without ever reaching json.loads on the oversized blob."""
    backend = InMemoryCryptoBackend()
    path = tmp_path / f"{OUJDA}.bin"
    huge_plaintext = b"a" * (MAX_ENVELOPE_PLAINTEXT_BYTES + 1000)
    path.write_bytes(backend.protect(huge_plaintext))
    assert WorkstationSessionStore(tmp_path, backend).load(OUJDA) is None


def test_load_fails_closed_when_read_bytes_exceeds_the_stat_checked_size(tmp_path, monkeypatch):
    """stat()/read() race: the file can grow between the size check and the
    actual read. The bytes read() actually returns must be re-checked
    against MAX_CIPHERTEXT_BYTES before ever reaching DPAPI -- proven here
    by asserting unprotect() is never called."""

    class _CountingBackend(InMemoryCryptoBackend):
        def __init__(self) -> None:
            super().__init__()
            self.unprotect_calls = 0

        def unprotect(self, data: bytes) -> bytes:
            self.unprotect_calls += 1
            return super().unprotect(data)

    backend = _CountingBackend()
    store = WorkstationSessionStore(tmp_path, backend)
    path = tmp_path / f"{OUJDA}.bin"
    path.write_bytes(b"x" * (MAX_CIPHERTEXT_BYTES + 1))

    class _LyingStatResult:
        st_size = MAX_CIPHERTEXT_BYTES - 1  # lies: reports an in-bound size

    original_stat = Path.stat

    def lying_stat(self, *args, **kwargs):
        if self == path:
            return _LyingStatResult()
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", lying_stat)
    assert store.load(OUJDA) is None
    assert backend.unprotect_calls == 0


@pytest.mark.parametrize("bad_cookie", [
    {"name": "s", "value": "v", "domain": "d"},  # missing "path"
    {"name": "s", "value": "v", "domain": "d", "path": "/", "unexpected": "x"},
    {"name": 1, "value": "v", "domain": "d", "path": "/"},
    {"name": "s", "value": "v", "domain": "d", "path": "/", "expires": "not-a-number"},
    {"name": "s", "value": "v", "domain": "d", "path": "/", "expires": True},
    {"name": "s", "value": "v", "domain": "d", "path": "/", "httpOnly": "yes"},
    {"name": "s", "value": "v", "domain": "d", "path": "/", "sameSite": "Nope"},
    "not-a-dict",
    ["nested", "list"],
    {"name": "s", "value": {"nested": "object"}, "domain": "d", "path": "/"},
])
def test_save_rejects_malformed_nested_cookie_entries(tmp_path, bad_cookie):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    with pytest.raises(InvalidStorageState):
        store.save(OUJDA, {"cookies": [bad_cookie], "origins": []})


@pytest.mark.parametrize("bad_expires", [float("nan"), float("inf"), float("-inf")])
def test_save_rejects_non_finite_cookie_expires(tmp_path, bad_expires):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    bad_cookie = {"name": "s", "value": "v", "domain": "d", "path": "/", "expires": bad_expires}
    with pytest.raises(InvalidStorageState):
        store.save(OUJDA, {"cookies": [bad_cookie], "origins": []})


@pytest.mark.parametrize("bad_origin", [
    {"origin": 1, "localStorage": []},
    {"origin": "https://x", "localStorage": "not-a-list"},
    {"origin": "https://x", "localStorage": [{"name": "k"}]},
    {"origin": "https://x", "localStorage": [{"name": "k", "value": 1}]},
    {"origin": "https://x", "unexpected": "field"},
    {"localStorage": []},  # missing "origin"
    "not-a-dict",
    {"origin": "https://x", "localStorage": [{"nested": {"deeply": "not allowed"}}]},
])
def test_save_rejects_malformed_nested_origin_entries(tmp_path, bad_origin):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    with pytest.raises(InvalidStorageState):
        store.save(OUJDA, {"cookies": [], "origins": [bad_origin]})


def test_validate_storage_state_accepts_full_playwright_shaped_state():
    state = {
        "cookies": [{
            "name": "session", "value": "v", "domain": "sinauto.mamda-mcma.ma", "path": "/",
            "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax",
        }],
        "origins": [{
            "origin": "https://sinauto.mamda-mcma.ma",
            "localStorage": [{"name": "k", "value": "v"}],
        }],
    }
    assert validate_storage_state(state) == state


def test_validate_storage_state_accepts_origin_without_local_storage():
    state = {"cookies": [], "origins": [{"origin": "https://sinauto.mamda-mcma.ma"}]}
    assert validate_storage_state(state) == state


@pytest.mark.parametrize("bad_state", [
    {},
    {"cookies": []},           # missing "origins"
    {"origins": []},           # missing "cookies"
])
def test_save_rejects_storage_state_missing_a_required_top_level_key(tmp_path, bad_state):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    with pytest.raises(InvalidStorageState):
        store.save(OUJDA, bad_state)


def test_validate_storage_state_requires_both_keys_but_accepts_them_together():
    state = {"cookies": [], "origins": []}
    assert validate_storage_state(state) == state
    with pytest.raises(InvalidStorageState):
        validate_storage_state({"cookies": []})
    with pytest.raises(InvalidStorageState):
        validate_storage_state({"origins": []})
    with pytest.raises(InvalidStorageState):
        validate_storage_state({})


def test_unknown_account_error_has_a_fixed_message_and_does_not_retain_the_bad_value(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    bad = "SECRET-MARKER-IN-BAD-ACCOUNT-ID"
    try:
        store.save(bad, _storage_state())
    except UnknownWorkstationAccount as exc:
        assert bad not in str(exc)
        assert bad not in repr(exc)
        assert not hasattr(exc, "account_id")
    else:
        pytest.fail("expected UnknownWorkstationAccount")


def test_load_fails_closed_on_malformed_decrypted_shape(tmp_path):
    """A structurally invalid decrypted envelope must make load() return
    None, never raise or return a partially-trusted value."""
    backend = InMemoryCryptoBackend()
    path = tmp_path / f"{OUJDA}.bin"
    payload = json.dumps({
        "format_version": SESSION_FORMAT_VERSION, "account_id": OUJDA,
        "storage_state": {"cookies": "not-a-list", "origins": []},
    }).encode("utf-8")
    path.write_bytes(backend.protect(payload))
    assert WorkstationSessionStore(tmp_path, backend).load(OUJDA) is None


def test_validate_storage_state_accepts_a_well_formed_empty_state():
    state = {"cookies": [], "origins": []}
    assert validate_storage_state(state) == state


# --------------------------------------------------------------------- #
# atomic replace / temp-file hygiene
# --------------------------------------------------------------------- #


def test_save_is_atomic_no_tmp_file_left_behind(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state())
    leftovers = [p for p in tmp_path.iterdir() if p.name != f"{OUJDA}.bin"]
    assert leftovers == []


def test_write_failure_preserves_the_previous_valid_session_and_leaves_no_temp_file(tmp_path, monkeypatch):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state("first-good-session"))

    original_open = Path.open

    def failing_open(self, *args, **kwargs):
        if self.name.endswith(".session.tmp"):
            raise OSError("simulated disk full")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(OSError):
        store.save(OUJDA, _storage_state("second-session-should-not-land"))
    monkeypatch.undo()

    assert store.load(OUJDA)["cookies"][0]["value"] == "first-good-session"
    leftovers = [p for p in tmp_path.iterdir() if p.name != f"{OUJDA}.bin"]
    assert leftovers == []


def test_fsync_failure_preserves_the_previous_valid_session_and_leaves_no_temp_file(tmp_path, monkeypatch):
    """The completed temp file must be flushed/synced to disk before the
    atomic replace -- if that durability step fails, the replace must never
    happen and no temp file may be left behind."""
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state("first-good-session"))

    def failing_fsync(fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr("mcma.app.workstation_runner.session_store.os.fsync", failing_fsync)
    with pytest.raises(OSError):
        store.save(OUJDA, _storage_state("second-session-should-not-land"))
    monkeypatch.undo()

    assert store.load(OUJDA)["cookies"][0]["value"] == "first-good-session"
    leftovers = [p for p in tmp_path.iterdir() if p.name != f"{OUJDA}.bin"]
    assert leftovers == []


def test_replace_failure_preserves_the_previous_valid_session_and_leaves_no_temp_file(tmp_path, monkeypatch):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state("first-good-session"))

    def failing_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("mcma.app.workstation_runner.session_store.os.replace", failing_replace)
    with pytest.raises(OSError):
        store.save(OUJDA, _storage_state("second-session-should-not-land"))
    monkeypatch.undo()

    assert store.load(OUJDA)["cookies"][0]["value"] == "first-good-session"
    leftovers = [p for p in tmp_path.iterdir() if p.name != f"{OUJDA}.bin"]
    assert leftovers == []


def test_save_propagates_dpapi_failure_and_creates_no_file(tmp_path):
    class _FailingBackend:
        def protect(self, data):
            raise DpapiUnavailable("simulated DPAPI failure")

        def unprotect(self, data):
            raise NotImplementedError

    store = WorkstationSessionStore(tmp_path, _FailingBackend())
    with pytest.raises(DpapiUnavailable):
        store.save(OUJDA, _storage_state())
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------- #
# clear-one / clear-all
# --------------------------------------------------------------------- #


def test_clear_removes_only_the_named_account(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state())
    store.save(NADOR, _storage_state())
    store.clear(OUJDA)
    assert store.load(OUJDA) is None
    assert store.load(NADOR) is not None


def test_clear_on_missing_file_is_a_noop(tmp_path):
    WorkstationSessionStore(tmp_path, InMemoryCryptoBackend()).clear(OUJDA)


def test_clear_all_removes_every_account(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state())
    store.save(NADOR, _storage_state())
    store.clear_all()
    assert store.load(OUJDA) is None
    assert store.load(NADOR) is None


def test_default_sessions_dir_uses_local_app_data(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\fake\localappdata")
    result = default_sessions_dir()
    assert str(result) == r"C:\fake\localappdata\MCMA Runner\sessions"


def test_default_sessions_dir_requires_local_app_data(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(RuntimeError):
        default_sessions_dir()


# --------------------------------------------------------------------- #
# leakage: the distinctive marker must never appear in the ciphertext,
# exceptions, or repr
# --------------------------------------------------------------------- #


def test_marker_never_appears_in_ciphertext_bytes(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state(_MARKER))
    raw = (tmp_path / f"{OUJDA}.bin").read_bytes()
    assert _MARKER.encode("utf-8") not in raw


def test_marker_never_appears_in_exception_text_on_failure(tmp_path):
    store = WorkstationSessionStore(tmp_path, InMemoryCryptoBackend())
    store.save(OUJDA, _storage_state(_MARKER))
    huge_with_marker = {
        "cookies": [{"name": "x", "value": _MARKER + "y" * MAX_STORAGE_STATE_BYTES}], "origins": [],
    }
    try:
        store.save(OUJDA, huge_with_marker)
    except InvalidStorageState as exc:
        assert _MARKER not in str(exc)
        assert _MARKER not in repr(exc)
    else:
        pytest.fail("expected InvalidStorageState")
