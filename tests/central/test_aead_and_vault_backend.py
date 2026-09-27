"""Linux-compatible authenticated encryption: envelope, key file, session
vault backend and job-input encryptor."""

import os
import stat
import sys

import pytest

from mcma.core import aead
from mcma.core.aead import (
    AeadDecryptionError,
    AeadEnvelope,
    KeyFileError,
    MalformedEnvelope,
    UnsupportedEnvelopeVersion,
    key_file_permission_problem,
    load_key_file,
)
from mcma.execution.inputs import AesGcmInputEncryptor, TestOnlyPlaintextEncryptor, get_input_encryptor
from mcma.persistence.db import open_database
from mcma.portal.vault import (
    AesGcmSessionVaultBackend,
    ProductionCryptoBackendUnavailable,
    SessionDecryptionFailed,
    TestOnlyAclVerifier,
    get_crypto_backend,
    load_and_verify_session,
    store_session,
)

KEY = bytes(range(32))
OTHER_KEY = bytes(range(1, 33))
SECRET = b'{"cookies": [{"name": "SESSION", "value": "s3cr3t-cookie"}]}'


def _envelope(key=KEY, purpose="portal-session-vault"):
    return AeadEnvelope(key, purpose=purpose)


# ------------------------------- envelope ------------------------------- #


def test_round_trip_and_ciphertext_hides_plaintext():
    sealed = _envelope().seal(SECRET, context="acct-1")
    assert b"s3cr3t-cookie" not in sealed
    assert _envelope().open(sealed, context="acct-1") == SECRET


def test_fresh_nonce_gives_different_ciphertext_for_same_plaintext():
    first = _envelope().seal(SECRET, context="acct-1")
    second = _envelope().seal(SECRET, context="acct-1")
    assert first != second
    assert first[5:17] != second[5:17]  # the nonce bytes differ
    assert first.startswith(aead.MAGIC + bytes([aead.FORMAT_VERSION]))


def test_wrong_key_is_rejected():
    sealed = _envelope().seal(SECRET, context="a")
    with pytest.raises(AeadDecryptionError):
        _envelope(OTHER_KEY).open(sealed, context="a")


@pytest.mark.parametrize("offset", [5, 20, -1])  # nonce, ciphertext body, tag
def test_tampering_is_detected(offset):
    sealed = bytearray(_envelope().seal(SECRET, context="a"))
    sealed[offset] ^= 0x01
    with pytest.raises(AeadDecryptionError):
        _envelope().open(bytes(sealed), context="a")


def test_a_blob_moved_to_another_account_fails():
    sealed = _envelope().seal(SECRET, context="MCMA-OUJDA")
    with pytest.raises(AeadDecryptionError):
        _envelope().open(sealed, context="MCMA-NADOR")


def test_a_blob_cannot_cross_purposes():
    sealed = _envelope(purpose="portal-session-vault").seal(SECRET)
    with pytest.raises(AeadDecryptionError):
        _envelope(purpose="job-input").open(sealed)


def test_unsupported_version_is_reported_as_such():
    sealed = bytearray(_envelope().seal(SECRET))
    sealed[4] = 99
    with pytest.raises(UnsupportedEnvelopeVersion):
        _envelope().open(bytes(sealed))


@pytest.mark.parametrize("blob", [b"", b"MC", b"XXXX\x01" + b"\x00" * 40, aead.MAGIC + b"\x01" + b"\x00" * 10])
def test_malformed_or_truncated_envelopes_are_rejected(blob):
    with pytest.raises((MalformedEnvelope, AeadDecryptionError)):
        _envelope().open(blob)


def test_truncated_real_envelope_is_rejected():
    sealed = _envelope().seal(SECRET)
    for cut in (len(sealed) - 1, aead.MIN_ENVELOPE_LENGTH, 10):
        with pytest.raises((MalformedEnvelope, AeadDecryptionError)):
            _envelope().open(sealed[:cut])


def test_plaintext_is_never_accepted_as_an_envelope():
    with pytest.raises(MalformedEnvelope):
        _envelope().open(SECRET)


@pytest.mark.parametrize("length", [0, 16, 31, 33, 64])
def test_key_must_be_exactly_32_bytes(length):
    with pytest.raises(KeyFileError):
        AeadEnvelope(b"k" * length, purpose="x")


def test_errors_never_contain_secret_material():
    sealed = _envelope().seal(SECRET, context="a")
    with pytest.raises(AeadDecryptionError) as info:
        _envelope(OTHER_KEY).open(sealed, context="a")
    text = str(info.value)
    assert "s3cr3t" not in text and repr(KEY) not in text


# ------------------------------- key file ------------------------------- #


def _write_key(path, data=KEY, mode=0o600):
    path.write_bytes(data)
    if os.name == "posix":
        os.chmod(path, mode)
    return path


def test_key_file_loads(tmp_path):
    assert load_key_file(_write_key(tmp_path / "k")) == KEY


def test_missing_key_file_is_refused(tmp_path):
    with pytest.raises(KeyFileError):
        load_key_file(tmp_path / "absent")


@pytest.mark.parametrize("data", [b"", KEY[:-1], KEY + b"\n", KEY + KEY])
def test_key_file_with_wrong_length_is_refused(tmp_path, data):
    with pytest.raises(KeyFileError):
        load_key_file(_write_key(tmp_path / "k", data))


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666, 0o610])
def test_insecure_permission_bits_are_reported(mode):
    assert key_file_permission_problem(stat.S_IFREG | mode, 1000, 1000) is not None


def test_secure_permissions_and_ownership_rules():
    assert key_file_permission_problem(stat.S_IFREG | 0o600, 1000, 1000) is None
    assert key_file_permission_problem(stat.S_IFREG | 0o400, 1000, 1000) is None
    assert key_file_permission_problem(stat.S_IFREG | 0o600, 0, 1000) is not None  # wrong owner
    assert key_file_permission_problem(stat.S_IFDIR | 0o700, 1000, 1000) is not None  # not a file


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_real_group_readable_key_file_is_refused(tmp_path):
    path = _write_key(tmp_path / "k", mode=0o640)
    with pytest.raises(KeyFileError, match="group or others"):
        load_key_file(path)


# ------------------------- session vault backend ------------------------ #


def test_session_backend_refuses_unbound_use():
    backend = AesGcmSessionVaultBackend(KEY)
    with pytest.raises(ProductionCryptoBackendUnavailable):
        backend.encrypt(SECRET)
    with pytest.raises(ProductionCryptoBackendUnavailable):
        backend.decrypt(b"x")


def test_factory_selects_aes_gcm_only_from_an_explicit_key_file(tmp_path):
    backend = get_crypto_backend(key_path=_write_key(tmp_path / "k"))
    assert isinstance(backend, AesGcmSessionVaultBackend)


@pytest.mark.skipif(sys.platform == "win32", reason="DPAPI is the Windows production backend")
def test_no_key_and_no_dpapi_means_refusal_not_plaintext():
    with pytest.raises(ProductionCryptoBackendUnavailable):
        get_crypto_backend()


def test_a_missing_key_never_creates_one(tmp_path):
    missing = tmp_path / "vault.key"
    with pytest.raises(KeyFileError):
        get_crypto_backend(key_path=missing)
    assert not missing.exists()


class _Lease:
    def __init__(self, account_id):
        self.account_id = account_id


def test_stored_session_round_trips_and_is_bound_to_its_account(tmp_path):
    conn = open_database(tmp_path / "db.sqlite3")
    for account_id in ("acct-a", "acct-b"):
        conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, 'MCMA', ?, 1, 'now')", (account_id, account_id, account_id),
        )
    backend = AesGcmSessionVaultBackend(KEY)
    vault = tmp_path / "vault"
    store_session(
        conn, _Lease("acct-a"), "acct-a", SECRET,
        vault_dir=vault, backend=backend, acl_verifier=TestOnlyAclVerifier(True),
    )
    assert load_and_verify_session(conn, "acct-a", vault_dir=vault, backend=backend) == SECRET
    on_disk = next(vault.glob("*.session")).read_bytes()
    assert b"s3cr3t-cookie" not in on_disk

    # Move acct-a's ciphertext under acct-b's row: must not decrypt.
    store_session(
        conn, _Lease("acct-b"), "acct-b", b"placeholder",
        vault_dir=vault, backend=backend, acl_verifier=TestOnlyAclVerifier(True),
    )
    row = conn.execute(
        "SELECT storage_ref FROM portal_sessions WHERE account_id='acct-b' AND status='ACTIVE'"
    ).fetchone()
    (vault / f"{row['storage_ref']}.session").write_bytes(on_disk)
    with pytest.raises(SessionDecryptionFailed):
        load_and_verify_session(conn, "acct-b", vault_dir=vault, backend=backend)


# ---------------------------- job-input encryptor ----------------------- #


def test_input_encryptor_round_trip_and_key_file_selection(tmp_path):
    encryptor = get_input_encryptor(key_path=_write_key(tmp_path / "in.key"))
    assert isinstance(encryptor, AesGcmInputEncryptor)
    sealed = encryptor.encrypt(SECRET)
    assert SECRET not in sealed
    assert encryptor.decrypt(sealed) == SECRET
    with pytest.raises(AeadDecryptionError):
        AesGcmInputEncryptor(OTHER_KEY).decrypt(sealed)


def test_input_key_cannot_open_a_session_blob():
    sealed = AesGcmSessionVaultBackend(KEY).for_account("a").encrypt(SECRET)
    with pytest.raises(AeadDecryptionError):
        AesGcmInputEncryptor(KEY).decrypt(sealed)


def test_test_only_backend_stays_explicit():
    assert isinstance(get_input_encryptor(_test_only_plaintext_backend=True), TestOnlyPlaintextEncryptor)
