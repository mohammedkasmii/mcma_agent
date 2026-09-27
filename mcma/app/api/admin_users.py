"""
mcma.app.api.admin_users -- minimal admin-only management of the pilot's
MCMA Platform users (2-3 employees). Platform accounts only: no MCMA/MAMDA
portal credential or browser session is read or written here.

Every endpoint:
  * requires an authenticated principal derived from the server-side
    session (never from request data) holding USERS_MANAGE (admin only);
  * every mutating endpoint also requires the CSRF double-submit header;
  * returns users through mcma.app.auth.users.user_view -- never a password
    or a hash -- with Cache-Control: no-store.

All rules (validation, transactions, last-admin / self-lockout protection,
audit) live in mcma.app.auth.users so the offline command shares them.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from mcma.app.api.authz import Principal, require_permission
from mcma.app.api.deps import require_csrf
from mcma.app.api.errors import ApiError
from mcma.app.auth import users
from mcma.app.auth.sessions import SessionStore
from mcma.domain.enums import Permission

_NO_STORE = {"Cache-Control": "no-store"}


def _as_api_error(exc: users.UserInputError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message)


async def _json_object(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "BAD_REQUEST", "corps JSON invalide") from None
    if not isinstance(body, dict):
        raise ApiError(400, "BAD_REQUEST", "un objet JSON est attendu")
    return body


def register_admin_user_routes(app: FastAPI, conn, get_principal, session_store: SessionStore) -> None:
    def admin(principal: Principal = Depends(get_principal)) -> Principal:
        require_permission(principal, Permission.USERS_MANAGE)
        return principal

    @app.get("/admin/users")
    def list_platform_users(principal: Principal = Depends(admin)):
        return JSONResponse({"users": users.list_users(conn)}, headers=_NO_STORE)

    @app.post("/admin/users")
    async def create_platform_user(
        request: Request, principal: Principal = Depends(admin), _csrf=Depends(require_csrf),
    ):
        body = await _json_object(request)
        try:
            created = await run_in_threadpool(
                users.create_user, conn,
                actor_user_id=principal.user_id,               # from the session, never from the body
                username=body.get("username"), password=body.get("password"),
                role=body.get("role"), account_ids=body.get("account_ids", []),
            )
        except users.UserInputError as exc:
            raise _as_api_error(exc) from None
        return JSONResponse({"user": created}, status_code=201, headers=_NO_STORE)

    @app.patch("/admin/users/{user_id}")
    async def update_platform_user(
        user_id: str, request: Request, principal: Principal = Depends(admin), _csrf=Depends(require_csrf),
    ):
        body = await _json_object(request)
        unknown = set(body) - {"active", "role", "account_ids"}
        if unknown or not body:
            raise ApiError(400, "BAD_REQUEST", "champs modifiables : active, role, account_ids")
        try:
            updated, end_sessions = await run_in_threadpool(
                users.update_user, conn,
                actor_user_id=principal.user_id, user_id=user_id,
                active=body.get("active"), role=body.get("role"), account_ids=body.get("account_ids"),
            )
        except users.UserInputError as exc:
            raise _as_api_error(exc) from None
        if end_sessions:
            session_store.invalidate_user(user_id)
        return JSONResponse({"user": updated}, headers=_NO_STORE)

    @app.post("/admin/users/{user_id}/password")
    async def reset_platform_user_password(
        user_id: str, request: Request, principal: Principal = Depends(admin), _csrf=Depends(require_csrf),
    ):
        body = await _json_object(request)
        try:
            await run_in_threadpool(
                users.reset_password, conn,
                actor_user_id=principal.user_id, user_id=user_id, password=body.get("password"),
            )
        except users.UserInputError as exc:
            raise _as_api_error(exc) from None
        # The user's existing sessions were opened with the OLD password.
        session_store.invalidate_user(user_id)
        return JSONResponse({"status": "password_reset"}, headers=_NO_STORE)
