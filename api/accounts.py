"""
api/accounts.py — Account Cards, OTP Login, Manual Refresh
===========================================================
The four portal profiles: their session health, the per-account login that opens
a browser on the server's desktop, and a manual refresh on top of the automatic
poll.

BLUEPRINT §3, §5, §6.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from api.deps import get_repo
from core.accounts import ACCOUNT_IDS, resolve_auth_state_path
from core.window import WINDOW
from portal import auth as portal_auth
from portal.poller import poll_all_accounts, poll_one_account

router = APIRouter(prefix="/api/v1", tags=["accounts"])


@router.get("/accounts")
async def api_accounts():
    """
    The four account cards.

    `last_successful_poll_at` is what lets the UI distinguish "nothing new" from
    "we have not been able to look since Tuesday" — those render identically and
    mean opposite things (§7.3).
    """
    repo = get_repo()
    accounts = repo.list_accounts(only_enabled=False)
    for acc in accounts:
        acc["has_session"] = bool(resolve_auth_state_path(acc["account_id"]))
        acc["login_in_flight"] = portal_auth.is_login_in_flight(acc["account_id"])
    return {
        "status": "success",
        "accounts": accounts,
        "window": WINDOW.status(),
        "warn_sessions": WINDOW.should_warn_sessions(),
    }


@router.post("/accounts/{account_id}/login")
async def api_account_login(account_id: str):
    """
    Opens a visible login window ON THE SERVER for one account.

    Refuses outside the operating window with a clear message, so nobody
    concludes the system is broken when the portal is simply closed.
    """
    if account_id not in ACCOUNT_IDS:
        raise HTTPException(status_code=404, detail=f"Compte inconnu : {account_id}")

    repo = get_repo()
    try:
        result = await portal_auth.interactive_login(account_id)
    except portal_auth.LoginRefused as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result["success"]:
        repo.set_session_health(account_id, "HEALTHY", validated=True)
        repo.audit("ACCOUNT_LOGIN", actor="employee", account_id=account_id)
    else:
        repo.set_session_health(account_id, "EXPIRED", error=result["message"])
    return {"status": "success" if result["success"] else "failed", **result}


@router.post("/accounts/{account_id}/validate")
async def api_account_validate(account_id: str):
    """Headless session check — used by the start-of-shift validation."""
    if account_id not in ACCOUNT_IDS:
        raise HTTPException(status_code=404, detail=f"Compte inconnu : {account_id}")

    repo = get_repo()
    result = await portal_auth.validate_session(account_id)
    repo.set_session_health(
        account_id,
        result["health"],
        error=None if result["valid"] else result["message"],
        validated=result["valid"],
    )
    return {"status": "success", **result}


@router.post("/refresh")
async def api_refresh(account_id: Optional[str] = None):
    """
    Manual refresh, on top of the automatic 5-minute poll.

    Reuses the poller's per-account lock, so repeated clicks queue behind each
    other instead of spawning a browser per click.
    """
    repo = get_repo()
    if not WINDOW.is_open():
        raise HTTPException(
            status_code=409,
            detail=WINDOW.status().get("message", "Portail fermé."),
        )
    if account_id:
        if account_id not in ACCOUNT_IDS:
            raise HTTPException(status_code=404, detail=f"Compte inconnu : {account_id}")
        results = [await poll_one_account(repo, account_id)]
    else:
        results = await poll_all_accounts(repo)
    return {"status": "success", "results": results, "version": repo.get_state()["version"]}
