"""Real Windows DPAPI CURRENT_USER round trip -- no fake backend. Mirrors
the skip idiom in tests/execution/jobs/test_inputs_dpapi_windows.py:14-21."""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="REAL_DPAPI_WINDOWS_ROUNDTRIP_PENDING_LOCAL_TEST: Windows DPAPI only",
)

from mcma.app.workstation_runner.identity import (
    IDENTITY_FORMAT_VERSION, DpapiCurrentUserBackend, IdentityStore, RunnerIdentity,
    select_production_crypto_backend,
)

ORIGIN = "https://central.example.local"


def _identity() -> RunnerIdentity:
    return RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN,
        runner_id="f" * 32, runner_secret="mcma_rs_" + "r" * 40,
        allowed_account_ids=("acct-mcma-oujda", "acct-mcma-nador"),
    )


def test_real_dpapi_round_trip(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", DpapiCurrentUserBackend())
    identity = _identity()
    store.save(identity)
    assert store.load(expected_server_origin=ORIGIN) == identity


def test_real_dpapi_ciphertext_is_not_plaintext_json(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", DpapiCurrentUserBackend())
    store.save(_identity())
    raw = (tmp_path / "identity.bin").read_bytes()
    assert b"mcma_rs_" not in raw
    assert b"runner_secret" not in raw


def test_restart_recovery_reopens_a_fresh_store_instance(tmp_path):
    path = tmp_path / "identity.bin"
    IdentityStore(path, DpapiCurrentUserBackend()).save(_identity())
    # simulate process restart: a brand-new IdentityStore object, same file
    reopened = IdentityStore(path, DpapiCurrentUserBackend())
    assert reopened.load(expected_server_origin=ORIGIN) == _identity()


def test_select_production_crypto_backend_returns_real_dpapi_on_windows():
    backend = select_production_crypto_backend()
    assert isinstance(backend, DpapiCurrentUserBackend)


@pytest.mark.parametrize("corrupt", [
    lambda b: b[:-5],                        # truncated
    lambda b: b[:20] + b"\xff" * 10 + b[30:],  # bit-flipped middle
    lambda b: b"not even DPAPI" + b,          # prefixed garbage
    lambda b: b"",                             # empty
])
def test_real_dpapi_load_fails_closed_on_corrupt_ciphertext(tmp_path, corrupt):
    """The fake-crypto version of this is in test_identity.py; this is the
    same guarantee against a REAL DPAPI-encrypted blob, not a stand-in."""
    path = tmp_path / "identity.bin"
    store = IdentityStore(path, DpapiCurrentUserBackend())
    store.save(_identity())
    path.write_bytes(corrupt(path.read_bytes()))
    assert store.load(expected_server_origin=ORIGIN) is None
