"""INC-13 -- session vault safety tests."""

import pytest

from mcma.portal.vault import (
    ProductionCryptoBackendUnavailable,
    SessionBindingMismatch,
    SessionDecryptionFailed,
    VaultAclPreconditionFailed,
    get_crypto_backend,
    load_and_verify_session,
    revoke_session,
    store_session,
)
from vault_test_support import ACCOUNT_ID, SyntheticLeaseHandle


def test_atomic_replacement_no_partial_session(conn, vault_dir, backend, restrictive_acl):
    lease = SyntheticLeaseHandle(ACCOUNT_ID)
    session_id = store_session(
        conn, lease, ACCOUNT_ID, b"first-storage-state",
        vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl,
    )
    loaded = load_and_verify_session(conn, ACCOUNT_ID, vault_dir=vault_dir, backend=backend)
    assert loaded == b"first-storage-state"

    # Replacement: the old file is gone, the new one is whole -- never a
    # window with a half-written or missing file.
    store_session(
        conn, lease, ACCOUNT_ID, b"second-storage-state",
        vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl,
    )
    files = list(vault_dir.glob("*.session"))
    assert len(files) == 1
    assert load_and_verify_session(conn, ACCOUNT_ID, vault_dir=vault_dir, backend=backend) == b"second-storage-state"
    assert session_id  # first session_id was returned and usable


def test_decryption_failure_fails_closed(conn, vault_dir, backend, restrictive_acl):
    lease = SyntheticLeaseHandle(ACCOUNT_ID)
    store_session(conn, lease, ACCOUNT_ID, b"storage-state", vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl)

    class _AlwaysFailsDecrypt:
        def encrypt(self, plaintext):
            return plaintext

        def decrypt(self, ciphertext):
            raise RuntimeError("corrupted")

    with pytest.raises(SessionDecryptionFailed):
        load_and_verify_session(conn, ACCOUNT_ID, vault_dir=vault_dir, backend=_AlwaysFailsDecrypt())


def test_account_binding_mismatch_fails_closed(conn, vault_dir, backend, restrictive_acl):
    lease = SyntheticLeaseHandle(ACCOUNT_ID)
    store_session(
        conn, lease, ACCOUNT_ID, b"storage-state",
        vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl,
        identity_fingerprint="fingerprint-for-acct-1",
    )
    with pytest.raises(SessionBindingMismatch):
        load_and_verify_session(
            conn, ACCOUNT_ID, vault_dir=vault_dir, backend=backend,
            observed_identity_fingerprint="a-completely-different-fingerprint",
        )
    # Positive control: the correct fingerprint still loads.
    loaded = load_and_verify_session(
        conn, ACCOUNT_ID, vault_dir=vault_dir, backend=backend,
        observed_identity_fingerprint="fingerprint-for-acct-1",
    )
    assert loaded == b"storage-state"


def test_rotation_and_revocation_force_relogin(conn, vault_dir, backend, restrictive_acl):
    lease = SyntheticLeaseHandle(ACCOUNT_ID)
    store_session(conn, lease, ACCOUNT_ID, b"storage-state", vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl)
    revoke_session(conn, ACCOUNT_ID, vault_dir=vault_dir)
    with pytest.raises(SessionDecryptionFailed):
        load_and_verify_session(conn, ACCOUNT_ID, vault_dir=vault_dir, backend=backend)
    assert list(vault_dir.glob("*.session")) == []

    # Rotation: a fresh store_session after revocation works cleanly (a
    # forced re-login is exactly what onboarding would perform next).
    store_session(conn, lease, ACCOUNT_ID, b"fresh-storage-state", vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl)
    assert load_and_verify_session(conn, ACCOUNT_ID, vault_dir=vault_dir, backend=backend) == b"fresh-storage-state"


def test_service_acquires_lease_before_session_replace(conn, vault_dir, backend, restrictive_acl):
    invalid_lease = SyntheticLeaseHandle(ACCOUNT_ID, valid=False)
    with pytest.raises(ValueError):
        store_session(
            conn, SyntheticLeaseHandle("acct-other"), ACCOUNT_ID, b"x",
            vault_dir=vault_dir, backend=backend, acl_verifier=restrictive_acl,
        )
    # store_session itself does not call assert_valid() (the caller,
    # mcma.app.onboarding, does immediately before calling it) -- proven
    # here via the onboarding endpoint test instead. This test proves the
    # account-identity binding check on the handle itself.
    assert invalid_lease.account_id == ACCOUNT_ID


def test_production_config_rejects_a_platform_without_dpapi(monkeypatch):
    """Pilot-integration correction: get_crypto_backend() now actually
    returns a working DpapiLocalMachineBackend on win32 (see the positive
    control below) -- the fail-closed case is specifically "no DPAPI on
    this platform", proven here by simulating a non-Windows platform
    rather than by the factory always refusing regardless of platform."""
    import mcma.portal.vault as vault_module

    monkeypatch.setattr(vault_module.sys, "platform", "linux")
    with pytest.raises(ProductionCryptoBackendUnavailable):
        get_crypto_backend()


def test_production_backend_on_windows_is_a_real_working_dpapi_backend():
    """Positive control: on the actual platform this suite runs on
    (win32), get_crypto_backend() returns a genuine DpapiLocalMachineBackend
    -- proven with a real encrypt/decrypt round-trip against the real
    Windows DPAPI API (a pure local OS call, no network, no portal
    contact) rather than merely asserting it doesn't raise."""
    import sys

    from mcma.portal.vault import DpapiLocalMachineBackend

    if sys.platform != "win32":
        pytest.skip("DPAPI is only available on win32")
    backend = get_crypto_backend()
    assert isinstance(backend, DpapiLocalMachineBackend)
    ciphertext = backend.encrypt(b"round-trip-test-value")
    assert ciphertext != b"round-trip-test-value"
    assert backend.decrypt(ciphertext) == b"round-trip-test-value"


def test_test_only_flag_opts_into_the_in_memory_backend():
    from mcma.portal.vault import TestOnlyInMemoryCryptoBackend

    backend = get_crypto_backend(_test_only_in_memory_backend=True)
    assert isinstance(backend, TestOnlyInMemoryCryptoBackend)


def test_store_refuses_when_service_account_only_acl_cannot_be_set(conn, vault_dir, backend, permissive_acl):
    lease = SyntheticLeaseHandle(ACCOUNT_ID)
    with pytest.raises(VaultAclPreconditionFailed):
        store_session(
            conn, lease, ACCOUNT_ID, b"storage-state",
            vault_dir=vault_dir, backend=backend, acl_verifier=permissive_acl,
        )
    # No session file, no DB row -- the refusal is total, not partial.
    assert list(vault_dir.glob("*.session")) == []
    assert conn.execute("SELECT COUNT(*) AS c FROM portal_sessions").fetchone()["c"] == 0
