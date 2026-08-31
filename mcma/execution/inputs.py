"""
mcma.execution.inputs -- job_inputs encrypt/store/verify (INC-12,
DATA_MODEL.md §4a).

The encryptor is INJECTED, never resolved by this module on its own
initiative in a way that could silently degrade: `get_input_encryptor()`
raises `ProductionEncryptorUnavailable` unless the caller explicitly
passes the underscore-prefixed test-only opt-in (mirrors
mcma.core.mutex's `_test_only_portable_backend` pattern) -- there is no
production code path that could reach the plaintext stub by omission.
Until INC-13 wires the real DPAPI-backed encryptor in, every PRODUCTION
attempt to store a job input fails closed rather than falling back to a
weak encryptor (review SE-1).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Protocol


class InputEncryptor(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class ProductionEncryptorUnavailable(Exception):
    """No production (DPAPI-backed, arrives in INC-13) encryptor is
    available. Storing a job input refuses rather than using a weak
    fallback."""


class TestOnlyPlaintextEncryptor:
    """TEST-ONLY. Never selectable in production -- see
    get_input_encryptor()."""

    def encrypt(self, plaintext: bytes) -> bytes:
        return plaintext

    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext


def get_input_encryptor(*, _test_only_plaintext_backend: bool = False) -> InputEncryptor:
    if _test_only_plaintext_backend:
        return TestOnlyPlaintextEncryptor()
    raise ProductionEncryptorUnavailable(
        "no production DPAPI-backed encryptor is available yet (arrives in INC-13); "
        "job input storage refuses rather than falling back to a weak encryptor"
    )


def compute_content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def default_expiry(created_at: datetime, ttl_days: int = 30) -> str:
    return _iso(created_at + timedelta(days=ttl_days))


# --------------------------------------------------------------------- #
# Restart / resume fail-closed reason codes (WORKFLOW_STATE_MODEL.md §7,
# DATA_MODEL.md §4a) -- one exception class per exact reason code.
# --------------------------------------------------------------------- #


class JobInputUnavailable(Exception):
    reason_code: str = "JOB_INPUT_UNAVAILABLE"

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job input unavailable for job {job_id!r}: {self.reason_code}")
        self.job_id = job_id


class MissingJobInput(JobInputUnavailable):
    reason_code = "MISSING_JOB_INPUT"


class InputExpired(JobInputUnavailable):
    reason_code = "INPUT_EXPIRED"


class InputUndecryptable(JobInputUnavailable):
    reason_code = "INPUT_UNDECRYPTABLE"


class InputHashMismatch(JobInputUnavailable):
    reason_code = "INPUT_HASH_MISMATCH"


def retrieve_and_verify_job_input(
    conn, job_id: str, expected_input_hash: str, encryptor: InputEncryptor
) -> bytes:
    """Re-reads job_inputs, decrypts, and asserts content_hash ==
    expected_input_hash before returning the plaintext -- a resumable job
    (restart, or a later verifying step) never executes on a guessed
    input. Missing/expired/undecryptable/hash-mismatched all fail closed
    with their own exact reason code (never generic)."""
    from mcma.persistence.repositories.jobs import JobInputsRepository

    row = JobInputsRepository(conn).get(job_id)
    if row is None or row["deleted_at"] is not None:
        raise MissingJobInput(job_id)
    if _parse(row["expires_at"]) < _utcnow():
        raise InputExpired(job_id)
    try:
        plaintext = encryptor.decrypt(bytes(row["ciphertext"]))
    except Exception as exc:
        raise InputUndecryptable(job_id) from exc
    if compute_content_hash(plaintext) != expected_input_hash:
        raise InputHashMismatch(job_id)
    return plaintext


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)
