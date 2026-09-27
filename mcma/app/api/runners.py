"""
mcma.app.api.runners -- HTTP surface of the workstation-runner registry
(Phase 1A). Three separate authentication worlds, never mixed:

  * ADMIN endpoints  (/admin/runner-enrollments, /admin/runners...):
    employee platform session cookie + runners:manage (admin only) + CSRF on
    every change. The acting admin comes from the session.
  * EMPLOYEE endpoint (/runner-status): employee session cookie; returns only
    the caller's own runner.
  * MACHINE endpoints (/runner/enroll, /runner/heartbeat): NO cookies and NO
    CSRF. Enrollment authenticates with a one-time pairing code in the JSON
    body; heartbeat with `Authorization: Bearer <runner secret>` ONLY --
    never a query parameter, cookie or body field. The runner's identity and
    assigned employee are derived from that credential; the request cannot
    choose them.

Every response is Cache-Control: no-store. Bodies are parsed strictly
(unknown fields refused, size bounded); errors carry fixed messages and never
echo input, secrets or exception text.
"""

from __future__ import annotations

import json

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from mcma.app.api.admin_users import _NO_STORE, _as_api_error
from mcma.app.api.authz import Principal, require_permission
from mcma.app.api.deps import require_csrf
from mcma.app.api.errors import ApiError
from mcma.app.auth.users import UserInputError
from mcma.app.runners import registry
from mcma.domain.enums import Permission

MAX_BODY_BYTES = 4096


def _bearer_token(request: Request):
    """The ONLY place a runner credential is read: the Authorization header."""
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _too_large() -> ApiError:
    return ApiError(413, "PAYLOAD_TOO_LARGE", "corps trop volumineux")


async def _read_bounded(request: Request) -> bytes:
    """Reads the body INCREMENTALLY and gives up the moment MAX_BODY_BYTES is
    crossed, so an arbitrarily large (or endless) upload -- notably on the
    unauthenticated /runner/enroll -- is never buffered. At most
    MAX_BODY_BYTES already-accepted bytes plus the current chunk are held, and
    the rest of the stream is left unread.

    Content-Length is only an early hint: a malformed or oversized declaration
    is refused without touching the body, but a missing or falsely small one
    proves nothing, so the ACTUAL bytes are always counted."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
        raise _too_large()
    chunks: list = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise _too_large()                     # stop reading; nothing further is consumed
        chunks.append(chunk)
    return b"".join(chunks)


async def _bounded_json(request: Request, allowed: set, required: set) -> dict:
    raw = await _read_bounded(request)
    try:
        body = json.loads(raw)                     # from the bounded bytes; never request.json()
    except (ValueError, RecursionError):           # UnicodeDecodeError is a ValueError
        raise ApiError(400, "BAD_REQUEST", "corps JSON invalide") from None
    if not isinstance(body, dict):
        raise ApiError(400, "BAD_REQUEST", "un objet JSON est attendu")
    if set(body) - allowed or required - set(body):
        raise ApiError(400, "BAD_REQUEST", "champs invalides")       # never says which, never echoes
    return body


def register_runner_routes(app: FastAPI, conn, get_principal) -> None:
    def admin(principal: Principal = Depends(get_principal)) -> Principal:
        require_permission(principal, Permission.RUNNERS_MANAGE)
        return principal

    # ------------------------------ admin ------------------------------- #

    @app.post("/admin/runner-enrollments")
    async def create_runner_enrollment(
        request: Request, principal: Principal = Depends(admin), _csrf=Depends(require_csrf),
    ):
        body = await _bounded_json(request, {"target_user_id", "runner_label"}, {"target_user_id"})
        try:
            created = await run_in_threadpool(
                registry.create_enrollment, conn,
                actor_user_id=principal.user_id,                        # from the session
                target_user_id=body["target_user_id"], runner_label=body.get("runner_label"),
            )
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(created, status_code=201, headers=_NO_STORE)

    @app.get("/admin/runners")
    def list_runners(principal: Principal = Depends(admin)):
        return JSONResponse(registry.admin_overview(conn), headers=_NO_STORE)

    @app.post("/admin/runners/{runner_id}/revoke")
    def revoke_runner(runner_id: str, principal: Principal = Depends(admin), _csrf=Depends(require_csrf)):
        try:
            view, already = registry.revoke_runner(conn, actor_user_id=principal.user_id, runner_id=runner_id)
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse({"runner": view, "already_revoked": already}, headers=_NO_STORE)

    # ----------------------------- employee ------------------------------ #

    @app.get("/runner-status")
    def own_runner_status(principal: Principal = Depends(get_principal)):
        return JSONResponse(registry.runner_status_for_user(conn, principal.user_id), headers=_NO_STORE)

    # ------------------------------ machine ------------------------------ #

    @app.post("/runner/enroll")
    async def runner_enroll(request: Request):
        body = await _bounded_json(
            request, {"pairing_code", "runner_label", "protocol_version", "app_version"},
            {"pairing_code", "protocol_version", "app_version"},
        )
        try:
            enrolled = await run_in_threadpool(
                registry.enroll, conn,
                pairing_code=body["pairing_code"], runner_label=body.get("runner_label"),
                protocol_version=body["protocol_version"], app_version=body["app_version"],
            )
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(enrolled, status_code=201, headers=_NO_STORE)

    @app.post("/runner/heartbeat")
    async def runner_heartbeat(request: Request):
        principal = await run_in_threadpool(registry.authenticate_runner, conn, _bearer_token(request))
        if principal is None:
            raise ApiError(401, "RUNNER_UNAUTHENTICATED", "authentification du poste refusée")
        body = await _bounded_json(request, {"protocol_version", "app_version", "sessions"},
                                   {"protocol_version", "app_version", "sessions"})
        try:
            result = await run_in_threadpool(
                registry.heartbeat, conn, principal,
                protocol_version=body["protocol_version"], app_version=body["app_version"],
                sessions=body["sessions"],
            )
        except UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse(result, headers=_NO_STORE)
