"""
mcma.app.runners.registry -- the ONE owner of workstation-runner registry
rules and transactions (Phase 1A: enrollment, identity, heartbeat,
readiness, revocation). No job claiming, dispatch or locks; no browser; no
portal login. Runner credentials are a separate world from employee
platform sessions: they are never cookies, never accepted by employee
endpoints, and employee sessions are never accepted by runner endpoints.

Trust boundaries and rules
  * Pairing code and runner secret: 256 random bits (secrets.token_urlsafe(32)),
    shown ONCE, stored ONLY as SHA-256 hex. Lookup is by digest (index seek),
    then confirmed with a constant-time comparison.
  * A code is single use, expires (default 10 minutes), and is bound to the
    admin who created it and to one target employee. Expired, consumed,
    revoked, unknown -- all refuse with the SAME error.
  * Target employee must be active, hold jobs:execute (so a viewer cannot be
    paired) and have access to at least one canonical MCMA account. At most
    one ACTIVE runner per employee (also a partial unique index).
  * Heartbeats carry only: protocol version, app version, and a closed-enum
    readiness for canonical MCMA accounts the assigned employee can access.
    MAMDA / unknown / inaccessible accounts are rejected (service check +
    CHECK constraint). last_seen_at is always the SERVER clock. The runner
    identity and user come from the credential, never from the request.
  * "Online" is derived: server time - last_seen_at <= OFFLINE_AFTER_SECONDS.
  * FAIL-CLOSED RULE: a runner whose assigned employee is deactivated, loses
    jobs:execute, or loses access to every MCMA account is REVOKED
    (durable, audited) the next time it is looked at (heartbeat, status or
    list) and its credential stops working. Restoring the employee does not
    revive it; an administrator pairs a new runner.
  * Audit rows hold ids and a hash of non-secret facts -- never a secret.

All writes are single BEGIN IMMEDIATE transactions
(mcma.app.auth.users.write_transaction).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from mcma.app.auth.permissions import role_has_permission
from mcma.app.auth.users import UserInputError, _audit, write_transaction
from mcma.domain.enums import Permission

# --- centralized protocol constants (tested) -------------------------------
ENROLLMENT_TTL_SECONDS = 600            # pairing codes live 10 minutes
HEARTBEAT_INTERVAL_SECONDS = 10         # what the server tells runners to use
OFFLINE_AFTER_SECONDS = 30              # ~3 missed heartbeats => offline
SUPPORTED_PROTOCOL_VERSIONS = frozenset({1})
MAX_RUNNER_SECRET_LENGTH = 200

PAIRING_CODE_PREFIX = "mcma_pc_"
RUNNER_SECRET_PREFIX = "mcma_rs_"
DEFAULT_RUNNER_LABEL = "Poste agent"

# Only these two may ever be runner capabilities (MAMDA is notification-only).
RUNNER_ACCOUNT_IDS = ("acct-mcma-oujda", "acct-mcma-nador")
SESSION_STATES = ("NOT_CONFIGURED", "LOGIN_REQUIRED", "READY", "ERROR")

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$")


def _err(code: str, message: str, status: int = 400) -> UserInputError:
    return UserInputError(code, message, status)


# --------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------- #


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse(text: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(text) if text else None


def digest_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _digests_equal(stored: str, computed: str) -> bool:
    return hmac.compare_digest(stored, computed)


def new_pairing_code() -> str:
    return PAIRING_CODE_PREFIX + secrets.token_urlsafe(32)


def new_runner_secret() -> str:
    return RUNNER_SECRET_PREFIX + secrets.token_urlsafe(32)


def validate_label(raw: object, *, required: bool = False) -> Optional[str]:
    if raw is None:
        if required:
            raise _err("RUNNER_LABEL_INVALID", "Le nom du poste est obligatoire.")
        return None
    if not isinstance(raw, str) or not _LABEL_RE.match(raw.strip()):
        raise _err(
            "RUNNER_LABEL_INVALID",
            "Le nom du poste doit contenir 1 à 40 caractères (lettres, chiffres, espace, « . », « _ » ou « - »).",
        )
    return raw.strip()


# --------------------------------------------------------------------- #
# eligibility
# --------------------------------------------------------------------- #


def _mcma_accounts_of(conn, user_id: str) -> list:
    rows = conn.execute("SELECT account_id FROM user_account_access WHERE user_id = ?", (user_id,)).fetchall()
    return sorted(r["account_id"] for r in rows if r["account_id"] in RUNNER_ACCOUNT_IDS)


def _ineligibility(conn, user_id: str) -> Optional[str]:
    """None when the employee may have a runner, else a fixed reason code."""
    row = conn.execute("SELECT role, active FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return "USER_NOT_FOUND"
    if not row["active"]:
        return "INACTIVE"
    if not role_has_permission(row["role"], Permission.JOBS_EXECUTE):
        return "NO_EXECUTE_PERMISSION"
    if not _mcma_accounts_of(conn, user_id):
        return "NO_MCMA_ACCOUNT"
    return None


def _active_runner_row(conn, user_id: str):
    return conn.execute("SELECT * FROM runners WHERE user_id = ? AND status = 'ACTIVE'", (user_id,)).fetchone()


# --------------------------------------------------------------------- #
# views
# --------------------------------------------------------------------- #


def _connection_status(row, now: datetime) -> str:
    if row["status"] == "REVOKED":
        return "REVOKED"
    seen = _parse(row["last_seen_at"])
    if seen is None or (now - seen).total_seconds() > OFFLINE_AFTER_SECONDS:
        return "OFFLINE"
    return "ONLINE"


def _sessions(conn, row) -> list:
    if row["status"] == "REVOKED":
        return []
    reported = {
        r["account_id"]: r["session_state"]
        for r in conn.execute(
            "SELECT account_id, session_state FROM runner_account_capabilities WHERE runner_id = ?", (row["runner_id"],)
        ).fetchall()
    }
    allowed = _mcma_accounts_of(conn, row["user_id"])
    return [{"account_id": a, "state": reported.get(a, "NOT_CONFIGURED")} for a in RUNNER_ACCOUNT_IDS if a in allowed]


def runner_view(conn, row, now: datetime) -> dict:
    """Safe projection: never a digest, secret or code."""
    username = conn.execute("SELECT username FROM users WHERE user_id = ?", (row["user_id"],)).fetchone()
    return {
        "runner_id": row["runner_id"],
        "user_id": row["user_id"],
        "username": username["username"] if username else None,
        "runner_label": row["runner_label"],
        "status": _connection_status(row, now),
        "last_seen_at": row["last_seen_at"],
        "created_at": row["created_at"],
        "revoked_at": row["revoked_at"],
        "app_version": row["app_version"],
        "protocol_version": row["protocol_version"],
        "sessions": _sessions(conn, row),
    }


# --------------------------------------------------------------------- #
# fail-closed enforcement
# --------------------------------------------------------------------- #


def _revoke_row(conn, row, *, actor_user_id: Optional[str], action: str, now: datetime) -> None:
    conn.execute(
        "UPDATE runners SET status = 'REVOKED', revoked_at = ?, revoked_by_user_id = ? WHERE runner_id = ? AND status = 'ACTIVE'",
        (_iso(now), actor_user_id, row["runner_id"]),
    )
    _audit(conn, action, actor_user_id, f"{row['runner_id']}|{row['user_id']}|REVOKED")


def enforce_eligibility(conn, *, now: Optional[datetime] = None) -> int:
    """Revokes every ACTIVE runner whose employee is no longer eligible.
    Cheap (a handful of runners); called before lists, status and heartbeat
    so no read can show or honour a runner that must already be dead."""
    now = now or utcnow()
    revoked = 0
    for row in conn.execute("SELECT * FROM runners WHERE status = 'ACTIVE'").fetchall():
        if _ineligibility(conn, row["user_id"]) is not None:
            with write_transaction(conn):
                fresh = conn.execute("SELECT * FROM runners WHERE runner_id = ?", (row["runner_id"],)).fetchone()
                if fresh["status"] == "ACTIVE" and _ineligibility(conn, fresh["user_id"]) is not None:
                    _revoke_row(conn, fresh, actor_user_id=None, action="runner.auto_revoked", now=now)
                    revoked += 1
    return revoked


# --------------------------------------------------------------------- #
# admin operations
# --------------------------------------------------------------------- #


def create_enrollment(
    conn, *, actor_user_id: str, target_user_id: object, runner_label: object = None, now: Optional[datetime] = None,
) -> dict:
    """Returns {"enrollment": safe metadata, "pairing_code": raw code}. The
    raw code exists only in this return value."""
    now = now or utcnow()
    if not isinstance(target_user_id, str) or not target_user_id or len(target_user_id) > 64:
        raise _err("USER_NOT_FOUND", "Utilisateur introuvable.", 404)
    label = validate_label(runner_label)
    enforce_eligibility(conn, now=now)
    code = new_pairing_code()
    enrollment_id = uuid.uuid4().hex
    expires = now + timedelta(seconds=ENROLLMENT_TTL_SECONDS)
    with write_transaction(conn):
        target = conn.execute("SELECT user_id, username FROM users WHERE user_id = ?", (target_user_id,)).fetchone()
        if target is None:
            raise _err("USER_NOT_FOUND", "Utilisateur introuvable.", 404)
        if _ineligibility(conn, target_user_id) is not None:
            raise _err(
                "TARGET_NOT_ELIGIBLE",
                "Cet employé ne peut pas recevoir de poste agent (compte actif, droit d'exécution "
                "et accès à MCMA Oujda ou Nador requis).",
                409,
            )
        if _active_runner_row(conn, target_user_id) is not None:
            raise _err(
                "RUNNER_ALREADY_ACTIVE",
                "Cet employé a déjà un poste agent actif : révoquez-le avant d'en associer un autre.",
                409,
            )
        # Older unused codes for this employee die when a new one is issued.
        conn.execute(
            "UPDATE runner_enrollments SET revoked_at = ?, revoked_by_user_id = ? "
            "WHERE target_user_id = ? AND consumed_at IS NULL AND revoked_at IS NULL",
            (_iso(now), actor_user_id, target_user_id),
        )
        conn.execute(
            "INSERT INTO runner_enrollments (enrollment_id, code_digest, target_user_id, created_by_user_id, "
            "runner_label, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (enrollment_id, digest_secret(code), target_user_id, actor_user_id, label, _iso(now), _iso(expires)),
        )
        _audit(conn, "runner.enrollment_created", actor_user_id, f"{enrollment_id}|{target_user_id}")
    return {
        "enrollment": {
            "enrollment_id": enrollment_id, "target_user_id": target_user_id,
            "target_username": target["username"], "runner_label": label, "expires_at": _iso(expires),
        },
        "pairing_code": code,
    }


def revoke_runner(conn, *, actor_user_id: str, runner_id: str, now: Optional[datetime] = None) -> tuple:
    """Returns (runner_view, already_revoked). Idempotent; audited once."""
    now = now or utcnow()
    with write_transaction(conn):
        row = conn.execute("SELECT * FROM runners WHERE runner_id = ?", (runner_id,)).fetchone()
        if row is None:
            raise _err("RUNNER_NOT_FOUND", "Poste agent introuvable.", 404)
        already = row["status"] == "REVOKED"
        if not already:
            _revoke_row(conn, row, actor_user_id=actor_user_id, action="runner.revoked", now=now)
    return runner_view(conn, conn.execute("SELECT * FROM runners WHERE runner_id = ?", (runner_id,)).fetchone(), now), already


def admin_overview(conn, *, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    enforce_eligibility(conn, now=now)
    runners = [
        runner_view(conn, row, now)
        for row in conn.execute("SELECT * FROM runners ORDER BY created_at DESC, runner_id").fetchall()
    ]
    pending = [
        {
            "enrollment_id": r["enrollment_id"], "target_user_id": r["target_user_id"],
            "target_username": r["username"], "runner_label": r["runner_label"], "expires_at": r["expires_at"],
        }
        for r in conn.execute(
            "SELECT e.*, u.username FROM runner_enrollments e JOIN users u ON u.user_id = e.target_user_id "
            "WHERE e.consumed_at IS NULL AND e.revoked_at IS NULL AND e.expires_at > ? ORDER BY e.created_at",
            (_iso(now),),
        ).fetchall()
    ]
    eligible = [
        {"user_id": u["user_id"], "username": u["username"]}
        for u in conn.execute("SELECT user_id, username FROM users ORDER BY lower(username)").fetchall()
        if _ineligibility(conn, u["user_id"]) is None and _active_runner_row(conn, u["user_id"]) is None
    ]
    return {
        "runners": runners, "pending_enrollments": pending, "eligible_employees": eligible,
        "server_time": _iso(now), "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
        "offline_after_seconds": OFFLINE_AFTER_SECONDS,
    }


# --------------------------------------------------------------------- #
# employee status
# --------------------------------------------------------------------- #


def runner_status_for_user(conn, user_id: str, *, now: Optional[datetime] = None) -> dict:
    """ONLY this employee's own runner. Never another user's."""
    now = now or utcnow()
    enforce_eligibility(conn, now=now)
    row = _active_runner_row(conn, user_id) or conn.execute(
        "SELECT * FROM runners WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id,)
    ).fetchone()
    if row is None:
        return {"status": "UNPAIRED", "runner_label": None, "last_seen_at": None, "protocol_version": None, "sessions": []}
    view = runner_view(conn, row, now)
    return {
        "status": view["status"], "runner_label": view["runner_label"], "last_seen_at": view["last_seen_at"],
        "protocol_version": view["protocol_version"], "sessions": view["sessions"],
    }


# --------------------------------------------------------------------- #
# machine operations
# --------------------------------------------------------------------- #

_INVALID_CODE = ("PAIRING_CODE_INVALID", "Code d'association invalide, expiré ou déjà utilisé.")


def _validated_versions(protocol_version: object, app_version: object) -> tuple:
    if isinstance(protocol_version, bool) or not isinstance(protocol_version, int) \
            or protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise _err("PROTOCOL_UNSUPPORTED", "Version de protocole non prise en charge.")
    if not isinstance(app_version, str) or not _VERSION_RE.match(app_version):
        raise _err("BAD_REQUEST", "Version de l'application invalide.")
    return protocol_version, app_version


def enroll(
    conn, *, pairing_code: object, runner_label: object = None, protocol_version: object, app_version: object,
    now: Optional[datetime] = None,
) -> dict:
    """Consumes a pairing code and creates the runner in ONE transaction.
    Returns the credential exactly once."""
    now = now or utcnow()
    protocol, version = _validated_versions(protocol_version, app_version)
    label_from_runner = validate_label(runner_label)
    if not isinstance(pairing_code, str) or not (10 <= len(pairing_code) <= MAX_RUNNER_SECRET_LENGTH):
        raise _err(*_INVALID_CODE)
    computed = digest_secret(pairing_code)
    secret = new_runner_secret()
    runner_id = uuid.uuid4().hex
    try:
        with write_transaction(conn):
            row = conn.execute("SELECT * FROM runner_enrollments WHERE code_digest = ?", (computed,)).fetchone()
            if (
                row is None
                or not _digests_equal(row["code_digest"], computed)
                or row["consumed_at"] is not None
                or row["revoked_at"] is not None
                or _parse(row["expires_at"]) <= now
                or _ineligibility(conn, row["target_user_id"]) is not None
                or _active_runner_row(conn, row["target_user_id"]) is not None
            ):
                raise _err(*_INVALID_CODE)                           # one answer for every refusal
            label = row["runner_label"] or label_from_runner or DEFAULT_RUNNER_LABEL
            conn.execute("UPDATE runner_enrollments SET consumed_at = ? WHERE enrollment_id = ?", (_iso(now), row["enrollment_id"]))
            conn.execute(
                "INSERT INTO runners (runner_id, user_id, credential_digest, runner_label, status, protocol_version, "
                "app_version, enrollment_id, created_at) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)",
                (runner_id, row["target_user_id"], digest_secret(secret), label, protocol, version,
                 row["enrollment_id"], _iso(now)),
            )
            _audit(conn, "runner.enrolled", row["target_user_id"], f"{runner_id}|{row['target_user_id']}|{row['enrollment_id']}")
            allowed = _mcma_accounts_of(conn, row["target_user_id"])
    except Exception as exc:
        # mcma.app never imports sqlite3 (single-owner contract), so the
        # constraint violation is recognised by name: e.g. a concurrent
        # enrollment won the race for the one-active-runner-per-user index.
        if type(exc).__name__ != "IntegrityError":
            raise
        raise _err(*_INVALID_CODE) from None
    return {
        "runner_id": runner_id, "runner_secret": secret, "runner_label": label,
        "allowed_account_ids": allowed, "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
        "offline_after_seconds": OFFLINE_AFTER_SECONDS, "server_time": _iso(now),
    }


@dataclass(frozen=True)
class RunnerPrincipal:
    """Derived ONLY from the bearer credential."""

    runner_id: str
    user_id: str


def authenticate_runner(conn, bearer: Optional[str], *, now: Optional[datetime] = None) -> Optional[RunnerPrincipal]:
    """None for a missing, malformed, unknown or revoked credential (the
    caller answers a generic 401 that never says which)."""
    if not bearer or len(bearer) > MAX_RUNNER_SECRET_LENGTH or not bearer.startswith(RUNNER_SECRET_PREFIX):
        return None
    computed = digest_secret(bearer)
    row = conn.execute("SELECT * FROM runners WHERE credential_digest = ?", (computed,)).fetchone()
    if row is None or not _digests_equal(row["credential_digest"], computed) or row["status"] != "ACTIVE":
        return None
    if _ineligibility(conn, row["user_id"]) is not None:
        enforce_eligibility(conn, now=now)                             # durable, audited revocation
        return None
    return RunnerPrincipal(row["runner_id"], row["user_id"])


def heartbeat(
    conn, principal: RunnerPrincipal, *, protocol_version: object, app_version: object, sessions: object,
    now: Optional[datetime] = None,
) -> dict:
    """Records liveness (SERVER clock) and per-account readiness."""
    now = now or utcnow()
    protocol, version = _validated_versions(protocol_version, app_version)
    if not isinstance(sessions, list) or len(sessions) > len(RUNNER_ACCOUNT_IDS):
        raise _err("BAD_REQUEST", "Liste de sessions invalide.")
    reported: dict = {}
    for item in sessions:
        if not isinstance(item, dict) or set(item) != {"account_id", "state"}:
            raise _err("BAD_REQUEST", "Session invalide.")
        account_id, state = item["account_id"], item["state"]
        if not isinstance(account_id, str) or account_id not in RUNNER_ACCOUNT_IDS:
            raise _err("ACCOUNT_NOT_ALLOWED", "Compte non autorisé pour un poste agent.")   # MAMDA/unknown
        if not isinstance(state, str) or state not in SESSION_STATES:
            raise _err("BAD_REQUEST", "État de session invalide.")
        if account_id in reported:
            raise _err("BAD_REQUEST", "Compte en double.")
        reported[account_id] = state
    with write_transaction(conn):
        row = conn.execute("SELECT * FROM runners WHERE runner_id = ?", (principal.runner_id,)).fetchone()
        if row is None or row["status"] != "ACTIVE" or _ineligibility(conn, row["user_id"]) is not None:
            raise _err("RUNNER_UNAUTHENTICATED", "Authentification du poste refusée.", 401)
        allowed = _mcma_accounts_of(conn, row["user_id"])
        if any(account_id not in allowed for account_id in reported):
            raise _err("ACCOUNT_NOT_ALLOWED", "Compte non autorisé pour un poste agent.")
        stamp = _iso(now)
        conn.execute(
            "UPDATE runners SET last_seen_at = ?, protocol_version = ?, app_version = ? WHERE runner_id = ?",
            (stamp, protocol, version, principal.runner_id),
        )
        conn.execute("DELETE FROM runner_account_capabilities WHERE runner_id = ?", (principal.runner_id,))
        for account_id, state in reported.items():
            conn.execute(
                "INSERT INTO runner_account_capabilities (runner_id, account_id, session_state, updated_at) VALUES (?, ?, ?, ?)",
                (principal.runner_id, account_id, state, stamp),
            )
    return {
        "status": "ACTIVE", "server_time": stamp, "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
        "offline_after_seconds": OFFLINE_AFTER_SECONDS, "allowed_account_ids": allowed,
    }
