"""mcma.app.workstation_runner.identity -- DPAPI CURRENT_USER-protected
runner identity persistence.

Fail-closed by construction: IdentityStore.load() returns None for a
missing file, a corrupt/truncated/altered ciphertext, a ciphertext DPAPI
cannot decrypt for this Windows account, a wrong format version, a
server-origin mismatch, or any structurally invalid field -- there is no
code path that returns a partially-trusted identity. Never falls back to
plaintext, base64, or LOCAL_MACHINE scope: mcma.core.dpapi.DpapiScope.CURRENT_USER
is the only production scope this module will ever select."""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mcma.app.workstation_runner.protocol import (
    MAX_RUNNER_SECRET_LENGTH, RUNNER_ACCOUNT_IDS, RUNNER_SECRET_PREFIX,
)
from mcma.core.dpapi import DpapiScope, DpapiUnavailable, protect, unprotect

IDENTITY_FORMAT_VERSION = 1

_RUNNER_ID_RE_LEN = 32  # uuid.uuid4().hex, matches mcma.app.runners.registry


@dataclass(frozen=True)
class RunnerIdentity:
    format_version: int
    server_origin: str
    runner_id: str
    runner_secret: str
    allowed_account_ids: tuple  # tuple[str, ...]


class CryptoBackend(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class DpapiCurrentUserBackend:
    """The only production CryptoBackend. No LOCAL_MACHINE option is
    exposed here -- runner identity is per-employee, per-account."""

    def protect(self, data: bytes) -> bytes:
        return protect(data, DpapiScope.CURRENT_USER)

    def unprotect(self, data: bytes) -> bytes:
        return unprotect(data, DpapiScope.CURRENT_USER)


def select_production_crypto_backend() -> CryptoBackend:
    if sys.platform != "win32":
        raise RuntimeError(
            "the workstation runner requires Windows DPAPI CURRENT_USER; "
            "no fallback backend exists in production"
        )
    return DpapiCurrentUserBackend()


def default_identity_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set; cannot locate the identity store")
    return Path(local_app_data) / "MCMA Runner" / "identity.bin"


def _valid_runner_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _RUNNER_ID_RE_LEN
        and all(c in "0123456789abcdef" for c in value)
    )


def _valid_runner_secret(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(RUNNER_SECRET_PREFIX)
        and len(RUNNER_SECRET_PREFIX) < len(value) <= MAX_RUNNER_SECRET_LENGTH
    )


def _valid_account_ids(value: object) -> bool:
    # Entry TYPES are checked before uniqueness: set(value) raises a raw
    # TypeError for an unhashable entry (a dict or a list, both valid JSON
    # values a corrupted/tampered envelope could contain), which used to
    # escape this function uncaught instead of failing closed.
    if not isinstance(value, list) or len(value) > len(RUNNER_ACCOUNT_IDS):
        return False
    if not all(isinstance(a, str) and a in RUNNER_ACCOUNT_IDS for a in value):
        return False
    return len(set(value)) == len(value)


def _parse_envelope(raw: bytes, *, expected_server_origin: str) -> RunnerIdentity | None:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("format_version") != IDENTITY_FORMAT_VERSION:
        return None
    if obj.get("server_origin") != expected_server_origin:
        return None
    if not _valid_runner_id(obj.get("runner_id")):
        return None
    if not _valid_runner_secret(obj.get("runner_secret")):
        return None
    if not _valid_account_ids(obj.get("allowed_account_ids")):
        return None
    return RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION,
        server_origin=expected_server_origin,
        runner_id=obj["runner_id"],
        runner_secret=obj["runner_secret"],
        allowed_account_ids=tuple(obj["allowed_account_ids"]),
    )


class IdentityStore:
    def __init__(self, path: Path, backend: CryptoBackend) -> None:
        self._path = Path(path)
        self._backend = backend

    def load(self, *, expected_server_origin: str) -> RunnerIdentity | None:
        try:
            ciphertext = self._path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return None  # unreadable is as good as missing -- fail closed
        try:
            plaintext = self._backend.unprotect(ciphertext)
        except (DpapiUnavailable, ValueError, TypeError, OSError):
            return None  # corrupt, wrong-user, or backend-refused -- fail closed
        return _parse_envelope(plaintext, expected_server_origin=expected_server_origin)

    def save(self, identity: RunnerIdentity) -> None:
        payload = json.dumps({
            "format_version": identity.format_version,
            "server_origin": identity.server_origin,
            "runner_id": identity.runner_id,
            "runner_secret": identity.runner_secret,
            "allowed_account_ids": list(identity.allowed_account_ids),
        }).encode("utf-8")
        ciphertext = self._backend.protect(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.parent / f".{uuid.uuid4().hex}.identity.tmp"
        try:
            tmp_path.write_bytes(ciphertext)
            os.replace(tmp_path, self._path)  # atomic on the same filesystem, same dir as vault.py's pattern
        except OSError:
            tmp_path.unlink(missing_ok=True)  # never leave a stray encrypted temp file behind
            raise

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
