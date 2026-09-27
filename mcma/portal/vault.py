"""
mcma.portal.vault -- the multi-account session vault (INC-13, ADR-0007,
SAFETY_MODEL.md §7, INV-10).

Production model: DPAPI LocalMachine encryption plus a service-account-
only NTFS ACL on the vault directory. LocalMachine-scoped DPAPI
ciphertext is decryptable by ANY local user on the machine -- the NTFS
ACL is therefore the SOLE confidentiality control, and this module
refuses to persist a session if that ACL cannot be set and verified
(review SEC-5, a HARD precondition, never "where feasible").

The crypto backend and the ACL verifier are both injected via the same
underscore-gated test-only opt-in pattern already established in
mcma.core.mutex/mcma.execution.inputs -- production call sites can never
reach the weaker backend by omission.

Decryption/binding failure always fails closed: no read or write
proceeds on ambiguous evidence. `storage_ref` (DATA_MODEL.md §2) is an
opaque token; the account's identity is `account_id`, never the file
path or the token itself.
"""

from __future__ import annotations

import os
import sys

from mcma.core import dpapi
from mcma.core.aead import AeadEnvelope, load_key_file
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol


class CryptoBackend(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class ProductionCryptoBackendUnavailable(Exception):
    """No production (DPAPI LocalMachine) backend is available. The vault
    refuses rather than falling back to a weaker backend."""


class DpapiLocalMachineBackend:
    """Production backend: Windows DPAPI, LOCAL_MACHINE scope.

    LOCAL_MACHINE is kept for the SESSION vault specifically. Any process
    on the machine can decrypt at this scope, so confidentiality here
    rests on the vault directory's NTFS ACL -- which is exactly the model
    G3 already specifies and WindowsAclVerifier already checks. Job inputs
    make the opposite choice; see mcma.execution.inputs.

    The ctypes call itself moved to mcma.core.dpapi so it is written once
    rather than twice; the scope and the threat model stay here, with the
    caller that owns them."""

    def encrypt(self, plaintext: bytes) -> bytes:
        return dpapi.protect(plaintext, dpapi.DpapiScope.LOCAL_MACHINE)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return dpapi.unprotect(ciphertext, dpapi.DpapiScope.LOCAL_MACHINE)


class AccountBoundCryptoBackend:
    """A session-vault backend bound to ONE account id by an AES-256-GCM
    envelope: the account id is authenticated additional data, so a blob
    copied to another account's row fails to decrypt instead of quietly
    becoming that account's session. Obtained only through
    AesGcmSessionVaultBackend.for_account()."""

    def __init__(self, envelope: AeadEnvelope, account_id: str) -> None:
        self._envelope = envelope
        self._account_id = account_id

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._envelope.seal(plaintext, context=self._account_id)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self._envelope.open(ciphertext, context=self._account_id)


class AesGcmSessionVaultBackend:
    """Linux-compatible production backend (central server): AES-256-GCM
    via mcma.core.aead with a versioned envelope, a fresh nonce per
    encryption and the account id bound as AAD.

    The key comes from an explicit key file (exactly 32 raw bytes, 0600 on
    POSIX); it is never generated here, so a missing key stops startup
    instead of silently minting one that cannot decrypt yesterday's
    sessions. There is no plaintext fallback, and encrypt()/decrypt()
    called without an account refuse: an unbound blob is exactly what the
    account binding exists to prevent. store_session/load_and_verify_session
    call for_account() themselves."""

    def __init__(self, key: bytes) -> None:
        self._envelope = AeadEnvelope(key, purpose="portal-session-vault")

    @classmethod
    def from_key_file(cls, key_path: Path) -> "AesGcmSessionVaultBackend":
        return cls(load_key_file(key_path))

    def for_account(self, account_id: str) -> CryptoBackend:
        if not account_id:
            raise ValueError("account_id is required to bind a session blob")
        return AccountBoundCryptoBackend(self._envelope, account_id)

    def encrypt(self, plaintext: bytes) -> bytes:
        raise ProductionCryptoBackendUnavailable(
            "the AES-GCM session backend requires an account binding; use for_account()"
        )

    def decrypt(self, ciphertext: bytes) -> bytes:
        raise ProductionCryptoBackendUnavailable(
            "the AES-GCM session backend requires an account binding; use for_account()"
        )


def _backend_for_account(backend: CryptoBackend, account_id: str) -> CryptoBackend:
    """Backends that bind an account (AES-GCM) hand back a bound view;
    DPAPI and the test-only backend have no per-account binding."""
    bind = getattr(backend, "for_account", None)
    return bind(account_id) if bind is not None else backend


class TestOnlyInMemoryCryptoBackend:
    """TEST-ONLY reversible transform (not real encryption). Never
    selectable in production -- see get_crypto_backend()."""

    _MARKER = b"TEST-ONLY-VAULT::"

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._MARKER + plaintext

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(self._MARKER):
            raise ValueError("not a value this test backend encrypted")
        return ciphertext[len(self._MARKER):]


def get_crypto_backend(
    *, _test_only_in_memory_backend: bool = False, key_path: Optional[Path] = None
) -> CryptoBackend:
    """Pilot-integration correction (section 2/4): DpapiLocalMachineBackend
    has existed since INC-13, but this factory never actually returned it
    -- it unconditionally raised, meaning production session storage was
    structurally unusable end-to-end. It now returns a real
    DpapiLocalMachineBackend on Windows (the only platform DPAPI exists
    on) and still fails closed everywhere else -- never a plaintext or
    weaker fallback, on any platform."""
    if _test_only_in_memory_backend:
        return TestOnlyInMemoryCryptoBackend()
    if key_path is not None:
        # An explicit key file selects the portable AES-GCM backend on any
        # platform. Never chosen implicitly: existing Windows installs
        # keep DPAPI unless a key path is configured.
        return AesGcmSessionVaultBackend.from_key_file(key_path)
    if sys.platform != "win32":
        raise ProductionCryptoBackendUnavailable(
            "no production DPAPI LocalMachine backend is available on this platform and no "
            "session vault key file is configured; the vault refuses rather than falling back "
            "to a weaker backend"
        )
    return DpapiLocalMachineBackend()


# --------------------------------------------------------------------- #
# ACL verification -- a hard precondition, not "where feasible" (SEC-5)
# --------------------------------------------------------------------- #


class AclVerifier(Protocol):
    def verify_restrictive(self, path: Path) -> bool: ...


class WindowsAclVerifier:
    """Verifies the vault directory grants access to no broad principal
    (Everyone/Authenticated Users/Users) via PowerShell's Get-Acl,
    checked by well-known SID rather than by localized display name
    (Fable-review correction: `icacls`'s principal names are localized --
    e.g. "Tout le monde"/"Utilisateurs authentifiés" on French
    Windows, plausible for this deployment -- so matching the English
    substrings "Everyone"/"Authenticated Users" silently passes a
    world-readable directory on a non-English system, defeating the sole
    confidentiality control for LocalMachine DPAPI ciphertext). SIDs are
    locale-independent: S-1-1-0 (Everyone), S-1-5-11 (Authenticated
    Users), S-1-5-32-545 (Users)."""

    _DISALLOWED_SIDS = ("S-1-1-0", "S-1-5-11", "S-1-5-32-545")

    def verify_restrictive(self, path: Path) -> bool:
        import subprocess

        # The path travels in the ENVIRONMENT, not as a trailing argv item.
        # powershell.exe -Command treats what follows the script as further
        # command text, not as $args -- so `$args[0]` was empty on a real
        # Windows host and Get-Acl ran against an empty -LiteralPath. That
        # made the verifier fail every time it was actually exercised.
        #
        # An environment variable also removes the quoting question
        # entirely: a vault path containing a space, a quote or a `$` is
        # read as data by $env:, never parsed as PowerShell.
        script = (
            "$acl = Get-Acl -LiteralPath $env:MCMA_ACL_PATH; "
            "$acl.Access | ForEach-Object { "
            "  try { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } "
            "  catch { $_.IdentityReference.Value } "
            "}"
        )
        environment = {**os.environ, "MCMA_ACL_PATH": str(path)}
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=15, env=environment,
        )
        if result.returncode != 0:
            # Fail closed: a verifier that could not run has not verified
            # anything, and "could not check" must never read as "safe".
            return False
        sids_granted = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return not any(sid in sids_granted for sid in self._DISALLOWED_SIDS)


class PosixVaultDirectoryVerifier:
    """POSIX equivalent of the ACL precondition: the vault directory must
    be a REAL directory (a symlink is refused), owned by the running user
    and inaccessible to group and others (mode 0700 or stricter).

    Checked on an open file descriptor -- O_NOFOLLOW | O_DIRECTORY, then
    fstat -- so the answer describes the object actually opened and cannot
    be raced by swapping the path between check and use. Anything that
    cannot be verified fails closed."""

    def verify_restrictive(self, path: Path) -> bool:
        if os.name != "posix":
            return False
        import stat as _stat

        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError:
            return False
        try:
            info = os.fstat(fd)
        except OSError:
            return False
        finally:
            os.close(fd)
        return (
            _stat.S_ISDIR(info.st_mode)
            and not (info.st_mode & 0o077)
            and info.st_uid == os.geteuid()
        )


class TestOnlyAclVerifier:
    """TEST-ONLY: a fixed, injected result -- never selectable in
    production."""

    def __init__(self, result: bool) -> None:
        self._result = result

    def verify_restrictive(self, path: Path) -> bool:
        return self._result


def get_acl_verifier(*, _test_only_result: Optional[bool] = None) -> AclVerifier:
    if _test_only_result is not None:
        return TestOnlyAclVerifier(_test_only_result)
    if os.name == "posix":
        return PosixVaultDirectoryVerifier()
    return WindowsAclVerifier()


# --------------------------------------------------------------------- #
# Vault errors
# --------------------------------------------------------------------- #


class VaultAclPreconditionFailed(Exception):
    """The service-account-only NTFS ACL could not be set/verified on the
    vault directory -- the store refuses (SEC-5 hard precondition)."""


class SessionDecryptionFailed(Exception):
    pass


class SessionBindingMismatch(Exception):
    """The opened portal identity's fingerprint does not match the
    account this session is bound to."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------- #
# Store / rotate / revoke / load
# --------------------------------------------------------------------- #


def store_session(
    conn,
    lease_handle,
    account_id: str,
    storage_state: bytes,
    *,
    vault_dir: Path,
    backend: CryptoBackend,
    acl_verifier: AclVerifier,
    identity_fingerprint: Optional[str] = None,
) -> str:
    """Acquires no lease itself -- the CALLER must already hold (and pass)
    a valid lease for this account (test_service_acquires_lease_before_
    session_replace proves the ordering). Atomic file replacement: writes
    to a temp file in the SAME directory, then os.replace() (atomic on
    the same filesystem) -- there is never a window where a reader could
    observe a partially-written ciphertext file."""
    if lease_handle.account_id != account_id:
        raise ValueError("lease_handle does not belong to this account")

    vault_dir = Path(vault_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)
    if not acl_verifier.verify_restrictive(vault_dir):
        raise VaultAclPreconditionFailed(
            f"service-account-only NTFS ACL could not be verified on {vault_dir}; refusing to store"
        )

    ciphertext = _backend_for_account(backend, account_id).encrypt(storage_state)
    storage_ref = uuid.uuid4().hex
    final_path = vault_dir / f"{storage_ref}.session"
    tmp_path = vault_dir / f".{storage_ref}.session.tmp"
    tmp_path.write_bytes(ciphertext)
    os.replace(tmp_path, final_path)  # atomic on the same filesystem

    # Fable-review correction: the old-row REVOKE and the new-row INSERT
    # used to be two separate autocommit statements (db.py opens
    # connections with isolation_level=None). A crash between them left
    # TWO ACTIVE rows; load_and_verify_session's "most recent ACTIVE"
    # query would still pick the new one, but revoke_session (which only
    # ever revokes the newest ACTIVE row) would then "resurrect" the
    # older one as the effective active session on a later revoke --
    # revocation would not reliably force re-login. One explicit
    # transaction makes the row-level swap atomic, matching the
    # already-atomic file replacement above.
    session_id = uuid.uuid4().hex
    conn.execute("BEGIN IMMEDIATE")
    try:
        previous = conn.execute(
            "SELECT session_id, storage_ref FROM portal_sessions WHERE account_id = ? AND status = 'ACTIVE' "
            "ORDER BY rowid DESC LIMIT 1",
            (account_id,),
        ).fetchone()
        if previous is not None:
            conn.execute(
                "UPDATE portal_sessions SET status = 'REVOKED' WHERE session_id = ?", (previous["session_id"],)
            )
        conn.execute(
            "INSERT INTO portal_sessions (session_id, account_id, storage_ref, status, last_validated_at, "
            "opened_identity_fingerprint) VALUES (?, ?, ?, 'ACTIVE', ?, ?)",
            (session_id, account_id, storage_ref, _utcnow_iso(), identity_fingerprint),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    if previous is not None:
        old_path = vault_dir / f"{previous['storage_ref']}.session"
        old_path.unlink(missing_ok=True)

    return session_id


def load_and_verify_session(
    conn,
    account_id: str,
    *,
    vault_dir: Path,
    backend: CryptoBackend,
    observed_identity_fingerprint: Optional[str] = None,
) -> bytes:
    row = conn.execute(
        "SELECT session_id, storage_ref, status, opened_identity_fingerprint FROM portal_sessions "
        "WHERE account_id = ? AND status = 'ACTIVE' ORDER BY rowid DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    if row is None:
        raise SessionDecryptionFailed(f"no active session for account {account_id!r}")

    path = Path(vault_dir) / f"{row['storage_ref']}.session"
    try:
        ciphertext = path.read_bytes()
    except OSError as exc:
        raise SessionDecryptionFailed(f"session file unreadable for account {account_id!r}") from exc

    try:
        plaintext = _backend_for_account(backend, account_id).decrypt(ciphertext)
    except Exception as exc:
        raise SessionDecryptionFailed(f"decryption failed for account {account_id!r}") from exc

    if observed_identity_fingerprint is not None and row["opened_identity_fingerprint"] is not None:
        if observed_identity_fingerprint != row["opened_identity_fingerprint"]:
            raise SessionBindingMismatch(f"identity fingerprint mismatch for account {account_id!r}")

    return plaintext


def revoke_session(conn, account_id: str, *, vault_dir: Path) -> None:
    """Revocation forces re-login: the row is marked REVOKED and the file
    is deleted -- load_and_verify_session finds no ACTIVE row afterward."""
    row = conn.execute(
        "SELECT session_id, storage_ref FROM portal_sessions WHERE account_id = ? AND status = 'ACTIVE' "
        "ORDER BY rowid DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute("UPDATE portal_sessions SET status = 'REVOKED' WHERE session_id = ?", (row["session_id"],))
    (Path(vault_dir) / f"{row['storage_ref']}.session").unlink(missing_ok=True)
