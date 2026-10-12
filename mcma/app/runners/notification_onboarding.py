"""
mcma.app.runners.notification_onboarding -- the ONE owner of the durable
control plane that lets an employee's Windows workstation capture a
SERVER-OWNED notification session (one of the four canonical accounts,
MCMA and MAMDA alike) without the central server ever having a display.

Flow
  1. The employee clicks Se connecter / Reconnecter. request_login() writes a
     short-lived PENDING request bound to the exact account, the exact
     employee and that employee's ACTIVE, online runner, and returns at once.
  2. That runner's claim() turns it into CLAIMED, returning a claim token
     ONCE (only its SHA-256 digest is stored) with a short lease.
  3. The employee signs in -- credentials and OTP go straight into SinAuto on
     their own desktop; this module never sees them.
  4. complete() receives the captured Playwright storage_state over the
     runner's verified HTTPS connection, validates and bounds it
     (mcma.portal.storage_state), takes the EXACT account lease and stores it
     through the existing vault path (store_session -> the AES server key
     already loaded at startup). The payload is never persisted anywhere else
     and never logged.

State machine (closed; enforced again by the CHECK constraints and partial
unique indexes of migration 0009)
    PENDING -> CLAIMED | CANCELLED | EXPIRED | FAILED
    CLAIMED -> SUCCEEDED | FAILED | CANCELLED | EXPIRED
    SUCCEEDED / FAILED / CANCELLED / EXPIRED are terminal and permanent.

Fencing (same design as mcma.app.runners.dispatch): renew/complete/fail match
the claim token digest AND request id AND generation AND runner together; a
lease or request that has reached its deadline is expired with <= semantics
BEFORE any call is served, so a stale token can never revive or modify a
newer request. Every refusal of a claim holder is the same fixed
CLAIM_NOT_FOUND.

Scope guard: this module never touches RUNNER_ACCOUNT_IDS, runner heartbeat
readiness, runner_account_capabilities or job dispatch eligibility. MAMDA
stays notification-only; all four accounts are allowed HERE only.

No browser, no Playwright, no writer: the central server stays headless.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from mcma.app.auth.permissions import role_has_permission
from mcma.app.auth.users import UserInputError, write_transaction
from mcma.app.runners import registry
from mcma.app.runners.registry import RunnerPrincipal
from mcma.domain.enums import Permission
from mcma.persistence.leases import LeaseNotHeld, acquire_lease
from mcma.portal.storage_state import PortalPolicy, StorageStateRejected, validate_storage_state
from mcma.portal.vault import (
    activate_staged_session, cleanup_replaced_session, discard_staged_session, stage_session,
)

logger = logging.getLogger(__name__)

NOTIFICATION_ACCOUNT_IDS = ("acct-mcma-oujda", "acct-mcma-nador", "acct-mamda-oujda", "acct-mamda-nador")

PENDING_TTL_SECONDS = 120        # how long a queued request waits for its runner to claim it
# Hard deadline after a claim, with the budget spelled out so the runner can
# do strict timeout arithmetic: 45 s for Chromium + login page startup, up to
# 300 s for the employee's login/OTP, 75 s reserved for the upload and its
# bounded retries.
STARTUP_RESERVE_SECONDS = 45
LOGIN_TIMEOUT_SECONDS = 300
UPLOAD_RESERVE_SECONDS = 75
LOGIN_WINDOW_SECONDS = STARTUP_RESERVE_SECONDS + LOGIN_TIMEOUT_SECONDS + UPLOAD_RESERVE_SECONDS   # 420
LEASE_TTL_SECONDS = 60           # runner must renew well inside this
LEASE_HOLD_SECONDS = 60          # account lease held while the session is replaced

CLAIM_TOKEN_PREFIX = "mcma_ot_"
MAX_CLAIM_TOKEN_LENGTH = 200

PHASES = frozenset({"OPENING_WINDOW", "WINDOW_OPENED", "WAITING_FOR_LOGIN"})
# runner-reported reason -> (terminal status, stored outcome code)
FAIL_REASONS = {
    "LOGIN_TIMED_OUT": ("FAILED", "LOGIN_TIMED_OUT"),
    "LOGIN_WINDOW_CLOSED": ("FAILED", "LOGIN_WINDOW_CLOSED"),
    "LOGIN_PAGE_UNREACHABLE": ("FAILED", "LOGIN_PAGE_UNREACHABLE"),
    "UPLOAD_FAILED": ("FAILED", "UPLOAD_FAILED"),
    "RUNNER_BUSY": ("FAILED", "RUNNER_BUSY"),
    "INTERNAL_ERROR": ("FAILED", "INTERNAL_ERROR"),
    "RUNNER_SHUTDOWN": ("CANCELLED", "RUNNER_SHUTDOWN"),
    "CANCELLED": ("CANCELLED", "CANCELLED_BY_USER"),
}

_ACTIVE = ("PENDING", "CLAIMED")
_CLAIM_NOT_FOUND = ("CLAIM_NOT_FOUND", "Jeton de réclamation invalide, expiré ou déjà utilisé.", 404)


def _err(code: str, message: str, status: int = 400) -> UserInputError:
    return UserInputError(code, message, status)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    # Fixed width (always microseconds) so SQL string comparison orders exactly like time.
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_claim_token() -> str:
    return CLAIM_TOKEN_PREFIX + secrets.token_urlsafe(32)


def _valid_claim_token(value: object) -> bool:
    return (
        isinstance(value, str) and value.startswith(CLAIM_TOKEN_PREFIX)
        and len(CLAIM_TOKEN_PREFIX) < len(value) <= MAX_CLAIM_TOKEN_LENGTH
    )


def _valid_generation(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _valid_request_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


def _state_of(row) -> str:
    if row["status"] == "CLAIMED":
        return row["phase"] if row["phase"] in PHASES else "QUEUED"
    return "QUEUED" if row["status"] == "PENDING" else row["status"]


def _view(account_id: str, row) -> dict:
    if row is None:
        return {"account_id": account_id, "request_id": None, "state": "IDLE", "outcome_code": None,
                "cancel_requested": False, "expires_at": None, "updated_at": None}
    return {
        "account_id": account_id, "request_id": row["request_id"], "state": _state_of(row),
        "outcome_code": row["outcome_code"],
        "cancel_requested": row["cancel_requested_at"] is not None and row["status"] in _ACTIVE,
        "expires_at": row["expires_at"], "updated_at": row["updated_at"],
    }


class NotificationOnboardingService:
    def __init__(
        self, conn, *, vault_dir: Path, instance_id: str, crypto_backend, acl_verifier, portal_host: str,
        connection_tracker=None,
    ) -> None:
        PortalPolicy(portal_host)                        # fail at construction on a malformed host, never per request
        self._portal_host = portal_host                  # from server settings ONLY -- never from a request
        self._conn = conn
        self._vault_dir = Path(vault_dir)
        self._instance_id = instance_id
        self._crypto_backend = crypto_backend          # the ONE backend loaded at startup; the key is never re-read
        self._acl_verifier = acl_verifier
        self._tracker = connection_tracker

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _user_may(self, user_id: str, account_id: str) -> bool:
        """Current, fresh: active employee, notifications permission, exact account access."""
        row = self._conn.execute("SELECT role, active FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None or not row["active"] or not role_has_permission(row["role"], Permission.NOTIFICATIONS_READ):
            return False
        return self._conn.execute(
            "SELECT 1 FROM user_account_access WHERE user_id = ? AND account_id = ?", (user_id, account_id)
        ).fetchone() is not None

    def _runner_has_job(self, runner_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM workstation_job_dispatch WHERE runner_id = ? AND status IN ('CLAIMED', 'RUNNING')",
            (runner_id,),
        ).fetchone() is not None

    def _runner_ok(self, principal: RunnerPrincipal, now: datetime):
        """The runner row only while it is ACTIVE, still the employee's, still
        eligible and online -- recomputed fresh on every call."""
        row = self._conn.execute("SELECT * FROM runners WHERE runner_id = ?", (principal.runner_id,)).fetchone()
        if (
            row is None or row["status"] != "ACTIVE" or row["user_id"] != principal.user_id
            or registry._ineligibility(self._conn, row["user_id"]) is not None
            or registry._connection_status(row, now) != "ONLINE"
        ):
            return None
        return row

    def _audit(self, action: str, actor_user_id: Optional[str], account_id: str, row, now: datetime) -> None:
        facts = f"{row['request_id']}|{row['generation']}|{action}"
        self._conn.execute(
            "INSERT INTO audit_events (audit_id, actor_user_id, account_id, job_id, action, before_hash, after_hash, "
            "created_at) VALUES (?, ?, ?, NULL, ?, NULL, ?, ?)",
            (uuid.uuid4().hex, actor_user_id, account_id, action, hashlib.sha256(facts.encode()).hexdigest(), _iso(now)),
        )

    def _finish(self, request_id: str, *, status: str, outcome: str, now: datetime, only_from=_ACTIVE) -> bool:
        marks = ",".join("?" for _ in only_from)
        cursor = self._conn.execute(
            f"UPDATE notification_onboarding_requests SET status = ?, outcome_code = ?, finished_at = ?, updated_at = ? "
            f"WHERE request_id = ? AND status IN ({marks})",
            (status, outcome, _iso(now), _iso(now), request_id, *only_from),
        )
        return cursor.rowcount == 1

    def expire_stale(self, now: datetime) -> int:
        """Server-time recovery, <= semantics, in its own transaction. An
        EXPIRED row can never match renew/complete/fail again."""
        stamp = _iso(now)
        with write_transaction(self._conn):
            lease = self._conn.execute(
                "UPDATE notification_onboarding_requests SET status = 'EXPIRED', outcome_code = 'LEASE_EXPIRED', "
                "finished_at = ?, updated_at = ? WHERE status = 'CLAIMED' AND lease_expires_at <= ?",
                (stamp, stamp, stamp),
            ).rowcount
            hard = self._conn.execute(
                "UPDATE notification_onboarding_requests SET status = 'EXPIRED', outcome_code = 'REQUEST_EXPIRED', "
                "finished_at = ?, updated_at = ? WHERE status IN ('PENDING', 'CLAIMED') AND expires_at <= ?",
                (stamp, stamp, stamp),
            ).rowcount
        return lease + hard

    def _latest(self, account_id: str):
        return self._conn.execute(
            "SELECT * FROM notification_onboarding_requests WHERE account_id = ? ORDER BY generation DESC LIMIT 1",
            (account_id,),
        ).fetchone()

    def _locate(self, principal: RunnerPrincipal, request_id: object, claim_token: object, generation: object,
                statuses: tuple):
        if not _valid_request_id(request_id) or not _valid_claim_token(claim_token):
            raise _err(*_CLAIM_NOT_FOUND)
        if not _valid_generation(generation):
            raise _err("BAD_REQUEST", "Génération invalide.")
        computed = digest_token(claim_token)
        row = self._conn.execute(
            "SELECT * FROM notification_onboarding_requests WHERE claim_token_digest = ?", (computed,)
        ).fetchone()
        if (
            row is None or not hmac.compare_digest(row["claim_token_digest"], computed)
            or row["request_id"] != request_id or row["runner_id"] != principal.runner_id
            or row["generation"] != generation or row["status"] not in statuses
        ):
            raise _err(*_CLAIM_NOT_FOUND)             # one answer for every refusal
        return row

    # ------------------------------------------------------------------ #
    # browser side (employee session already authenticated by the API layer)
    # ------------------------------------------------------------------ #

    def request_login(self, user_id: str, account_id: str, *, now: Optional[datetime] = None) -> tuple:
        """-> (view, created). Idempotent: a repeat click returns the same request."""
        now = now or utcnow()
        if account_id not in NOTIFICATION_ACCOUNT_IDS or not self._user_may(user_id, account_id):
            raise _err("ACCOUNT_NOT_ALLOWED", "Compte non autorisé.", 403)
        self.expire_stale(now)
        with write_transaction(self._conn):
            active = self._conn.execute(
                "SELECT * FROM notification_onboarding_requests WHERE account_id = ? AND status IN ('PENDING', 'CLAIMED')",
                (account_id,),
            ).fetchone()
            if active is not None:
                if active["user_id"] != user_id:
                    raise _err("ONBOARDING_IN_PROGRESS", "Une connexion est déjà en cours pour ce compte.", 409)
                return _view(account_id, active), False
            runner = registry._active_runner_row(self._conn, user_id)
            if runner is None or registry._ineligibility(self._conn, user_id) is not None:
                raise _err("RUNNER_MISSING", "Aucun poste de travail actif n'est associé à votre compte.", 409)
            if registry._connection_status(runner, now) != "ONLINE":
                raise _err("RUNNER_OFFLINE", "Votre poste de travail est hors ligne.", 409)
            busy = self._conn.execute(
                "SELECT 1 FROM notification_onboarding_requests WHERE runner_id = ? AND status IN ('PENDING', 'CLAIMED')",
                (runner["runner_id"],),
            ).fetchone()
            if busy is not None or self._runner_has_job(runner["runner_id"]):
                raise _err("RUNNER_BUSY", "Votre poste de travail est occupé.", 409)
            generation = self._conn.execute(
                "SELECT COALESCE(MAX(generation), 0) + 1 FROM notification_onboarding_requests WHERE account_id = ?",
                (account_id,),
            ).fetchone()[0]
            request_id = uuid.uuid4().hex
            self._conn.execute(
                "INSERT INTO notification_onboarding_requests (request_id, account_id, user_id, runner_id, generation, "
                "status, created_at, expires_at, updated_at) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)",
                (request_id, account_id, user_id, runner["runner_id"], generation, _iso(now),
                 _iso(now + timedelta(seconds=PENDING_TTL_SECONDS)), _iso(now)),
            )
            row = self._conn.execute(
                "SELECT * FROM notification_onboarding_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            self._audit("notification_onboarding.requested", user_id, account_id, row, now)
            return _view(account_id, row), True

    def status(self, user_id: str, account_id: str, *, now: Optional[datetime] = None) -> dict:
        now = now or utcnow()
        if account_id not in NOTIFICATION_ACCOUNT_IDS:
            raise _err("ACCOUNT_NOT_ALLOWED", "Compte non autorisé.", 403)
        self.expire_stale(now)
        return _view(account_id, self._latest(account_id))

    def cancel(self, user_id: str, account_id: str, *, now: Optional[datetime] = None) -> dict:
        """Idempotent. PENDING is cancelled at once; CLAIMED only gets a flag the
        runner sees on its next renew (the runner closes its own window)."""
        now = now or utcnow()
        if account_id not in NOTIFICATION_ACCOUNT_IDS:
            raise _err("ACCOUNT_NOT_ALLOWED", "Compte non autorisé.", 403)
        self.expire_stale(now)
        with write_transaction(self._conn):
            row = self._latest(account_id)
            if row is not None and row["status"] in _ACTIVE and row["user_id"] == user_id:
                if row["status"] == "PENDING":
                    self._finish(row["request_id"], status="CANCELLED", outcome="CANCELLED_BY_USER", now=now,
                                 only_from=("PENDING",))
                else:
                    self._conn.execute(
                        "UPDATE notification_onboarding_requests SET cancel_requested_at = COALESCE(cancel_requested_at, ?), "
                        "updated_at = ? WHERE request_id = ? AND status = 'CLAIMED'", (_iso(now), _iso(now), row["request_id"]),
                    )
                row = self._latest(account_id)
            return _view(account_id, row)

    # ------------------------------------------------------------------ #
    # machine side (runner bearer already authenticated by the API layer)
    # ------------------------------------------------------------------ #

    def claim(self, principal: RunnerPrincipal, *, protocol_version: object, app_version: object,
              now: Optional[datetime] = None) -> Optional[dict]:
        now = now or utcnow()
        registry._validated_versions(protocol_version, app_version)
        self.expire_stale(now)
        envelope = None
        with write_transaction(self._conn):
            runner = self._runner_ok(principal, now)
            if runner is None or self._runner_has_job(principal.runner_id):
                return None
            row = self._conn.execute(
                "SELECT * FROM notification_onboarding_requests WHERE runner_id = ? AND status = 'PENDING' "
                "AND expires_at > ? ORDER BY created_at LIMIT 1", (principal.runner_id, _iso(now)),
            ).fetchone()
            if row is None:
                return None
            if row["user_id"] != runner["user_id"] or not self._user_may(row["user_id"], row["account_id"]):
                self._finish(row["request_id"], status="FAILED", outcome="ACCESS_REVOKED", now=now, only_from=("PENDING",))
                return None
            token = new_claim_token()
            hard = now + timedelta(seconds=LOGIN_WINDOW_SECONDS)
            lease = min(now + timedelta(seconds=LEASE_TTL_SECONDS), hard)
            claimed = self._conn.execute(
                "UPDATE notification_onboarding_requests SET status = 'CLAIMED', claim_token_digest = ?, claimed_at = ?, "
                "lease_expires_at = ?, expires_at = ?, updated_at = ? WHERE request_id = ? AND status = 'PENDING'",
                (digest_token(token), _iso(now), _iso(lease), _iso(hard), _iso(now), row["request_id"]),
            ).rowcount
            if claimed != 1:
                return None
            envelope = {
                "request_id": row["request_id"], "account_id": row["account_id"], "generation": row["generation"],
                "claim_token": token, "lease_expires_at": _iso(lease), "expires_at": _iso(hard), "server_time": _iso(now),
            }
        return envelope

    def renew(self, principal: RunnerPrincipal, *, request_id: object, claim_token: object, generation: object,
              phase: object, now: Optional[datetime] = None) -> dict:
        now = now or utcnow()
        if not isinstance(phase, str) or phase not in PHASES:
            raise _err("BAD_REQUEST", "Phase invalide.")
        self.expire_stale(now)
        refusal = None
        with write_transaction(self._conn):
            row = self._locate(principal, request_id, claim_token, generation, ("CLAIMED",))
            if self._runner_ok(principal, now) is None:
                raise _err(*_CLAIM_NOT_FOUND)
            if not self._user_may(row["user_id"], row["account_id"]):
                self._finish(row["request_id"], status="FAILED", outcome="ACCESS_REVOKED", now=now, only_from=("CLAIMED",))
                refusal = True
            else:
                lease = min(now + timedelta(seconds=LEASE_TTL_SECONDS), datetime.fromisoformat(row["expires_at"]))
                self._conn.execute(
                    "UPDATE notification_onboarding_requests SET lease_expires_at = ?, last_renewed_at = ?, phase = ?, "
                    "updated_at = ? WHERE request_id = ? AND status = 'CLAIMED'",
                    (_iso(lease), _iso(now), phase, _iso(now), row["request_id"]),
                )
                cancel_requested = row["cancel_requested_at"] is not None
        if refusal:
            raise _err(*_CLAIM_NOT_FOUND)
        return {"lease_expires_at": _iso(lease), "server_time": _iso(now), "cancel_requested": cancel_requested}

    def fail(self, principal: RunnerPrincipal, *, request_id: object, claim_token: object, generation: object,
             reason_code: object, now: Optional[datetime] = None) -> dict:
        now = now or utcnow()
        if not isinstance(reason_code, str) or reason_code not in FAIL_REASONS:
            raise _err("BAD_REQUEST", "Motif invalide.")
        status, outcome = FAIL_REASONS[reason_code]
        self.expire_stale(now)
        with write_transaction(self._conn):
            row = self._locate(principal, request_id, claim_token, generation, ("CLAIMED", status))
            if row["status"] == "CLAIMED":
                self._finish(row["request_id"], status=status, outcome=outcome, now=now, only_from=("CLAIMED",))
            elif row["outcome_code"] != outcome:
                raise _err(*_CLAIM_NOT_FOUND)         # a DIFFERENT terminal outcome is never overwritten
        return {"status": status, "server_time": _iso(now)}

    def complete(self, principal: RunnerPrincipal, **kwargs) -> dict:
        """See _complete. The tracker is reconciled HERE, after every durable
        write and cleanup has finished -- on a fresh success and also on an
        idempotent retry (a restart or a post-commit cleanup failure can leave
        the session committed with the in-memory tracker never told). It
        touches no vault file, portal_sessions row or audit event."""
        response, account_id = self._complete(principal, **kwargs)
        if self._tracker is not None:
            self._tracker.mark_authenticated(account_id)
        return response

    def _release_quietly(self, lease) -> None:
        """A failing lease release never replaces an authoritative outcome; the
        unreleased lease simply expires on its own TTL."""
        try:
            lease.release()
        except Exception:
            logger.warning("account lease release failed; it will expire on its own")   # fixed text only

    def _complete(self, principal: RunnerPrincipal, *, request_id: object, claim_token: object, generation: object,
                  storage_state: object, now: Optional[datetime] = None) -> tuple:
        """Atomic staged activation. The new session is encrypted to a file no
        row references, the account lease is taken, and then ONE SQLite write
        transaction re-checks everything and switches portal_sessions AND marks
        the request SUCCEEDED together. Any failure rolls both back, the staged
        file is discarded and the previous active session is untouched. The
        transaction holds no network or browser I/O."""
        clock = now is None
        now = now or utcnow()
        self.expire_stale(now)
        refusal: Optional[tuple] = None
        with write_transaction(self._conn):
            row = self._locate(principal, request_id, claim_token, generation, ("CLAIMED", "SUCCEEDED"))
            if row["status"] == "SUCCEEDED":
                # lost-response retry: nothing is stored twice
                return {"status": "SUCCEEDED", "server_time": _iso(now)}, row["account_id"]
            account_id = row["account_id"]
            if self._runner_ok(principal, now) is None:
                raise _err(*_CLAIM_NOT_FOUND)
            if not self._user_may(row["user_id"], account_id):
                self._finish(row["request_id"], status="FAILED", outcome="ACCESS_REVOKED", now=now, only_from=("CLAIMED",))
                refusal = _CLAIM_NOT_FOUND
            elif row["cancel_requested_at"] is not None:
                self._finish(row["request_id"], status="CANCELLED", outcome="CANCELLED_BY_USER", now=now,
                             only_from=("CLAIMED",))
                refusal = _CLAIM_NOT_FOUND
            else:
                try:
                    state = validate_storage_state(storage_state, portal_host=self._portal_host)
                except StorageStateRejected:
                    self._finish(row["request_id"], status="FAILED", outcome="UPLOAD_FAILED", now=now,
                                 only_from=("CLAIMED",))
                    refusal = ("SESSION_REJECTED", "Session refusée : format invalide.", 422)
        if refusal is not None:
            raise _err(*refusal)

        try:
            staged = stage_session(
                account_id, json.dumps(state).encode("utf-8"), vault_dir=self._vault_dir,
                backend=self._crypto_backend, acl_verifier=self._acl_verifier,
            )
        except Exception:
            logger.warning("notification session staging failed for %s", account_id)   # never the payload or exception text
            raise _err("STORAGE_UNAVAILABLE", "Stockage de la session indisponible.", 503) from None
        try:
            lease = acquire_lease(self._conn, account_id, self._instance_id, ttl_seconds=LEASE_HOLD_SECONDS)
        except LeaseNotHeld:
            discard_staged_session(staged)
            raise _err("ACCOUNT_BUSY", "Compte occupé, réessayez dans un instant.", 409) from None
        except Exception:
            discard_staged_session(staged)
            raise _err("STORAGE_UNAVAILABLE", "Stockage de la session indisponible.", 503) from None

        committed = None
        try:
            try:
                committed = self._admit(principal, row, claim_token, generation, staged, lease,
                                        utcnow() if clock else now)
            except Exception:
                logger.warning("notification session activation failed for %s", account_id)
                raise _err("STORAGE_UNAVAILABLE", "Stockage de la session indisponible.", 503) from None
        finally:
            # Order matters: file cleanup FIRST (it can never be skipped), then
            # the lease release, which is itself exception-safe.
            if committed is None or committed[0] is not None:
                discard_staged_session(staged)           # nothing was activated: the staged file never becomes visible
            self._release_quietly(lease)
        done, final_now, previous_ref = committed
        if done is not None:
            raise _err(*done)
        cleanup_replaced_session(self._vault_dir, previous_ref)
        # The tracker is marked by complete(), only AFTER the durable commit.
        return {"status": "SUCCEEDED", "server_time": _iso(final_now)}, account_id

    def _lease_still_owned(self, lease, now: datetime) -> bool:
        owned = self._conn.execute(
            "SELECT fencing_token, expires_at FROM account_leases WHERE account_id = ?", (lease.account_id,)
        ).fetchone()
        return (
            owned is not None and owned["fencing_token"] == lease._fencing_token
            and datetime.fromisoformat(owned["expires_at"]) > now
        )

    def _admit(self, principal, row, claim_token, generation, staged, lease, now: datetime) -> tuple:
        """The ONE write transaction. Returns (refusal-or-None, now, previous
        storage_ref). A refusal commits only request-state changes made BEFORE
        any portal_sessions mutation; an exception rolls back everything."""
        account_id = row["account_id"]
        previous_ref = None
        with write_transaction(self._conn):
            digest = digest_token(claim_token)
            current = self._conn.execute(
                "SELECT * FROM notification_onboarding_requests WHERE request_id = ? AND claim_token_digest = ? "
                "AND generation = ? AND runner_id = ?",
                (row["request_id"], digest, generation, principal.runner_id),
            ).fetchone()
            stamp = _iso(now)
            if current is None or current["status"] != "CLAIMED":
                return _CLAIM_NOT_FOUND, now, None
            if current["lease_expires_at"] <= stamp or current["expires_at"] <= stamp:
                self._finish(current["request_id"], status="EXPIRED", outcome=(
                    "LEASE_EXPIRED" if current["lease_expires_at"] <= stamp else "REQUEST_EXPIRED"), now=now,
                    only_from=("CLAIMED",))
                return _CLAIM_NOT_FOUND, now, None
            if self._runner_ok(principal, now) is None:
                return _CLAIM_NOT_FOUND, now, None
            if not self._user_may(current["user_id"], account_id):
                self._finish(current["request_id"], status="FAILED", outcome="ACCESS_REVOKED", now=now,
                             only_from=("CLAIMED",))
                return _CLAIM_NOT_FOUND, now, None
            if current["cancel_requested_at"] is not None:
                self._finish(current["request_id"], status="CANCELLED", outcome="CANCELLED_BY_USER", now=now,
                             only_from=("CLAIMED",))
                return _CLAIM_NOT_FOUND, now, None
            if not self._lease_still_owned(lease, now):
                return ("ACCOUNT_BUSY", "Compte occupé, réessayez dans un instant.", 409), now, None
            _session_id, previous_ref = activate_staged_session(self._conn, staged, account_id)
            _mark_succeeded(self._conn, current["request_id"], digest, generation, now)
            self._audit("notification_onboarding.succeeded", current["user_id"], account_id, current, now)
        return None, now, previous_ref


def _mark_succeeded(conn, request_id: str, digest: str, generation: int, now: datetime) -> None:
    """The onboarding half of the atomic switch. Module-level so the failure
    injection tests can break it AFTER the portal_sessions mutation."""
    done = conn.execute(
        "UPDATE notification_onboarding_requests SET status = 'SUCCEEDED', outcome_code = 'SESSION_STORED', "
        "finished_at = ?, updated_at = ?, phase = NULL WHERE request_id = ? AND status = 'CLAIMED' "
        "AND claim_token_digest = ? AND generation = ?",
        (_iso(now), _iso(now), request_id, digest, generation),
    ).rowcount
    if done != 1:
        raise RuntimeError("request no longer claimable")
