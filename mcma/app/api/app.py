"""
mcma.app.api.app -- the authenticated API application factory (INC-17).
Routes are grouped by surface (auth, notifications, jobs, events,
health) in this one module for this increment's scope; each surface
enforces authz.require_permission/require_account_access and derives its
actor exclusively from deps.get_principal_dependency.

`mode` is NEVER a client field anywhere here (test_no_mode_field_exists):
POST /jobs/dry-runs always creates mode='DRY_RUN'; POST /jobs/{id}/
executions always creates mode='EXECUTE'. There is no third endpoint and
no body field that could select a mode.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from typing import Optional

from fastapi import Depends, FastAPI, Request

from mcma.app.browser_supervisor import BrowserNotReady, BrowserUnavailable
from mcma.app.api.authz import (
    Principal,
    filter_rows_by_account_access,
    require_account_access,
    require_permission,
    visible_account_ids,
)
from mcma.app.api.deps import get_principal_dependency, require_csrf
from mcma.app.api.errors import ApiError, install_error_handlers
from mcma.app.connection_state import resolve_connection_state
from mcma.app.auth.csrf import CSRF_COOKIE_NAME, generate_csrf_token
from mcma.app.auth.provider import AuthProvider
from mcma.app.auth.sessions import SESSION_COOKIE_NAME, SessionStore, clear_session_cookie, set_session_cookie
from mcma.app.sse import Authorizer, create_sse_endpoint
from mcma.domain.enums import Permission
from mcma.domain.portal_accounts import PortalAccountProfile
from mcma.execution.inputs import InputEncryptor, JobInputUnavailable, compute_content_hash, retrieve_and_verify_job_input
from mcma.execution.jobs import (
    JobAuthorizationError,
    confirm_review_completed,
    enqueue_dry_run,
    enqueue_execute,
    report_review_problem,
    run_execute_planning,
)
from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import PlanBuildError, detect_workflow
from mcma.planning.registry import default_registry, workflow_name_for
from mcma.persistence.repositories.audit import EmployeeActionsRepository
from mcma.persistence.repositories.accounts import AccountsRepository
from mcma.persistence.repositories.claims import CategoryPresenceRepository
from mcma.persistence.repositories.jobs import AutomationJobsRepository

# Fable-review-2 correction (HIGH finding), extended by the pilot-
# integration correction (section 3): the EXECUTE endpoint's
# rebuild_plan_from_retained_input callable used to be an always-matching
# stub, making run_execute_planning's hash re-check vacuous. It now
# re-derives the plan from the SAME typed input bytes retained at
# DRY_RUN time, through the SAME pure builder function the workflow_name
# names (mcma.planning.registry.default_registry(), the one canonical
# name<->builder mapping) -- a genuine re-verification. An unrecognized
# workflow_name fails closed (never guesses a builder). workflow_name
# itself is NEVER a client-supplied field (section 3): POST /jobs/
# dry-runs determines it server-side via detect_workflow() from the
# parsed typed_input, never from the browser.
_WORKFLOW_REGISTRY = default_registry()


logger = logging.getLogger(__name__)


def _log_refresh_failure(exc: BaseException) -> None:
    """Names WHERE a manual refresh failed, without quoting anything the
    portal said.

    The response reports the exception TYPE and nothing else, which is
    right -- a portal error page can carry a claimant's name -- but the
    server log was left empty too, so an onsite "502
    REFRESH_FAILED_ValueError" pointed at no line of code and could not
    be diagnosed. Logged here: the chain of exception TYPES and the code
    locations they were raised from. Exception MESSAGES, URLs, page text
    and session material are never logged; a frame is a filename, a line
    number and a function name in this repository."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    # __cause__ first: `raise X from Y` is the deliberate link, and the
    # root cause is the frame an operator actually needs.
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    for depth, item in enumerate(chain):
        frames = " <- ".join(
            f"{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}"
            for frame in traceback.extract_tb(item.__traceback__)[-10:]
        )
        logger.warning(
            "notification refresh failed [%d]: %s raised at %s",
            depth, type(item).__name__, frames or "-",
        )


def _require_mcma_account(conn, account_id: str) -> None:
    """MAMDA read-only enforcement, defense-in-depth layer 1 (correction
    batch / owner amendment): rejected here, before enqueueing anything --
    mcma.execution.jobs independently re-checks this itself (layer 2) and
    never trusts that this endpoint-level check alone was performed."""
    account = AccountsRepository(conn).get(account_id)
    if account is None:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "no such account")
    profile = PortalAccountProfile.from_row(account.entity, account.scope)
    if not profile.is_mcma:
        raise ApiError(403, "MAMDA_ACCOUNT_NOT_WRITABLE", "this account is notification-only")


class RealAuthorizer:
    """The concrete Authorizer for SSE (correction #9) -- backed by the
    SAME user_account_access table every other surface enforces against.
    Revoking a row here is what test_sse_revocation_drops_stream_with_
    real_auth (INC-17) actually proves."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def visible_accounts(self, principal: Principal) -> set:
        return set(visible_account_ids(self._conn, principal))

    def is_authorized(self, principal: Principal, account_id: str) -> bool:
        return account_id in self.visible_accounts(principal)


def create_api_app(
    conn,
    *,
    auth_provider: AuthProvider,
    session_store: Optional[SessionStore] = None,
    encryptor: InputEncryptor,
    secure_cookies: bool = True,
    portal_login_opener=None,
    local_user_id: str | None = None,
    notification_refresher=None,
    connection_state_tracker=None,
) -> FastAPI:
    app = FastAPI(title="MCMA API")
    install_error_handlers(app)
    session_store = session_store or SessionStore()
    get_principal = get_principal_dependency(conn, session_store, local_user_id)

    if local_user_id is not None:
        # State-changing requests still require the CSRF double-submit.
        # With no login step there is nothing to issue that cookie, so it
        # is issued here -- the check itself is unchanged, and a request
        # without the matching header is still refused.
        @app.middleware("http")
        async def _issue_csrf_cookie(request: Request, call_next):
            response = await call_next(request)
            if not request.cookies.get(CSRF_COOKIE_NAME):
                response.set_cookie(
                    CSRF_COOKIE_NAME, generate_csrf_token(),
                    httponly=False, samesite="strict", secure=secure_cookies,
                )
            return response
    authorizer: Authorizer = RealAuthorizer(conn)

    # -- auth -------------------------------------------------------------

    @app.post("/auth/login")
    async def login(request: Request):
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        if not username or not password:
            raise ApiError(400, "BAD_REQUEST", "username and password are required")
        user = auth_provider.authenticate(username, password)
        if user is None:
            raise ApiError(401, "INVALID_CREDENTIALS", "invalid username or password")
        token = session_store.create(user.user_id)
        csrf_token = generate_csrf_token()
        from fastapi.responses import JSONResponse

        response = JSONResponse(
            {"user_id": user.user_id, "username": user.username, "role": user.role, "csrf_token": csrf_token}
        )
        set_session_cookie(response, token, secure=secure_cookies)
        # The CSRF cookie is deliberately NOT HttpOnly -- the client-side
        # code must be able to read it to echo it back in the header
        # (double-submit-cookie pattern); it carries no session authority
        # by itself.
        response.set_cookie(CSRF_COOKIE_NAME, csrf_token, httponly=False, samesite="strict", secure=secure_cookies)
        return response

    @app.post("/auth/logout")
    def logout(request: Request, principal: Principal = Depends(get_principal)):
        from fastapi.responses import JSONResponse

        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token:
            session_store.invalidate(token)
        response = JSONResponse({"status": "logged_out"})
        clear_session_cookie(response)
        return response

    # -- notifications (row-filtered list surfaces, review AR-H1) --------

    _NOTIFICATIONS_WITH_PROFILE_SELECT = (
        "SELECT n.*, a.entity AS account_entity, a.scope AS account_scope, a.label AS account_label "
        "FROM unmatched_notifications n JOIN accounts a ON a.account_id = n.account_id"
    )

    def _list_notifications(principal: Principal, account_id: Optional[str]):
        require_permission(principal, Permission.NOTIFICATIONS_READ)
        if account_id is not None:
            require_account_access(conn, principal, account_id)
            rows = conn.execute(f"{_NOTIFICATIONS_WITH_PROFILE_SELECT} WHERE n.account_id = ?", (account_id,)).fetchall()
        else:
            visible = visible_account_ids(conn, principal)
            if not visible:
                rows = []
            else:
                placeholders = ",".join("?" for _ in visible)
                rows = conn.execute(
                    f"{_NOTIFICATIONS_WITH_PROFILE_SELECT} WHERE n.account_id IN ({placeholders})", tuple(visible)
                ).fetchall()
        # Row-filtered even for a caller with a global permission and no
        # explicit account_id -- never another account's rows. entity/
        # scope/label (section I, correction batch) let the dashboard
        # always render an account-labelled notification view, even in
        # the combined (no explicit account_id) listing.
        filtered = filter_rows_by_account_access(conn, principal, rows)
        return {"notifications": [dict(r) for r in filtered]}

    def _notification_summary_by_account(account_ids):
        """Notification volume and poll freshness for SEVERAL accounts, in
        three GROUPED queries -- never one per account.

        Counts are derived from the same category_presence rows the work
        queue reads, so the rail, the overview and the queue can never
        disagree. present=1 only: a membership that resolved on the portal
        is no longer a notification, whatever its unread flag still says.

        Nothing claimant-facing is returned -- counts and poll timestamps
        only. The caller passes exactly the accounts the principal may see,
        so an account outside that set has no row here to expose.
        """
        if not account_ids:
            return {}
        placeholders = ",".join("?" for _ in account_ids)
        params = tuple(account_ids)
        summaries = {
            account_id: {
                "active_notification_count": 0,
                "unread_notification_count": 0,
                "unread_claim_count": 0,
                "notification_last_attempt_at": None,
                "notification_last_attempt_status": None,
                "notification_last_success_at": None,
            }
            for account_id in account_ids
        }

        # One dossier in two categories is two notifications and ONE
        # dossier: the employee needs both numbers, so both are counted
        # here rather than divided out in the browser.
        for row in conn.execute(
            "SELECT account_id, COUNT(*) AS active_count, "
            "SUM(CASE WHEN unread = 1 THEN 1 ELSE 0 END) AS unread_count, "
            "COUNT(DISTINCT CASE WHEN unread = 1 THEN claim_pk END) AS unread_claims "
            f"FROM category_presence WHERE present = 1 AND account_id IN ({placeholders}) "
            "GROUP BY account_id",
            params,
        ).fetchall():
            summary = summaries[row["account_id"]]
            summary["active_notification_count"] = row["active_count"] or 0
            summary["unread_notification_count"] = row["unread_count"] or 0
            summary["unread_claim_count"] = row["unread_claims"] or 0

        # The latest attempt, whatever its outcome. rowid is this single
        # writer's insertion order, so MAX(rowid) is the poll that ran last
        # -- including one that FAILED, which is exactly what the employee
        # must be told about.
        for row in conn.execute(
            "SELECT account_id, completed_at, status FROM poll_runs WHERE rowid IN "
            f"(SELECT MAX(rowid) FROM poll_runs WHERE account_id IN ({placeholders}) GROUP BY account_id)",
            params,
        ).fetchall():
            summary = summaries[row["account_id"]]
            summary["notification_last_attempt_at"] = row["completed_at"]
            summary["notification_last_attempt_status"] = row["status"]

        # The latest poll that actually read everything on a valid session.
        # This is the only timestamp "les donnees datent de" may rest on: a
        # later FAILED attempt must never overwrite it, or stale rows would
        # be presented as current.
        for row in conn.execute(
            "SELECT account_id, MAX(completed_at) AS last_success FROM poll_runs "
            f"WHERE status = 'COMPLETE' AND session_valid = 1 AND account_id IN ({placeholders}) "
            "GROUP BY account_id",
            params,
        ).fetchall():
            summaries[row["account_id"]]["notification_last_success_at"] = row["last_success"]

        return summaries

    @app.get("/accounts")
    def list_accounts(principal: Principal = Depends(get_principal)):
        """Pilot-integration correction (section 2/6): the dashboard must
        never hardcode a production account_id in its HTML -- it loads
        the authenticated user's own accessible profiles from here."""
        visible = visible_account_ids(conn, principal)
        if not visible:
            rows = []
        else:
            placeholders = ",".join("?" for _ in visible)
            rows = conn.execute(
                f"SELECT account_id, label, entity, scope FROM accounts WHERE account_id IN ({placeholders})",
                tuple(visible),
            ).fetchall()
        summaries = _notification_summary_by_account(tuple(visible))
        # session_active tells the dashboard which accounts have captured
        # portal session MATERIAL. It is not the same claim as "this
        # session works": nothing ages an ACTIVE row out, so reporting
        # CONNECTED from this alone left an account signed in yesterday
        # still offering "Actualiser" this morning.
        active_sessions = {
            row["account_id"]
            for row in conn.execute("SELECT account_id FROM portal_sessions WHERE status = 'ACTIVE'")
        }
        # An account that HAS session rows but none active was connected
        # and is not any more -- it needs reconnecting, which is a
        # different thing to tell an employee than "never connected".
        # Derived from the existing session model rather than adding a
        # second definition of "connected".
        ever_connected = {
            row["account_id"] for row in conn.execute("SELECT DISTINCT account_id FROM portal_sessions")
        }
        accounts = []
        for row in rows:
            account = dict(row)
            account_id = account["account_id"]
            account["session_active"] = account_id in active_sessions
            # Stored material plus what THIS PROCESS has observed. Without
            # live evidence, ACTIVE material is UNVERIFIED -- never
            # CONNECTED, which is the claim that was untrue every morning.
            account["connection_state"] = resolve_connection_state(
                has_active_session=account_id in active_sessions,
                has_session_history=account_id in ever_connected,
                verified_live=(
                    connection_state_tracker is not None
                    and connection_state_tracker.is_verified(account_id)
                ),
            )
            # A MAMDA account is readable but can never be the target of a
            # form job. Stating it here means the dashboard never has to
            # re-derive the rule from the entity string.
            account["writable"] = account.get("entity") == "MCMA"
            # Additive: every existing field keeps its meaning. The summary
            # is what lets the rail and the overview show where the work is
            # without fetching each account's claims.
            account.update(summaries[account_id])
            accounts.append(account)
        return {"accounts": accounts}

    @app.get("/notifications")
    def list_notifications(account_id: Optional[str] = None, principal: Principal = Depends(get_principal)):
        return _list_notifications(principal, account_id)

    @app.get("/cached-notifications")
    def list_cached_notifications(account_id: Optional[str] = None, principal: Principal = Depends(get_principal)):
        return _list_notifications(principal, account_id)

    # -- portal login ------------------------------------------------------
    # Registered by the composition root (mcma.app.main), which owns the
    # browser and the vault; this module never touches either. When no
    # opener is supplied -- every existing test app, and any deployment
    # without a browser -- the route simply does not exist, rather than
    # existing and failing.

    if portal_login_opener is not None:

        @app.post("/accounts/{account_id}/login")
        async def start_portal_login(
            account_id: str, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf)
        ):
            require_permission(principal, Permission.NOTIFICATIONS_READ)
            require_account_access(conn, principal, account_id)
            try:
                session_id = await portal_login_opener(account_id)
            except BrowserNotReady as exc:
                # Transient and NOT the employee's doing: telling them the
                # sign-in failed when no window ever opened is simply
                # untrue.
                raise ApiError(
                    503, "BROWSER_NOT_READY",
                    "le navigateur demarre encore -- reessayez dans quelques secondes",
                ) from exc
            except BrowserUnavailable as exc:
                raise ApiError(
                    503, "BROWSER_UNAVAILABLE",
                    "le navigateur partage n'a pas pu demarrer -- redemarrez l'application",
                ) from exc
            except Exception as exc:
                # The exception TYPE is reported and its message is not:
                # a portal failure page can contain the username that was
                # typed, but "LoginTimedOut" versus "UnreviewedHost"
                # versus "TargetClosedError" is exactly what tells an
                # operator whether they were too slow, pointed at the
                # wrong host, or closed the window -- and a bare 409 with
                # no code makes a failure here undiagnosable.
                reason = getattr(exc, "reason", None) or type(exc).__name__
                # LOGIN_WINDOW_CLOSED and LOGIN_TIMED_OUT are outcomes of
                # a login the employee saw, so they are reported as
                # themselves rather than folded into one code.
                raise ApiError(
                    409, reason if reason.startswith("LOGIN_") else f"PORTAL_LOGIN_FAILED_{reason}",
                    "the portal login did not complete -- finish signing in "
                    "in the browser window that opened, then try again",
                ) from exc
            return {"account_id": account_id, "session_id": session_id}

    # -- manual notification refresh ---------------------------------------
    # Registered by the composition root, like the login route, because it
    # needs the browser the API layer does not have. It calls the SAME
    # poll_one_account() the background loop calls -- there is no second
    # scraper, so the two can never drift apart.

    if notification_refresher is not None:

        _REFRESH_MESSAGES = {
            "POLLED": "Notifications actualisées.",
            # Reaching the poll is not reading anything: saying
            # "actualisées" after a run that read nothing is the kind of
            # false reassurance that hides an outage for a day.
            "POLL_INCOMPLETE": "Actualisation partielle — certaines catégories n'ont pas pu être lues.",
            "POLL_FAILED": "Aucune catégorie n'a pu être lue — réessayez ou reconnectez ce compte.",
            "NO_SESSION": "Compte non connecté — cliquez sur Se connecter.",
            "RECONNECT_REQUIRED": "Session expirée — reconnectez ce compte.",
            "LEASE_BUSY": "Compte occupé par un dossier en cours — réessayez dans un instant.",
            "NO_CATEGORIES": "Aucune catégorie d'alerte pour ce compte.",
            "PORTAL_UNAVAILABLE": "Portail temporairement indisponible — réessayez.",
        }

        @app.post("/accounts/{account_id}/refresh-notifications")
        async def refresh_notifications(
            account_id: str, principal: Principal = Depends(get_principal),
            _csrf=Depends(require_csrf),
        ):
            require_permission(principal, Permission.NOTIFICATIONS_READ)
            require_account_access(conn, principal, account_id)
            try:
                outcome = await notification_refresher(account_id)
            except Exception as exc:
                # No portal text: an error page can carry claimant data.
                # The response still says only the TYPE; the server log
                # gets the code locations, because a 502 whose only
                # evidence was "ValueError" was undiagnosable onsite.
                _log_refresh_failure(exc)
                raise ApiError(
                    502, f"REFRESH_FAILED_{type(exc).__name__}",
                    "l'actualisation a échoué",
                ) from exc
            return {
                "account_id": account_id,
                "outcome": outcome,
                "message": _REFRESH_MESSAGES.get(outcome, "Actualisation terminée."),
            }

    # -- claims: the employee's working list -------------------------------
    # An employee opens one account (MCMA Oujda, MAMDA Nador, ...) and works
    # through its claims one at a time, recording where each one stands and
    # why. SinAuto itself offers nowhere to keep that, which is the problem
    # this list exists to solve.
    #
    # employee_actions is append-only and versioned: correcting a note adds a
    # row, never rewrites one, so "who said what, when" survives. The current
    # state of a claim is simply its highest-version row.

    CLAIM_STATUSES = frozenset({"NEW", "IN_PROGRESS", "WAITING", "DONE", "NOT_APPLICABLE"})

    _CLAIMS_SELECT = (
        "SELECT c.claim_pk, c.account_id, c.portal_claim_id, c.reference, c.insured, "
        "c.police, c.matricule_norm, c.last_seen_version, "
        "a.entity AS account_entity, a.scope AS account_scope, a.label AS account_label "
        "FROM claims c JOIN accounts a ON a.account_id = c.account_id"
    )

    def _latest_actions_by_claim(claim_pks):
        """One query for the whole page rather than one per claim."""
        if not claim_pks:
            return {}
        placeholders = ",".join("?" for _ in claim_pks)
        rows = conn.execute(
            "SELECT e.claim_pk, e.status, e.note, e.actor_user_id, e.updated_at, e.version "
            f"FROM employee_actions e WHERE e.claim_pk IN ({placeholders}) ORDER BY e.version",
            tuple(claim_pks),
        ).fetchall()
        latest = {}
        for row in rows:
            latest[row["claim_pk"]] = dict(row)   # ordered by version, so last wins
        return latest

    def _active_notifications_by_claim(claim_pks):
        """Which alert categories each claim is currently present in -- the
        portal's own reason for surfacing it -- and whether each of those
        memberships is still unread (migration 0004). One row per active
        membership, so the same dossier in two categories is two
        notifications, each with its own freshness."""
        if not claim_pks:
            return {}
        placeholders = ",".join("?" for _ in claim_pks)
        rows = conn.execute(
            "SELECT p.claim_pk, p.category_code, p.unread, p.appeared_at, p.seen_at, c.label "
            "FROM category_presence p "
            "LEFT JOIN categories c ON c.code_alerte = p.category_code "
            f"WHERE p.claim_pk IN ({placeholders}) AND p.present = 1",
            tuple(claim_pks),
        ).fetchall()
        by_claim = {}
        for row in rows:
            by_claim.setdefault(row["claim_pk"], []).append(
                {
                    # The label is what the employee reads and what
                    # `categories` already carries; the category code is
                    # a portal key and stays server-side.
                    "category": row["label"] or row["category_code"],
                    "unread": bool(row["unread"]),
                    "appeared_at": row["appeared_at"],
                    "seen_at": row["seen_at"],
                }
            )
        return by_claim

    @app.get("/claims")
    def list_claims(account_id: Optional[str] = None, principal: Principal = Depends(get_principal)):
        require_permission(principal, Permission.NOTIFICATIONS_READ)
        if account_id is not None:
            require_account_access(conn, principal, account_id)
            rows = conn.execute(f"{_CLAIMS_SELECT} WHERE c.account_id = ?", (account_id,)).fetchall()
        else:
            visible = visible_account_ids(conn, principal)
            if not visible:
                rows = []
            else:
                placeholders = ",".join("?" for _ in visible)
                rows = conn.execute(
                    f"{_CLAIMS_SELECT} WHERE c.account_id IN ({placeholders})", tuple(visible)
                ).fetchall()
        # Row-filtered even for a caller holding a global permission and
        # passing no account_id -- never another account's claims.
        filtered = filter_rows_by_account_access(conn, principal, rows)
        claim_pks = [r["claim_pk"] for r in filtered]
        actions = _latest_actions_by_claim(claim_pks)
        notifications = _active_notifications_by_claim(claim_pks)

        claims = []
        for row in filtered:
            claim = dict(row)
            action = actions.get(claim["claim_pk"])
            claim["status"] = action["status"] if action else "NEW"
            claim["note"] = action["note"] if action else None
            claim["updated_at"] = action["updated_at"] if action else None
            active = notifications.get(claim["claim_pk"], [])
            # `categories` is kept exactly as before for compatibility;
            # `notifications` is the additive, structured form of the same
            # memberships, carrying freshness.
            claim["categories"] = [entry["category"] for entry in active]
            claim["notifications"] = active
            claims.append(claim)
        return {"claims": claims}

    @app.post("/claims/{claim_pk}/action")
    async def set_claim_action(
        claim_pk: str, request: Request, principal: Principal = Depends(get_principal),
        _csrf=Depends(require_csrf),
    ):
        require_permission(principal, Permission.NOTIFICATIONS_UPDATE)
        row = conn.execute("SELECT account_id FROM claims WHERE claim_pk = ?", (claim_pk,)).fetchone()
        if row is None:
            raise ApiError(404, "CLAIM_NOT_FOUND", "no such claim")
        # The claim's OWN account decides access -- never a client-supplied one.
        require_account_access(conn, principal, row["account_id"])

        body = await request.json() if await request.body() else {}
        status = body.get("status")
        note = body.get("note")
        if status not in CLAIM_STATUSES:
            raise ApiError(400, "BAD_REQUEST", "status must be one of: " + ", ".join(sorted(CLAIM_STATUSES)))
        if note is not None and not isinstance(note, str):
            raise ApiError(400, "BAD_REQUEST", "note must be text")
        if note is not None and len(note) > 2000:
            raise ApiError(400, "BAD_REQUEST", "note is too long (2000 characters maximum)")

        previous = conn.execute(
            "SELECT MAX(version) AS v FROM employee_actions WHERE claim_pk = ?", (claim_pk,)
        ).fetchone()
        version = (previous["v"] or 0) + 1
        EmployeeActionsRepository(conn).create(
            uuid.uuid4().hex, claim_pk, status,
            # The actor is the authenticated principal, never a body field.
            actor_user_id=principal.user_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
            version=version,
            note=note,
        )
        return {"claim_pk": claim_pk, "status": status, "note": note, "version": version}

    @app.post("/claims/{claim_pk}/notifications/seen")
    def mark_claim_notifications_seen(
        claim_pk: str, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf),
    ):
        """Marks the claim's currently active unread notifications seen --
        the employee opened the dossier. Freshness only: the workflow status
        in employee_actions is never read or written here. Idempotent: a
        repeat changes nothing and keeps the first seen_at. Local state
        only -- nothing is sent to the portal."""
        require_permission(principal, Permission.NOTIFICATIONS_UPDATE)
        row = conn.execute("SELECT account_id FROM claims WHERE claim_pk = ?", (claim_pk,)).fetchone()
        if row is None:
            raise ApiError(404, "CLAIM_NOT_FOUND", "no such claim")
        # The claim's OWN account decides access and scopes the update --
        # never a client-supplied one (no body is read at all).
        require_account_access(conn, principal, row["account_id"])
        marked = CategoryPresenceRepository(conn).mark_seen_for_claim(
            row["account_id"], claim_pk, seen_at=datetime.now(timezone.utc).isoformat()
        )
        return {"claim_pk": claim_pk, "marked_seen": marked}

    # -- jobs --------------------------------------------------------------

    # An explicit allowlist, not dict(row). Serializing the whole row made
    # every column public by default -- which is how plan_snapshot, holding
    # a vehicle registration and a claim id, reached the browser. Adding a
    # sensitive column to this table must not silently publish it, so a new
    # field appears here only when someone decides it should.
    _JOB_FIELDS = (
        "job_id",
        "account_id",
        "parent_job_id",
        "workflow_name",
        "mode",
        "status",
        "reason_code",
        "plan_hash",       # the dashboard shows it; it is a digest, not content
        "created_at",
        "started_at",
        "finished_at",
    )

    def _job_projection(row) -> dict:
        return {field: row[field] for field in _JOB_FIELDS if field in row.keys()}

    @app.get("/jobs/{job_id}/plan")
    def get_job_plan(job_id: str, principal: Principal = Depends(get_principal)):
        """The plan preview, rebuilt on demand from the encrypted retained
        input rather than read from a stored copy.

        The dashboard genuinely needs this -- it is the panel an employee
        reads before authorizing a fill -- but keeping a plaintext copy on
        disk forever to serve a screen that is looked at once is the wrong
        trade. Rebuilding costs a decrypt and a pure planner call, goes
        through the same account authorization as everything else, and
        leaves nothing behind."""
        require_permission(principal, Permission.JOBS_VIEW)
        row = AutomationJobsRepository(conn).get(job_id)
        if row is None:
            raise ApiError(404, "JOB_NOT_FOUND", "no such job")
        require_account_access(conn, principal, row["account_id"])

        try:
            typed_input_bytes = retrieve_and_verify_job_input(
                conn, job_id, row["input_hash"], encryptor
            )
        except JobInputUnavailable as exc:
            # Expired or already deleted retention -- normal, not an error
            # worth a stack trace.
            raise ApiError(410, "PLAN_INPUT_UNAVAILABLE", "the retained input is no longer available") from exc

        try:
            plan = default_registry().get(row["workflow_name"])(parse_wexia(json.loads(typed_input_bytes)))
        except PlanBuildError as exc:
            raise ApiError(409, "PLAN_BUILD_FAILED", "the retained input could not be re-planned") from exc

        # A DISPLAY projection: what will be written, and what needs a
        # human's attention. Deliberately no expected_identity -- the
        # registration and claim id are exactly the PII this change is
        # removing from storage, and the employee already knows which
        # dossier they uploaded.
        return {
            "job_id": job_id,
            "plan_hash": plan.provenance.plan_hash,
            "repair_workflow": plan.repair_workflow.value,
            "steps": [
                {
                    "rubrique_id": step.rubrique_id.value,
                    "ht": str(step.ht.amount),
                    "tva": str(step.tva.amount),
                    "vetuste": str(step.vetuste.amount),
                }
                for step in plan.steps
            ],
            "form_field_intents": [
                {"selector": intent.selector, "value": str(intent.value)}
                for intent in getattr(plan, "form_field_intents", ())
            ],
            "needs_review": [
                {"reason": item.reason, "detail": getattr(item, "detail", None)}
                for item in plan.needs_review
            ],
        }

    @app.get("/jobs")
    def list_jobs(
        account_id: Optional[str] = None, job_id: Optional[str] = None, principal: Principal = Depends(get_principal)
    ):
        require_permission(principal, Permission.JOBS_VIEW)
        if job_id is not None:
            # A single-job status poll (the dashboard's readiness
            # display) -- still fully authz-checked below via
            # filter_rows_by_account_access, never a bypass of the
            # per-account rules just because one row was named directly.
            row = AutomationJobsRepository(conn).get(job_id)
            rows = [row] if row is not None else []
        elif account_id is not None:
            require_account_access(conn, principal, account_id)
            rows = conn.execute("SELECT * FROM automation_jobs WHERE account_id = ?", (account_id,)).fetchall()
        else:
            visible = visible_account_ids(conn, principal)
            if not visible:
                rows = []
            else:
                placeholders = ",".join("?" for _ in visible)
                rows = conn.execute(
                    f"SELECT * FROM automation_jobs WHERE account_id IN ({placeholders})", tuple(visible)
                ).fetchall()
        filtered = filter_rows_by_account_access(conn, principal, rows)
        return {"jobs": [_job_projection(r) for r in filtered]}

    @app.post("/jobs/dry-runs")
    async def create_dry_run(
        request: Request, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf)
    ):
        require_permission(principal, Permission.JOBS_PLAN)
        body = await request.json()
        if "workflow_name" in body:
            # Pilot-integration correction (section 3): the workflow is
            # ALWAYS determined server-side from the parsed typed_input,
            # never accepted (let alone hardcoded) from the browser --
            # this mirrors the existing `mode` field rejection exactly.
            raise ApiError(400, "BAD_REQUEST", "workflow_name is not a client-settable field")
        account_id = body.get("account_id")
        typed_input = body.get("typed_input")
        idempotency_key = body.get("idempotency_key")
        if not account_id or typed_input is None or not idempotency_key:
            raise ApiError(400, "BAD_REQUEST", "account_id, typed_input, and idempotency_key are required")
        # account_id is NEVER trusted bare from the body -- it is checked
        # against this principal's own access before anything is created.
        require_account_access(conn, principal, account_id)
        _require_mcma_account(conn, account_id)

        try:
            parsed_typed_input = parse_wexia(typed_input)
        except ValidationError as exc:
            raise ApiError(400, "INVALID_TYPED_INPUT", "typed_input does not match the expected dossier shape") from exc
        try:
            repair_workflow = detect_workflow(parsed_typed_input)
            workflow_name = workflow_name_for(repair_workflow)
        except PlanBuildError as exc:
            raise ApiError(409, "WORKFLOW_NOT_DETERMINABLE", "could not determine exactly one workflow from typed evidence") from exc

        typed_input_bytes = json.dumps(typed_input, sort_keys=True).encode("utf-8")
        input_hash = compute_content_hash(typed_input_bytes)
        job_id = enqueue_dry_run(
            conn,
            account_id=account_id,
            requested_by_user_id=principal.user_id,
            workflow_name=workflow_name,
            input_hash=input_hash,
            typed_input_bytes=typed_input_bytes,
            idempotency_key=idempotency_key,
            encryptor=encryptor,
        )
        return {"job_id": job_id, "status": AutomationJobsRepository(conn).get(job_id)["status"], "workflow_name": workflow_name}

    @app.post("/jobs/{dry_run_job_id}/executions")
    async def create_execution(
        dry_run_job_id: str, request: Request, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf)
    ):
        require_permission(principal, Permission.JOBS_EXECUTE)
        body = await request.json()
        if "mode" in body:
            raise ApiError(400, "BAD_REQUEST", "mode is not a client-settable field")
        idempotency_key = body.get("idempotency_key") or uuid.uuid4().hex

        jobs_repo = AutomationJobsRepository(conn)
        parent = jobs_repo.get(dry_run_job_id)
        if parent is None:
            raise ApiError(404, "NOT_FOUND", "dry-run job not found")
        # account_id is derived from the PARENT job, never accepted from
        # the request body (correction #3 / review AR-M3: the authorizer
        # is always the authenticated session user, never client-supplied).
        require_account_access(conn, principal, parent["account_id"])
        _require_mcma_account(conn, parent["account_id"])
        if parent["status"] != "DRY_RUN_VERIFIED":
            raise ApiError(409, "PARENT_NOT_DRY_RUN_VERIFIED", "the referenced job is not an approved dry-run")

        try:
            retrieve_and_verify_job_input(conn, dry_run_job_id, parent["input_hash"], encryptor)
        except JobInputUnavailable as exc:
            raise ApiError(409, exc.reason_code, "the dry-run's retained input is no longer usable") from exc

        try:
            plan_builder = _WORKFLOW_REGISTRY.get(parent["workflow_name"])
        except KeyError as exc:
            raise ApiError(409, "UNSUPPORTED_WORKFLOW_NAME", "no known plan builder for this workflow") from exc

        parent_input_row = conn.execute("SELECT ciphertext, pii_class FROM job_inputs WHERE job_id = ?", (dry_run_job_id,)).fetchone()
        parent_typed_input_bytes = encryptor.decrypt(bytes(parent_input_row["ciphertext"]))
        execute_job_id = enqueue_execute(
            conn,
            account_id=parent["account_id"],
            requested_by_user_id=principal.user_id,
            workflow_name=parent["workflow_name"],
            input_hash=parent["input_hash"],
            typed_input_bytes=parent_typed_input_bytes,
            idempotency_key=idempotency_key,
            encryptor=encryptor,
            parent_job_id=dry_run_job_id,
            # Known at creation time (the authenticated caller of this
            # very endpoint) -- recorded atomically with the job row
            # itself rather than a separate post-hoc update (Fable-
            # review-2 correction: the old pattern skipped the version-
            # bump/outbox-event invariant every other status change goes
            # through).
            authorized_by_user_id=principal.user_id,
        )

        def _rebuild_plan_from_retained_input():
            # Fable-review-2 correction (HIGH finding): this used to be
            # an always-matching stub, making run_execute_planning's
            # hash re-check vacuous. It now re-derives the plan from the
            # SAME retained input bytes through the SAME pure builder
            # the workflow_name names -- a genuine re-verification.
            typed_input = parse_wexia(json.loads(parent_typed_input_bytes))
            return plan_builder(typed_input)

        try:
            run_execute_planning(conn, execute_job_id, rebuild_plan_from_retained_input=_rebuild_plan_from_retained_input)
        except PlanBuildError as exc:
            raise ApiError(409, "PLAN_BUILD_FAILED", "the retained input could not be re-planned") from exc
        except JobAuthorizationError as exc:
            raise ApiError(409, exc.reason_code, "execution authorization failed") from exc

        return {"job_id": execute_job_id, "status": jobs_repo.get(execute_job_id)["status"]}

    # -- human browser handoff (section G) ---------------------------------

    def _load_job_for_handoff(job_id: str, principal: Principal):
        jobs_repo = AutomationJobsRepository(conn)
        job_row = jobs_repo.get(job_id)
        if job_row is None:
            raise ApiError(404, "NOT_FOUND", "job not found")
        # account_id/user_id/status are NEVER accepted from the client
        # body for either handoff endpoint below -- the actor is always
        # the authenticated session user, and the account is always the
        # job's own account_id.
        require_account_access(conn, principal, job_row["account_id"])
        return job_row

    @app.post("/jobs/{job_id}/review-completed")
    async def review_completed(
        job_id: str, request: Request, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf)
    ):
        require_permission(principal, Permission.JOBS_EXECUTE)
        body = await request.json() if await request.body() else {}
        if any(k in body for k in ("account_id", "user_id", "confirmed_by_user_id", "status")):
            raise ApiError(400, "BAD_REQUEST", "account_id/user_id/status are not client-settable fields")
        _load_job_for_handoff(job_id, principal)
        try:
            status = confirm_review_completed(conn, job_id, confirmed_by_user_id=principal.user_id)
        except JobAuthorizationError as exc:
            raise ApiError(409, exc.reason_code, "the job cannot be confirmed completed right now") from exc
        return {"job_id": job_id, "status": status}

    @app.post("/jobs/{job_id}/problem")
    async def report_problem(
        job_id: str, request: Request, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf)
    ):
        require_permission(principal, Permission.JOBS_EXECUTE)
        body = await request.json() if await request.body() else {}
        if any(k in body for k in ("account_id", "user_id", "reported_by_user_id", "status")):
            raise ApiError(400, "BAD_REQUEST", "account_id/user_id/status are not client-settable fields")
        reason_code = body.get("reason_code") or "EMPLOYEE_REPORTED_PROBLEM"
        if not isinstance(reason_code, str) or len(reason_code) > 200:
            # Fable-review-2 correction (LOW finding): reason_code was an
            # unvalidated, unbounded client string persisted verbatim and
            # echoed back in GET /jobs -- capped here (a stored free-text
            # channel, even if not an XSS sink today, should still be
            # typed and bounded).
            raise ApiError(400, "BAD_REQUEST", "reason_code must be a string of at most 200 characters")
        _load_job_for_handoff(job_id, principal)
        try:
            status = report_review_problem(
                conn, job_id, reported_by_user_id=principal.user_id, reason_code=reason_code
            )
        except JobAuthorizationError as exc:
            raise ApiError(409, exc.reason_code, "a problem cannot be reported for this job right now") from exc
        return {"job_id": job_id, "status": status}

    # -- events (SSE, real authorizer) -------------------------------------

    sse_endpoint = create_sse_endpoint(conn, authorizer, get_principal)
    app.add_api_route("/events", sse_endpoint, methods=["GET"])

    # -- health --------------------------------------------------------------

    @app.get("/health")
    def health():
        try:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok}

    return app
