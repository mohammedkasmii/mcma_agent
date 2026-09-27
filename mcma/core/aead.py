"""
mcma.core.aead -- versioned AES-256-GCM envelope and key-file loading for
the Linux-compatible storage backends (central server, Phase 1).

The Windows installs protect data with DPAPI, which does not exist on
Ubuntu. This module is the portable replacement primitive: authenticated
encryption from the maintained `cryptography` package, never a hand-rolled
cipher.

Envelope (all values fixed-width, nothing is length-prefixed):

    MAGIC "MCMA" (4) | version (1) | nonce (12) | ciphertext || GCM tag (16)

  * A FRESH random 96-bit nonce is drawn for every encryption.
  * The additional authenticated data (AAD) is
        MAGIC | version | purpose | 0x00 | context
    so a blob cannot be replayed under another format version, another
    purpose (session vault vs job input) or another context (the portal
    account id) without failing authentication.
  * Wrong key, tampering, wrong AAD and truncation all surface as one
    AeadDecryptionError with a fixed message. The three are deliberately
    not distinguished: telling an attacker which one it was helps them,
    and the operator's remedy is the same. A bad or unknown VERSION is
    reported separately because that one is a deployment fact, not an
    attack signal.
  * There is no plaintext fallback anywhere: a blob that is not a valid
    envelope is refused, never passed through.

Key material is never logged, never placed in an exception message and
never generated here. A key is loaded from an explicit path or the caller
gets KeyFileError; creating one is an operator action (see
docs/architecture/CENTRAL_SERVER_DEPLOYMENT.md).
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"MCMA"
FORMAT_VERSION = 1
KEY_LENGTH = 32
NONCE_LENGTH = 12
TAG_LENGTH = 16
_HEADER_LENGTH = len(MAGIC) + 1
MIN_ENVELOPE_LENGTH = _HEADER_LENGTH + NONCE_LENGTH + TAG_LENGTH


class AeadError(Exception):
    """Base for every failure in this module. Messages are fixed strings:
    they never contain key bytes, plaintext or ciphertext."""


class AeadDecryptionError(AeadError):
    """Wrong key, tampered or truncated ciphertext, or wrong purpose/
    context. Deliberately one error -- see the module docstring."""


class UnsupportedEnvelopeVersion(AeadError):
    """A well-formed header naming a format version this build does not
    know. Refused rather than guessed at."""


class MalformedEnvelope(AeadError):
    """Too short to be an envelope, or missing the magic prefix."""


class KeyFileError(AeadError):
    """The key file is missing, unreadable, the wrong length or has
    insecure permissions. Never carries key bytes."""


def _associated_data(version: int, purpose: str, context: str) -> bytes:
    return MAGIC + bytes([version]) + purpose.encode("utf-8") + b"\x00" + context.encode("utf-8")


class AeadEnvelope:
    """One key, one purpose. `context` (e.g. the account id) is supplied
    per call and bound into the AAD."""

    def __init__(self, key: bytes, *, purpose: str) -> None:
        if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_LENGTH:
            raise KeyFileError(f"key must be exactly {KEY_LENGTH} bytes")
        if not purpose:
            raise ValueError("purpose must be a non-empty label")
        self._aesgcm = AESGCM(bytes(key))
        self._purpose = purpose

    def seal(self, plaintext: bytes, *, context: str = "") -> bytes:
        nonce = secrets.token_bytes(NONCE_LENGTH)
        aad = _associated_data(FORMAT_VERSION, self._purpose, context)
        return MAGIC + bytes([FORMAT_VERSION]) + nonce + self._aesgcm.encrypt(nonce, bytes(plaintext), aad)

    def open(self, envelope: bytes, *, context: str = "") -> bytes:
        envelope = bytes(envelope)
        if len(envelope) < _HEADER_LENGTH or envelope[: len(MAGIC)] != MAGIC:
            raise MalformedEnvelope("not an MCMA encrypted envelope")
        version = envelope[len(MAGIC)]
        if version != FORMAT_VERSION:
            raise UnsupportedEnvelopeVersion(f"unsupported envelope version {version}")
        if len(envelope) < MIN_ENVELOPE_LENGTH:
            raise AeadDecryptionError("encrypted data is truncated or was not produced with this key")
        nonce = envelope[_HEADER_LENGTH : _HEADER_LENGTH + NONCE_LENGTH]
        body = envelope[_HEADER_LENGTH + NONCE_LENGTH :]
        aad = _associated_data(version, self._purpose, context)
        try:
            return self._aesgcm.decrypt(nonce, body, aad)
        except InvalidTag:
            raise AeadDecryptionError(
                "encrypted data is truncated, was tampered with, or was not produced with this key/context"
            ) from None


# --------------------------------------------------------------------- #
# Key file
# --------------------------------------------------------------------- #


def key_file_permission_problem(mode: int, owner_uid: int, effective_uid: int) -> Optional[str]:
    """Pure check on stat results (unit-testable on any OS). Returns a
    fixed description of the problem, or None when the file is acceptable:
    a regular file, owned by the running user, with no group/other access."""
    if not stat.S_ISREG(mode):
        return "key path is not a regular file"
    if mode & 0o077:
        return "key file must not be accessible by group or others (require mode 0600 or stricter)"
    if owner_uid != effective_uid:
        return "key file must be owned by the user running the service"
    return None


def load_key_file(path: Path) -> bytes:
    """Reads exactly KEY_LENGTH raw bytes from `path`.

    Raw bytes, not text: no encoding or trailing-newline ambiguity about
    what the key is. Generate with `head -c 32 /dev/urandom > key`.
    On POSIX the file must be a regular file, owner-only (0600 or
    stricter) and owned by the running user; the check is made on the
    OPEN descriptor so it cannot be raced by swapping the path."""
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        raise KeyFileError(f"key file not found: {path}") from None
    except OSError:
        raise KeyFileError(f"key file could not be opened: {path}") from None
    try:
        info = os.fstat(fd)
        if os.name == "posix":
            problem = key_file_permission_problem(info.st_mode, info.st_uid, os.geteuid())
            if problem is not None:
                raise KeyFileError(f"{problem}: {path}")
        elif not stat.S_ISREG(info.st_mode):
            raise KeyFileError(f"key path is not a regular file: {path}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            key = handle.read(KEY_LENGTH + 1)
    finally:
        os.close(fd)
    if len(key) != KEY_LENGTH:
        raise KeyFileError(f"key file must contain exactly {KEY_LENGTH} raw bytes: {path}")
    return key
