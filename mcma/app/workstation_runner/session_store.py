"""mcma.app.workstation_runner.session_store -- DPAPI CURRENT_USER-protected
storage for the two workstation MCMA Playwright sessions (Phase 1B-B).

Deliberately separate from three other things it must never be confused
with:
  * mcma.app.workstation_runner.identity -- the RUNNER PAIRING credential
    (one file, one Windows account, one server). This module is about the
    two PORTAL accounts an authorized human logs into from that same
    Windows account -- a completely different secret, with its own file
    per account.
  * mcma.portal.vault -- the SERVER's four-notification-account session
    vault (DPAPI LOCAL_MACHINE + an NTFS-ACL hard precondition, SQLite
    rows). This module never touches sqlite3 (mcma.app may not import it
    anyway) and never uses LOCAL_MACHINE scope: a workstation session is
    the property of the one interactive Windows user who is physically
    sitting at that machine, so CURRENT_USER (only that account can ever
    decrypt it) is the correct, narrower scope -- exactly identity.py's
    reasoning, reapplied here.
  * a Windows Edge/Chrome profile -- there is no such thing referenced
    anywhere below. Only a Playwright storage_state dict is ever stored.

Same fail-closed shape as identity.py: corruption, a wrong Windows user,
an account mismatch, an unsupported envelope version, or an oversized
file all make load() return None -- there is no partially-trusted result.
Never falls back to plaintext.
"""

from __future__ import annotations

import json
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Protocol

from mcma.app.workstation_runner.protocol import RUNNER_ACCOUNT_IDS
from mcma.core.dpapi import DpapiScope, DpapiUnavailable, protect, unprotect

SESSION_FORMAT_VERSION = 1

# Generous but bounded: a real Playwright storage_state for one portal
# account is a handful of cookies and, at most, a few origins' worth of
# localStorage -- comfortably under 200 KB in practice. 2 MB is far larger
# than any legitimate session yet small enough that a corrupted/hostile
# blob can never turn this into an unbounded-memory or unbounded-disk
# problem. This bound is checked on storage_state ALONE (validate_storage_state);
# the envelope/ciphertext bounds below add explicit margin on top of it so a
# legitimate save can never be rejected by disk-side bounds that forgot the
# envelope's own JSON scaffolding.
MAX_STORAGE_STATE_BYTES = 2_000_000

# The on-disk envelope wraps storage_state in {"format_version": int,
# "account_id": str, "storage_state": ...}. That scaffolding is small and
# fixed-shape, but load() must bound the DECRYPTED plaintext before ever
# handing it to json.loads -- checking MAX_STORAGE_STATE_BYTES alone (which
# is validated only on the inner "storage_state" value, after decoding)
# would mean decoding an arbitrarily large JSON document first.
_ENVELOPE_OVERHEAD_BYTES = 4_096
MAX_ENVELOPE_PLAINTEXT_BYTES = MAX_STORAGE_STATE_BYTES + _ENVELOPE_OVERHEAD_BYTES

# DPAPI's CryptProtectData adds a small, fixed amount of framing on top of
# the plaintext it protects -- far less than this margin. Checking the
# CIPHERTEXT file's size on disk (via stat(), before it is even read) lets
# load() refuse an absurdly oversized or hostile file without ever calling
# read_bytes(), DPAPI, or json.loads on it.
_CIPHERTEXT_OVERHEAD_BYTES = 65_536
MAX_CIPHERTEXT_BYTES = MAX_ENVELOPE_PLAINTEXT_BYTES + _CIPHERTEXT_OVERHEAD_BYTES

_ALLOWED_TOP_LEVEL_KEYS = {"cookies", "origins"}

# Playwright's own BrowserContext.storage_state() cookie shape. All four
# required keys are always present in real output; the rest are optional
# there too, but when present are always exactly these types -- accepting
# them (and only them) keeps this compatible with genuine Playwright output
# while refusing arbitrary nested objects.
_COOKIE_REQUIRED_KEYS = {"name", "value", "domain", "path"}
_COOKIE_OPTIONAL_KEYS = {"expires", "httpOnly", "secure", "sameSite"}
_COOKIE_ALLOWED_KEYS = _COOKIE_REQUIRED_KEYS | _COOKIE_OPTIONAL_KEYS
_COOKIE_SAME_SITE_VALUES = {"Strict", "Lax", "None"}

_ORIGIN_ALLOWED_KEYS = {"origin", "localStorage"}


class SessionStoreError(Exception):
    """Base for every error this module raises. Never carries a secret,
    a cookie value, a token, or any storage_state content -- only account
    ids and fixed, safe messages."""


class UnknownWorkstationAccount(SessionStoreError):
    """Raised for any account_id outside the fixed two-account allowlist.
    Fixed message only, and the rejected value is never retained on the
    exception: the offending object could be an arbitrary/hostile value
    from a caller bug, not merely a mistyped id, so it must not survive in
    a traceback, a log, or repr()."""

    def __init__(self) -> None:
        super().__init__("account_id is not one of the allowed workstation MCMA accounts")


class InvalidStorageState(SessionStoreError):
    """The storage_state failed shape or size validation, either before
    encryption (save) or after decryption (load/verify). Carries only a
    fixed reason, never the offending value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CryptoBackend(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class DpapiCurrentUserBackend:
    """The only production CryptoBackend. Same CURRENT_USER scope and
    reasoning as identity.DpapiCurrentUserBackend -- a different secret (a
    portal session, not the runner's pairing credential) but the same
    "only this interactive Windows account may ever decrypt it" answer.
    No LOCAL_MACHINE option is exposed here."""

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


def default_sessions_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set; cannot locate the session store")
    return Path(local_app_data) / "MCMA Runner" / "sessions"


def _require_known_account(account_id: object) -> str:
    if not isinstance(account_id, str) or account_id not in RUNNER_ACCOUNT_IDS:
        raise UnknownWorkstationAccount()
    return account_id


def _valid_cookie(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    keys = set(item)
    if not _COOKIE_REQUIRED_KEYS.issubset(keys) or not keys.issubset(_COOKIE_ALLOWED_KEYS):
        return False
    if not all(isinstance(item[key], str) for key in _COOKIE_REQUIRED_KEYS):
        return False
    if "expires" in item:
        expires = item["expires"]
        if isinstance(expires, bool) or not isinstance(expires, (int, float)):
            return False
        if not math.isfinite(expires):  # reject NaN, +inf, -inf
            return False
    for flag_key in ("httpOnly", "secure"):
        if flag_key in item and not isinstance(item[flag_key], bool):
            return False
    if "sameSite" in item and item["sameSite"] not in _COOKIE_SAME_SITE_VALUES:
        return False
    return True


def _valid_local_storage_item(item: object) -> bool:
    return (
        isinstance(item, dict)
        and set(item) == {"name", "value"}
        and isinstance(item["name"], str)
        and isinstance(item["value"], str)
    )


def _valid_origin(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    keys = set(item)
    if "origin" not in keys or not keys.issubset(_ORIGIN_ALLOWED_KEYS):
        return False
    if not isinstance(item["origin"], str):
        return False
    local_storage = item.get("localStorage", [])
    if not isinstance(local_storage, list):
        return False
    return all(_valid_local_storage_item(entry) for entry in local_storage)


def validate_storage_state(storage_state: object) -> dict:
    """Strict shape + bounded-size validation, applied identically before
    encryption (save) and after decryption (load) -- SEC requirement: a
    saved session that later fails to decode as a well-formed
    storage_state must never be handed back as if it were usable.

    Deliberately narrow but now also strict about NESTING: only the two
    top-level keys Playwright's own storage_state() ever produces are
    accepted, and every cookie/origin/localStorage entry is checked
    against Playwright's own shape for that entry -- a top-level key being
    correct is not enough to let arbitrary nested objects through. This is
    still not a full schema validator for cookie/origin semantics
    (Playwright owns that), it is a bound against a corrupted or hostile
    blob pretending to be one, plus the fixed byte bound below."""
    if not isinstance(storage_state, dict):
        raise InvalidStorageState("storage_state must be a JSON object")
    if set(storage_state) != _ALLOWED_TOP_LEVEL_KEYS:
        raise InvalidStorageState("storage_state must contain exactly the cookies and origins keys")
    cookies = storage_state["cookies"]
    origins = storage_state["origins"]
    if not isinstance(cookies, list) or not isinstance(origins, list):
        raise InvalidStorageState("storage_state cookies/origins must be lists")
    if not all(_valid_cookie(cookie) for cookie in cookies):
        raise InvalidStorageState("storage_state contains a malformed cookie entry")
    if not all(_valid_origin(origin) for origin in origins):
        raise InvalidStorageState("storage_state contains a malformed origin entry")
    try:
        encoded = json.dumps(storage_state).encode("utf-8")
    except (TypeError, ValueError):
        raise InvalidStorageState("storage_state is not JSON-serializable") from None
    if len(encoded) > MAX_STORAGE_STATE_BYTES:
        raise InvalidStorageState("storage_state exceeds the maximum allowed size")
    return storage_state


def _parse_envelope(raw: bytes, *, expected_account_id: str) -> dict | None:
    if len(raw) > MAX_ENVELOPE_PLAINTEXT_BYTES:
        return None  # fail closed: never JSON-decode an oversized decrypted blob
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("format_version") != SESSION_FORMAT_VERSION:
        return None
    if obj.get("account_id") != expected_account_id:
        return None
    try:
        return validate_storage_state(obj.get("storage_state"))
    except InvalidStorageState:
        return None


class WorkstationSessionStore:
    """One encrypted file per account under `sessions_dir`. Every public
    method takes/returns plain dicts (never a Playwright object) and never
    raises with a storage_state value inside the exception."""

    def __init__(self, sessions_dir: Path, backend: CryptoBackend) -> None:
        self._dir = Path(sessions_dir)
        self._backend = backend

    def _path_for(self, account_id: str) -> Path:
        account_id = _require_known_account(account_id)
        return self._dir / f"{account_id}.bin"

    def load(self, account_id: str) -> dict | None:
        path = self._path_for(account_id)
        try:
            file_size = path.stat().st_size
        except OSError:
            return None  # missing/unreadable is as good as missing -- fail closed
        if file_size > MAX_CIPHERTEXT_BYTES:
            return None  # refuse to even attempt reading an oversized/hostile file
        try:
            ciphertext = path.read_bytes()
        except OSError:
            return None  # unreadable is as good as missing -- fail closed
        if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            # stat()/read() race: the file could have grown between the size
            # check above and this read. Re-check the ACTUAL bytes read
            # before ever handing them to DPAPI.
            return None
        try:
            plaintext = self._backend.unprotect(ciphertext)
        except (DpapiUnavailable, ValueError, TypeError, OSError):
            return None  # corrupt, wrong-user, or backend-refused -- fail closed
        return _parse_envelope(plaintext, expected_account_id=account_id)

    def has_saved_session(self, account_id: str) -> bool:
        return self._path_for(account_id).is_file()

    def save(self, account_id: str, storage_state: dict) -> None:
        account_id = _require_known_account(account_id)
        validated = validate_storage_state(storage_state)
        path = self._dir / f"{account_id}.bin"
        payload = json.dumps({
            "format_version": SESSION_FORMAT_VERSION,
            "account_id": account_id,
            "storage_state": validated,
        }).encode("utf-8")
        ciphertext = self._backend.protect(payload)
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._dir / f".{uuid.uuid4().hex}.{account_id}.session.tmp"
        try:
            with tmp_path.open("wb") as handle:
                handle.write(ciphertext)
                handle.flush()
                os.fsync(handle.fileno())  # durably complete before the replace below
            os.replace(tmp_path, path)  # atomic, same directory as identity.py's pattern
        except OSError:
            tmp_path.unlink(missing_ok=True)  # never leave a stray encrypted temp file behind
            raise

    def clear(self, account_id: str) -> None:
        self._path_for(account_id).unlink(missing_ok=True)

    def clear_all(self) -> None:
        for account_id in RUNNER_ACCOUNT_IDS:
            self.clear(account_id)
