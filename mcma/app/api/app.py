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
        # session_active tells the dashboard which accounts can currently
        # be polled or written to at all. Without it, an account with no
        # captured portal session looks identical to one that simply has
        # no notifications, and "why is this list empty" has no answer.
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
            account["session_active"] = account["account_id"] in active_sessions
            if account["account_id"] in active_sessions:
                account["connection_state"] = "CONNECTED"
            elif account["account_id"] in ever_connected:
                account["connection_state"] = "RECONNECT_REQUIRED"
            else:
                account["connection_state"] = "NOT_CONNECTED"
            # A MAMDA account is readable but can never be the target of a
            # form job. Stating it here means the dashboard never has to
            # re-derive the rule from the entity string.
            account["writable"] = account.get("entity") == "MCMA"
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

    def _categories_by_claim(claim_pks):
        """Which alert categories each claim is currently present in -- the
        portal's own reason for surfacing it."""
        if not claim_pks:
            return {}
        placeholders = ",".join("?" for _ in claim_pks)
        rows = conn.execute(
            "SELECT p.claim_pk, p.category_code, c.label FROM category_presence p "
            "LEFT JOIN categories c ON c.code_alerte = p.category_code "
            f"WHERE p.claim_pk IN ({placeholders}) AND p.present = 1",
            tuple(claim_pks),
        ).fetchall()
        by_claim = {}
        for row in rows:
            by_claim.setdefault(row["claim_pk"], []).append(row["label"] or row["category_code"])
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
        categories = _categories_by_claim(claim_pks)

        claims = []
        for row in filtered:
            claim = dict(row)
            action = actions.get(claim["claim_pk"])
            claim["status"] = action["status"] if action else "NEW"
            claim["note"] = action["note"] if action else None
            claim["updated_at"] = action["updated_at"] if action else None
            claim["categories"] = categories.get(claim["claim_pk"], [])
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

    # -- jobs --------------------------------------------------------------

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
        return {"jobs": [dict(r) for r in filtered]}

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
