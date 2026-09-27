"""
mcma.app.auth.users -- the ONE place platform (MCMA Platform) users are
validated, created and changed. Used by the offline first-admin command
and by the admin web API, so username normalization, the password policy,
hashing (mcma.app.auth.passwords), transactions and audit conventions
cannot drift between the two.

These are PLATFORM accounts only. Nothing here reads, writes or duplicates
the stored MCMA/MAMDA portal credentials or browser sessions.

Rules kept here so every caller gets them:

  * usernames are normalized (NFKC, trimmed, lower-cased) and must match
    ^[a-z0-9][a-z0-9._-]{2,31}$; uniqueness is checked case-insensitively
    inside the same write transaction, with the table's UNIQUE constraint as
    the backstop;
  * one password policy (12-128 characters, not the username, not a trivially
    repeated/sequential string);
  * every multi-row change (user + account access + audit) is one
    BEGIN IMMEDIATE transaction;
  * the last active administrator can never be deactivated or demoted, and an
    administrator can never deactivate or demote their OWN account;
  * audit rows carry only a hash of non-secret fields -- never a password or
    a password hash.

Validation errors carry a stable `code` (the API returns it) and a French
`message` (the offline CLI prints it).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Optional

from mcma.app.auth.passwords import hash_password
from mcma.app.auth.permissions import ROLE_PERMISSIONS
from mcma.app.provisioning import ensure_canonical_accounts
from mcma.domain.portal_accounts import THE_FOUR_PROFILES, canonical_account_id

ROLES: tuple[str, ...] = tuple(ROLE_PERMISSIONS)          # admin, operator, viewer
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class UserInputError(Exception):
    """A request the caller can correct. `status` is the HTTP status the API
    uses; `message` is French and safe to show (it never echoes input)."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _err(code: str, message: str, status: int = 400) -> UserInputError:
    return UserInputError(code, message, status)


# --------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------- #


def normalize_username(raw: object) -> str:
    if not isinstance(raw, str):
        raise _err("USERNAME_INVALID", "Le nom d'utilisateur est obligatoire.")
    username = unicodedata.normalize("NFKC", raw).strip().lower()
    if not USERNAME_PATTERN.match(username):
        raise _err(
            "USERNAME_INVALID",
            "Le nom d'utilisateur doit contenir 3 à 32 caractères (lettres minuscules, chiffres, « . », « _ » ou « - ») "
            "et commencer par une lettre ou un chiffre.",
        )
    return username


def validate_password(password: object, username: str = "") -> str:
    """Returns the password unchanged when it satisfies the policy."""
    if not isinstance(password, str) or password == "":
        raise _err("PASSWORD_TOO_SHORT", f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères.")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise _err("PASSWORD_TOO_SHORT", f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise _err("PASSWORD_TOO_LONG", f"Le mot de passe ne doit pas dépasser {PASSWORD_MAX_LENGTH} caractères.")
    if username and username.lower() in password.lower():
        raise _err("PASSWORD_CONTAINS_USERNAME", "Le mot de passe ne doit pas contenir le nom d'utilisateur.")
    if len(set(password)) < 4 or _is_sequence(password):
        raise _err(
            "PASSWORD_TOO_SIMPLE",
            "Le mot de passe est trop simple (caractères répétés ou suite évidente). Choisissez une phrase plus longue.",
        )
    return password


def _is_sequence(password: str) -> bool:
    lowered = password.lower()
    steps = {ord(b) - ord(a) for a, b in zip(lowered, lowered[1:])}
    return len(steps) == 1 and steps <= {1, -1}


def validate_role(role: object) -> str:
    if not isinstance(role, str) or role not in ROLES:
        raise _err("ROLE_INVALID", "Rôle invalide : choisissez administrateur, opérateur ou lecteur.")
    return role


def canonical_account_ids() -> frozenset:
    return frozenset(canonical_account_id(profile) for profile in THE_FOUR_PROFILES)


def validate_account_ids(conn, account_ids: object) -> tuple:
    """Only the four canonical portal accounts, and only ones that exist."""
    if not isinstance(account_ids, (list, tuple)) or not all(isinstance(a, str) for a in account_ids):
        raise _err("ACCOUNT_UNKNOWN", "La liste des comptes portail est invalide.")
    unique = tuple(sorted(set(account_ids)))
    canonical = canonical_account_ids()
    existing = {row["account_id"] for row in conn.execute("SELECT account_id FROM accounts").fetchall()}
    if any(a not in canonical or a not in existing for a in unique):
        raise _err("ACCOUNT_UNKNOWN", "Un des comptes portail sélectionnés n'existe pas.")
    return unique


def _all_portal_accounts(conn) -> tuple:
    """Every canonical portal account that exists. Administrators always hold
    all of them ("Administrateur: full access"), which also guarantees the
    admin page can offer every account as a choice."""
    canonical = canonical_account_ids()
    return tuple(sorted(
        r["account_id"] for r in conn.execute("SELECT account_id FROM accounts").fetchall()
        if r["account_id"] in canonical
    ))


# --------------------------------------------------------------------- #
# transactions and audit
# --------------------------------------------------------------------- #


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def write_transaction(conn):
    """BEGIN IMMEDIATE ... COMMIT, ROLLBACK on any exception. The connection
    holds its lock for the whole transaction (SerializedConnection)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _audit(conn, action: str, actor_user_id: Optional[str], summary: str) -> None:
    """Hash of NON-secret facts only (user id, role, active flag, account set)."""
    conn.execute(
        "INSERT INTO audit_events (audit_id, actor_user_id, account_id, job_id, action, before_hash, after_hash, "
        "created_at) VALUES (?, ?, NULL, NULL, ?, NULL, ?, ?)",
        (uuid.uuid4().hex, actor_user_id, action, hashlib.sha256(summary.encode("utf-8")).hexdigest(), _now()),
    )


def _summary(user_id: str, role: str, active: bool, account_ids: Iterable[str]) -> str:
    return f"{user_id}|{role}|{int(active)}|{','.join(sorted(account_ids))}"


# --------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------- #


def _accounts_of(conn, user_id: str) -> list:
    rows = conn.execute("SELECT account_id FROM user_account_access WHERE user_id = ?", (user_id,)).fetchall()
    return sorted(r["account_id"] for r in rows)


def user_view(conn, row) -> dict:
    """The ONLY shape a user leaves this module in: never a hash or password."""
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "role": row["role"],
        "active": bool(row["active"]),
        "account_ids": _accounts_of(conn, row["user_id"]),
    }


def list_users(conn) -> list:
    rows = conn.execute("SELECT user_id, username, role, active FROM users ORDER BY lower(username)").fetchall()
    return [user_view(conn, r) for r in rows]


def user_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def _get(conn, user_id: str):
    row = conn.execute("SELECT user_id, username, role, active FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise _err("USER_NOT_FOUND", "Utilisateur introuvable.", 404)
    return row


def _active_admin_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND active = 1").fetchone()["c"]


# --------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------- #


def _insert_user(conn, username: str, password: str, role: str, account_ids: Iterable[str]) -> str:
    """Caller holds the write transaction. Case-insensitive uniqueness is
    checked here, in the same transaction as the insert."""
    if conn.execute("SELECT 1 FROM users WHERE lower(username) = ?", (username,)).fetchone():
        raise _err("USERNAME_TAKEN", "Ce nom d'utilisateur existe déjà.", 409)
    user_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, ?, 1)",
        (user_id, username, hash_password(password), role),
    )
    now = _now()
    for account_id in account_ids:
        conn.execute(
            "INSERT OR IGNORE INTO user_account_access (user_id, account_id, granted_at) VALUES (?, ?, ?)",
            (user_id, account_id, now),
        )
    return user_id


def create_first_admin(conn, username_raw: object, password: object) -> dict:
    """Offline provisioning, ONE write transaction, in this order:

      1. (before any write) validate the username and the password policy;
      2. BEGIN IMMEDIATE, then check the users table is EMPTY -- if any user
         exists the command refuses and NOTHING has been written, not even the
         canonical accounts;
      3. only then ensure the four canonical portal accounts exist (the
         existing provisioning logic, run inside this same transaction);
      4. create the administrator, grant EXACTLY the four canonical account
         ids (never other rows that may exist in `accounts`), write the audit
         event.

    Any exception rolls back all of it: accounts, user, access grants, audit."""
    username = normalize_username(username_raw)
    validate_password(password, username)
    with write_transaction(conn):
        if user_count(conn) != 0:
            raise _err(
                "USERS_EXIST",
                "Des utilisateurs existent déjà : la création du premier administrateur est refusée. "
                "Rien n'a été modifié.",
                409,
            )
        ensure_canonical_accounts(conn)
        account_ids = list(_all_portal_accounts(conn))
        if set(account_ids) != set(canonical_account_ids()):
            raise _err("ACCOUNT_UNKNOWN", "Les comptes portail canoniques n'ont pas pu être créés.", 500)
        user_id = _insert_user(conn, username, str(password), "admin", account_ids)
        _audit(conn, "user.first_admin_created", None, _summary(user_id, "admin", True, account_ids))
    return user_view(conn, _get(conn, user_id))


def create_user(conn, *, actor_user_id: str, username: object, password: object, role: object, account_ids: object) -> dict:
    name = normalize_username(username)
    validate_password(password, name)
    checked_role = validate_role(role)
    accounts = validate_account_ids(conn, account_ids)
    if checked_role == "admin":
        accounts = _all_portal_accounts(conn)
    with write_transaction(conn):
        user_id = _insert_user(conn, name, str(password), checked_role, accounts)
        _audit(conn, "user.created", actor_user_id, _summary(user_id, checked_role, True, accounts))
    return user_view(conn, _get(conn, user_id))


def update_user(
    conn, *, actor_user_id: str, user_id: str,
    active: object = None, role: object = None, account_ids: object = None,
) -> tuple:
    """Applies any of active/role/account_ids atomically. Returns
    (user_view, must_end_sessions): True when the user was deactivated or
    demoted, so the caller can drop that user's live sessions."""
    if active is not None and not isinstance(active, bool):
        raise _err("BAD_REQUEST", "Valeur invalide pour l'état du compte.")
    new_role = validate_role(role) if role is not None else None
    accounts = validate_account_ids(conn, account_ids) if account_ids is not None else None

    with write_transaction(conn):
        target = _get(conn, user_id)
        was_admin = target["role"] == "admin" and bool(target["active"])
        loses_admin = was_admin and ((active is False) or (new_role is not None and new_role != "admin"))
        if loses_admin and _active_admin_count(conn) <= 1:
            raise _err("LAST_ADMIN", "Impossible : c'est le dernier administrateur actif.", 409)
        if user_id == actor_user_id and ((active is False) or (new_role is not None and new_role != target["role"])):
            raise _err(
                "SELF_LOCKOUT",
                "Vous ne pouvez pas désactiver ou modifier le rôle de votre propre compte.",
                409,
            )
        if active is not None:
            conn.execute("UPDATE users SET active = ? WHERE user_id = ?", (1 if active else 0, user_id))
        if new_role is not None:
            conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (new_role, user_id))
        if (new_role or target["role"]) == "admin":
            accounts = _all_portal_accounts(conn)          # admins always hold every portal account
        if accounts is not None:
            conn.execute(
                "DELETE FROM user_account_access WHERE user_id = ? AND account_id NOT IN (%s)"
                % (",".join("?" for _ in accounts) or "''"),
                (user_id, *accounts),
            )
            now = _now()
            for account_id in accounts:
                conn.execute(
                    "INSERT OR IGNORE INTO user_account_access (user_id, account_id, granted_at) VALUES (?, ?, ?)",
                    (user_id, account_id, now),
                )
        updated = _get(conn, user_id)
        _audit(
            conn, "user.updated", actor_user_id,
            _summary(user_id, updated["role"], bool(updated["active"]), _accounts_of(conn, user_id)),
        )
    return user_view(conn, updated), bool(loses_admin or active is False)


def reset_password(conn, *, actor_user_id: str, user_id: str, password: object) -> None:
    with write_transaction(conn):
        target = _get(conn, user_id)
        validate_password(password, target["username"])
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?", (hash_password(str(password)), user_id)
        )
        _audit(conn, "user.password_reset", actor_user_id, _summary(user_id, target["role"], bool(target["active"]), []))
