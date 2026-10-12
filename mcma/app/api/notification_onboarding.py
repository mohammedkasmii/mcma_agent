"""
mcma.app.api.notification_onboarding -- HTTP surface of the centralized
notification-session onboarding (see mcma.app.runners.notification_onboarding
for the state machine and the reasoning).

Two authentication worlds, never mixed:

  * BROWSER routes (employee session cookie + CSRF on every POST):
        POST /accounts/{account_id}/login          202 queued / 200 already active
        GET  /accounts/{account_id}/login-status   200
        POST /accounts/{account_id}/login/cancel   200
    The body must be empty or `{}`: the browser can never name a runner, user,
    entity, scope, URL, server or credential -- all of those are derived on the
    server from the session. They return at once; nothing here waits for the
    employee to finish signing in.

  * MACHINE routes (`Authorization: Bearer <runner secret>` ONLY -- no
    cookies, no CSRF, never a query parameter):
        POST /runner/notification-onboarding/claim
        POST /runner/notification-onboarding/{request_id}/renew
        POST /runner/notification-onboarding/{request_id}/complete
        POST /runner/notification-onboarding/{request_id}/fail
    Strict JSON objects (unknown fields refused), small explicit body limits
    (4 KiB; 512 KiB for the one route that carries the session), fixed error
    codes and messages that never echo input.

Every response is Cache-Control: no-store. The captured session is parsed
with a strict loader, handed to the service and never logged.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from mcma.app.api.admin_users import _NO_STORE, _as_api_error
from mcma.app.api.authz import Principal, require_account_access, require_permission
from mcma.app.api.deps import require_csrf
from mcma.app.api.errors import ApiError
from mcma.app.api.runners import _bearer_token, _bounded_json, _read_bounded
from mcma.app.auth.users import UserInputError
from mcma.app.runners import registry
from mcma.app.runners.notification_onboarding import NOTIFICATION_ACCOUNT_IDS, NotificationOnboardingService
from mcma.domain.enums import Permission
from mcma.portal.storage_state import StorageStateRejected, strict_loads

MAX_BROWSER_BODY_BYTES = 64
MAX_COMPLETE_BODY_BYTES = 524_288                    # 512 KiB, session payload included


async def _browser_body_must_be_empty(request: Request) -> None:
    raw = await _read_bounded(request, MAX_BROWSER_BODY_BYTES)
    if not raw.strip():
        return
    try:
        body = strict_loads(raw)
    except StorageStateRejected:
        raise ApiError(400, "BAD_REQUEST", "corps JSON invalide") from None
    if body != {}:
        raise ApiError(400, "BAD_REQUEST", "champs invalides")


def register_notification_onboarding_routes(
    app: FastAPI, conn, get_principal, service: NotificationOnboardingService,
) -> None:
    def _checked(principal: Principal, account_id: str) -> None:
        require_permission(principal, Permission.NOTIFICATIONS_READ)
        require_account_access(conn, principal, account_id)
        if account_id not in NOTIFICATION_ACCOUNT_IDS:
            raise ApiError(404, "UNKNOWN_ACCOUNT", "compte inconnu")

    # ------------------------------ browser ------------------------------ #

    @app.post("/accounts/{account_id}/login")
    async def start_notification_login(
        account_id: str, request: Request, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf),
    ):
        await _browser_body_must_be_empty(request)
        _checked(principal, account_id)
        try:
            view, created = await run_in_threadpool(service.request_login, principal.user_id, account_id)
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(view, status_code=202 if created else 200, headers=_NO_STORE)

    @app.get("/accounts/{account_id}/login-status")
    async def notification_login_status(account_id: str, principal: Principal = Depends(get_principal)):
        _checked(principal, account_id)
        try:
            view = await run_in_threadpool(service.status, principal.user_id, account_id)
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(view, headers=_NO_STORE)

    @app.post("/accounts/{account_id}/login/cancel")
    async def cancel_notification_login(
        account_id: str, request: Request, principal: Principal = Depends(get_principal), _csrf=Depends(require_csrf),
    ):
        await _browser_body_must_be_empty(request)
        _checked(principal, account_id)
        try:
            view = await run_in_threadpool(service.cancel, principal.user_id, account_id)
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(view, headers=_NO_STORE)

    # ------------------------------ machine ------------------------------ #

    async def _runner(request: Request) -> registry.RunnerPrincipal:
        principal = await run_in_threadpool(registry.authenticate_runner, conn, _bearer_token(request))
        if principal is None:
            raise ApiError(401, "RUNNER_UNAUTHENTICATED", "authentification du poste refusée")
        return principal

    @app.post("/runner/notification-onboarding/claim")
    async def runner_claim_onboarding(request: Request):
        principal = await _runner(request)
        body = await _bounded_json(request, {"protocol_version", "app_version"}, {"protocol_version", "app_version"})
        try:
            envelope = await run_in_threadpool(
                service.claim, principal, protocol_version=body["protocol_version"], app_version=body["app_version"],
            )
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        if envelope is None:
            return Response(status_code=204, headers=_NO_STORE)
        return JSONResponse(envelope, headers=_NO_STORE)

    @app.post("/runner/notification-onboarding/{request_id}/renew")
    async def runner_renew_onboarding(request_id: str, request: Request):
        principal = await _runner(request)
        body = await _bounded_json(
            request, {"claim_token", "generation", "phase"}, {"claim_token", "generation", "phase"},
        )
        try:
            result = await run_in_threadpool(
                service.renew, principal, request_id=request_id, claim_token=body["claim_token"],
                generation=body["generation"], phase=body["phase"],
            )
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(result, headers=_NO_STORE)

    @app.post("/runner/notification-onboarding/{request_id}/fail")
    async def runner_fail_onboarding(request_id: str, request: Request):
        principal = await _runner(request)
        body = await _bounded_json(
            request, {"claim_token", "generation", "reason_code"}, {"claim_token", "generation", "reason_code"},
        )
        try:
            result = await run_in_threadpool(
                service.fail, principal, request_id=request_id, claim_token=body["claim_token"],
                generation=body["generation"], reason_code=body["reason_code"],
            )
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(result, headers=_NO_STORE)

    @app.post("/runner/notification-onboarding/{request_id}/complete")
    async def runner_complete_onboarding(request_id: str, request: Request):
        principal = await _runner(request)
        # Bearer first, THEN the (large) body: an unauthenticated caller can never
        # make this server read more than a few KiB.
        raw = await _read_bounded(request, MAX_COMPLETE_BODY_BYTES)
        try:
            body = strict_loads(raw)
        except StorageStateRejected:
            raise ApiError(400, "BAD_REQUEST", "corps JSON invalide") from None
        if not isinstance(body, dict) or set(body) != {"claim_token", "generation", "storage_state"}:
            raise ApiError(400, "BAD_REQUEST", "champs invalides")
        try:
            result = await run_in_threadpool(
                service.complete, principal, request_id=request_id, claim_token=body["claim_token"],
                generation=body["generation"], storage_state=body["storage_state"],
            )
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(result, headers=_NO_STORE)
