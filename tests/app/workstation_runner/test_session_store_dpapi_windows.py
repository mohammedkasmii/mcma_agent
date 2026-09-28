"""Real Windows DPAPI CURRENT_USER round trip for the workstation portal
session store -- no fake backend. Mirrors the skip idiom and coverage shape
in test_identity_dpapi_windows.py:8-11."""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="REAL_DPAPI_WINDOWS_ROUNDTRIP_PENDING_LOCAL_TEST: Windows DPAPI only",
)

from mcma.app.workstation_runner.session_store import (
    DpapiCurrentUserBackend, WorkstationSessionStore, select_production_crypto_backend,
)

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"
_MARKER = "REAL-DPAPI-SECRET-COOKIE-MARKER-zzz"


def _storage_state(marker: str = _MARKER) -> dict:
    return {
        "cookies": [{"name": "session", "value": marker, "domain": "sinauto.mamda-mcma.ma", "path": "/"}],
        "origins": [],
    }


def test_real_dpapi_round_trip(tmp_path):
    store = WorkstationSessionStore(tmp_path, DpapiCurrentUserBackend())
    state = _storage_state()
    store.save(OUJDA, state)
    assert store.load(OUJDA) == state


def test_real_dpapi_ciphertext_is_not_plaintext_json(tmp_path):
    store = WorkstationSessionStore(tmp_path, DpapiCurrentUserBackend())
    store.save(OUJDA, _storage_state())
    raw = (tmp_path / f"{OUJDA}.bin").read_bytes()
    assert _MARKER.encode("utf-8") not in raw
    assert b"storage_state" not in raw
    assert b"cookies" not in raw


def test_real_dpapi_account_binding_rejects_copied_ciphertext(tmp_path):
    """Copying Oujda's real-DPAPI-encrypted file onto Nador's path must not
    let it be read back as Nador's session -- the account id is bound
    INSIDE the encrypted envelope, not just implied by the filename."""
    store = WorkstationSessionStore(tmp_path, DpapiCurrentUserBackend())
    store.save(OUJDA, _storage_state("oujda-marker"))
    oujda_bytes = (tmp_path / f"{OUJDA}.bin").read_bytes()
    (tmp_path / f"{NADOR}.bin").write_bytes(oujda_bytes)
    assert store.load(NADOR) is None


@pytest.mark.parametrize("corrupt", [
    lambda b: b[:-5],                          # truncated
    lambda b: b[:20] + b"\xff" * 10 + b[30:],  # bit-flipped middle
    lambda b: b"not even DPAPI" + b,           # prefixed garbage
    lambda b: b"",                              # empty
])
def test_real_dpapi_load_fails_closed_on_corrupt_ciphertext(tmp_path, corrupt):
    """The fake-crypto version of this is in test_session_store.py; this is
    the same guarantee against a REAL DPAPI-encrypted blob, not a stand-in."""
    store = WorkstationSessionStore(tmp_path, DpapiCurrentUserBackend())
    store.save(OUJDA, _storage_state())
    path = tmp_path / f"{OUJDA}.bin"
    path.write_bytes(corrupt(path.read_bytes()))
    assert store.load(OUJDA) is None


def test_select_production_crypto_backend_returns_real_dpapi_on_windows():
    backend = select_production_crypto_backend()
    assert isinstance(backend, DpapiCurrentUserBackend)
