"""Dossier JSON must not be readable in the database.

The property under test throughout is STORAGE, not that .encrypt() was
called: these read the actual job_inputs.ciphertext column and assert the
plaintext is not in it.

A recognisable marker is used so a leak is unmistakable in a failure
message -- if SUPER_SECRET_CLIENT_12345 ever appears where it should not,
the assertion says so plainly.
"""

import hashlib
import json
import sys

import pytest

from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, typed_input_bytes
from mcma.execution.inputs import (
    InputHashMismatch,
    InputUndecryptable,
    JobInputUnavailable,
    ProductionEncryptorUnavailable,
    TestOnlyPlaintextEncryptor,
    get_input_encryptor,
    retrieve_and_verify_job_input,
)
from mcma.execution.jobs import enqueue_dry_run

SECRET = "SUPER_SECRET_CLIENT_12345"
PAYLOAD = {"dossier": {"insured": SECRET, "matricule": "62259-A-50", "amount": "12345.67"}}


class _ReversibleFake:
    """Stands in for DPAPI on a non-Windows CI: a real transformation, so
    "the plaintext is not in the stored bytes" is a meaningful assertion
    rather than an artefact of a prefix. NOT encryption, and never
    reachable from production code -- only injected by these tests."""

    _KEY = 0x5A

    def encrypt(self, plaintext: bytes) -> bytes:
        return b"FAKE1" + bytes(b ^ self._KEY for b in plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"FAKE1"):
            raise ValueError("not produced by this encryptor")
        return bytes(b ^ self._KEY for b in ciphertext[5:])


def _enqueue(conn, encryptor, payload=PAYLOAD, key="secret-1"):
    return enqueue_dry_run(
        conn, account_id=ACCOUNT_ID, requested_by_user_id=USER_ID, workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload), typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=key, encryptor=encryptor,
    )


def _stored_ciphertext(conn, job_id):
    return conn.execute(
        "SELECT ciphertext FROM job_inputs WHERE job_id = ?", (job_id,)
    ).fetchone()["ciphertext"]


# --------------------------------------------------------------------- #
# At rest
# --------------------------------------------------------------------- #


def test_the_database_does_not_contain_the_dossier_in_the_clear(conn):
    job_id = _enqueue(conn, _ReversibleFake())
    stored = _stored_ciphertext(conn, job_id)
    plaintext = typed_input_bytes(PAYLOAD)

    assert stored != plaintext
    # The real assertion: the byte sequence is not sitting inside the
    # stored value anywhere.
    assert plaintext not in stored
    assert SECRET.encode() not in stored
    assert b"62259-A-50" not in stored


def test_the_plaintext_encryptor_shows_exactly_what_is_being_prevented(conn):
    """Negative control. With the test-only plaintext encryptor the
    dossier IS readable in the database -- which is what the normal local
    application did before this change."""
    job_id = _enqueue(conn, TestOnlyPlaintextEncryptor())
    assert SECRET.encode() in _stored_ciphertext(conn, job_id)


def test_the_stored_hash_is_of_the_plaintext_not_the_ciphertext(conn):
    job_id = _enqueue(conn, _ReversibleFake())
    row = conn.execute(
        "SELECT content_hash FROM job_inputs WHERE job_id = ?", (job_id,)
    ).fetchone()
    plaintext = typed_input_bytes(PAYLOAD)
    assert row["content_hash"] == hashlib.sha256(plaintext).hexdigest()


def test_retrieval_returns_the_exact_original_bytes(conn):
    job_id = _enqueue(conn, _ReversibleFake())
    retrieved = retrieve_and_verify_job_input(
        conn, job_id, input_hash_for(PAYLOAD), _ReversibleFake()
    )
    assert retrieved == typed_input_bytes(PAYLOAD)
    assert json.loads(retrieved)["dossier"]["insured"] == SECRET


# --------------------------------------------------------------------- #
# Restart
# --------------------------------------------------------------------- #


def test_a_fresh_encryptor_instance_can_decrypt_what_another_stored(conn):
    """Restart under the same Windows identity. Correctness must not
    depend on a key created in memory at startup."""
    job_id = _enqueue(conn, _ReversibleFake())          # instance A
    retrieved = retrieve_and_verify_job_input(
        conn, job_id, input_hash_for(PAYLOAD), _ReversibleFake()   # instance B
    )
    assert retrieved == typed_input_bytes(PAYLOAD)


# --------------------------------------------------------------------- #
# Tamper / fail closed
# --------------------------------------------------------------------- #


def test_mutated_ciphertext_is_undecryptable(conn):
    job_id = _enqueue(conn, _ReversibleFake())
    stored = bytearray(_stored_ciphertext(conn, job_id))
    stored[0] ^= 0xFF
    conn.execute("UPDATE job_inputs SET ciphertext = ? WHERE job_id = ?", (bytes(stored), job_id))

    with pytest.raises(InputUndecryptable):
        retrieve_and_verify_job_input(conn, job_id, input_hash_for(PAYLOAD), _ReversibleFake())


def test_valid_ciphertext_of_different_plaintext_is_a_hash_mismatch(conn):
    """Substituting a properly encrypted DIFFERENT dossier must not pass:
    the hash is what binds the stored bytes to the approved input."""
    job_id = _enqueue(conn, _ReversibleFake())
    other = _ReversibleFake().encrypt(typed_input_bytes({"dossier": {"insured": "SOMEONE_ELSE"}}))
    conn.execute("UPDATE job_inputs SET ciphertext = ? WHERE job_id = ?", (other, job_id))

    with pytest.raises(InputHashMismatch):
        retrieve_and_verify_job_input(conn, job_id, input_hash_for(PAYLOAD), _ReversibleFake())


def test_a_missing_row_is_reported_as_missing(conn):
    job_id = _enqueue(conn, _ReversibleFake())
    conn.execute("DELETE FROM job_inputs WHERE job_id = ?", (job_id,))
    with pytest.raises(JobInputUnavailable):
        retrieve_and_verify_job_input(conn, job_id, input_hash_for(PAYLOAD), _ReversibleFake())


def test_an_expired_row_is_refused(conn):
    job_id = _enqueue(conn, _ReversibleFake())
    conn.execute(
        "UPDATE job_inputs SET expires_at = '2000-01-01T00:00:00+00:00' WHERE job_id = ?",
        (job_id,),
    )
    with pytest.raises(JobInputUnavailable):
        retrieve_and_verify_job_input(conn, job_id, input_hash_for(PAYLOAD), _ReversibleFake())


# --------------------------------------------------------------------- #
# Enqueue is all-or-nothing
# --------------------------------------------------------------------- #


class _FailingEncryptor:
    def encrypt(self, plaintext: bytes) -> bytes:
        raise RuntimeError("DPAPI protect failed")

    def decrypt(self, ciphertext: bytes) -> bytes:  # pragma: no cover
        raise AssertionError("never reached")


def test_an_encryption_failure_leaves_no_job_and_no_partial_row(conn):
    """The job row, the input row, the outbox event and the audit record
    are one transaction. An encryption failure must roll all of it back --
    an orphan job pointing at no input, or a half-written PII row, would
    both be worse than the failure."""
    before_jobs = conn.execute("SELECT count(*) AS n FROM automation_jobs").fetchone()["n"]
    before_inputs = conn.execute("SELECT count(*) AS n FROM job_inputs").fetchone()["n"]

    with pytest.raises(Exception):
        _enqueue(conn, _FailingEncryptor(), key="rollback-1")

    assert conn.execute("SELECT count(*) AS n FROM automation_jobs").fetchone()["n"] == before_jobs
    assert conn.execute("SELECT count(*) AS n FROM job_inputs").fetchone()["n"] == before_inputs


# --------------------------------------------------------------------- #
# No PII escapes into other persisted artefacts
# --------------------------------------------------------------------- #


def test_the_dossier_is_not_copied_into_outbox_or_audit_rows(conn):
    """job_inputs.ciphertext must be the ONLY place this data lands."""
    _enqueue(conn, _ReversibleFake())
    for table, column in (("event_outbox", "payload_json"),):
        rows = conn.execute(f"SELECT {column} AS v FROM {table}").fetchall()
        for row in rows:
            assert SECRET not in str(row["v"])
            assert "62259-A-50" not in str(row["v"])
    audit = conn.execute("SELECT * FROM audit_events").fetchall()
    for row in audit:
        assert SECRET not in str(tuple(row))


# --------------------------------------------------------------------- #
# Platform selection
# --------------------------------------------------------------------- #


def test_production_selection_is_fail_closed_on_this_platform():
    if sys.platform == "win32":
        from mcma.execution.inputs import DpapiCurrentUserEncryptor

        assert isinstance(get_input_encryptor(), DpapiCurrentUserEncryptor)
    else:
        with pytest.raises(ProductionEncryptorUnavailable):
            get_input_encryptor()


def test_the_test_backend_needs_the_explicit_keyword():
    assert isinstance(
        get_input_encryptor(_test_only_plaintext_backend=True), TestOnlyPlaintextEncryptor
    )


def test_dpapi_refuses_rather_than_returning_data_off_windows():
    from mcma.core.dpapi import DpapiScope, DpapiUnavailable, is_available, protect

    if is_available():
        pytest.skip("this asserts the non-Windows refusal")
    with pytest.raises(DpapiUnavailable):
        protect(b"anything", DpapiScope.CURRENT_USER)


def test_a_dpapi_failure_message_never_carries_the_data():
    from mcma.core.dpapi import DpapiScope, DpapiUnavailable, protect

    try:
        protect(SECRET.encode(), DpapiScope.CURRENT_USER)
    except DpapiUnavailable as exc:
        assert SECRET not in str(exc)
    except Exception:  # pragma: no cover - Windows path
        pass


def test_the_session_vault_still_uses_local_machine_scope():
    """The two callers make different scope choices deliberately;
    extracting the shared primitive must not have silently aligned them."""
    import inspect

    from mcma.portal.vault import DpapiLocalMachineBackend

    source = inspect.getsource(DpapiLocalMachineBackend)
    assert "LOCAL_MACHINE" in source
    assert "CURRENT_USER" not in source
