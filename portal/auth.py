"""
portal/auth.py — Per-Account OTP Login
=======================================
Implements the "morning ritual" of PROJECT_ARCHITECTURE_BLUEPRINT.md §6.

Every account needs its own login plus an SMS OTP, so no daemon can ever
authenticate by itself. Rather than building machinery to postpone an
unavoidable human step — machinery that fails silently at 02:00 when nobody is
watching — authentication is an explicit, visible action:

    an employee clicks « Reconnecter » on an account card, a browser opens ON
    THE SERVER'S DESKTOP, they type the credentials and the SMS code, the card
    turns green.

This is why the application must run as a Task Scheduler logon task and not as a
Session 0 Windows service: a service cannot render this window (§12.1).
"""

import asyncio
import os
import sys
from typing import Dict, Optional

from core.accounts import auth_state_path, ensure_sessions_dir, get_account
from core.config import BASE_URL
from core.window import WINDOW

LOGIN_TIMEOUT_SECONDS = 300

#: Accounts with a login window currently open, so a second click cannot start
#: a competing browser for the same account.
_in_flight: Dict[str, bool] = {}


def is_login_in_flight(account_id: str) -> bool:
    return bool(_in_flight.get(account_id))


class LoginRefused(RuntimeError):
    """Raised when a login cannot be started (window closed, already running)."""


async def interactive_login(account_id: str, headless: bool = False) -> dict:
    """
    Opens a visible browser for one account and waits for the dashboard.

    Returns a result dict; never raises for an ordinary failed login.
    """
    account = get_account(account_id)
    if account is None:
        raise LoginRefused(f"Compte inconnu : {account_id}")

    if is_login_in_flight(account_id):
        raise LoginRefused(
            f"Une fenêtre de connexion est déjà ouverte pour {account['display_name']}."
        )

    if not WINDOW.is_open():
        raise LoginRefused(
            "Portail MAMDA/MCMA indisponible jusqu'à demain matin "
            f"({WINDOW.start.strftime('%H:%M')}). Aucune connexion possible maintenant."
        )

    from playwright.async_api import async_playwright

    ensure_sessions_dir()
    path = auth_state_path(account_id)
    _in_flight[account_id] = True

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto(account.get("base_url") or BASE_URL)

            detected = False
            for second in range(LOGIN_TIMEOUT_SECONDS):
                await asyncio.sleep(1)
                url = page.url.lower()

                if any(k in url for k in ("/expertise/", "/frontexpert", "/gestionexpert")):
                    detected = True
                    break
                try:
                    has_dashboard = await page.locator(
                        "#formRecherche, #ReferenceCie, a[href*='logout'], a[href*='Login/logout']"
                    ).count() > 0
                    if has_dashboard and "login" not in url and "otp" not in url:
                        detected = True
                        break
                except Exception:
                    pass

            if detected:
                try:
                    await page.wait_for_selector(
                        "#formRecherche, #ReferenceCie, #Matricule, a[href*='logout']",
                        timeout=5000,
                    )
                except Exception:
                    pass
                await asyncio.sleep(1)

            await context.storage_state(path=path)
            await browser.close()

        ok = detected and os.path.exists(path) and os.path.getsize(path) > 10
        return {
            "account_id": account_id,
            "success": ok,
            "auth_state_path": path,
            "message": (
                f"Session enregistrée pour {account['display_name']}."
                if ok
                else "Connexion non détectée (délai dépassé ou fenêtre fermée)."
            ),
        }
    finally:
        _in_flight.pop(account_id, None)


async def validate_session(account_id: str) -> dict:
    """
    Headless check that an account's saved session still works.

    Used by the start-of-shift validation so the four account cards are already
    green-or-grey before the first employee sits down (§5).
    """
    from core.accounts import resolve_auth_state_path
    from core.config import DASHBOARD_URL
    from playwright.async_api import async_playwright

    path = resolve_auth_state_path(account_id)
    if not path:
        return {"account_id": account_id, "valid": False,
                "health": "NEVER_AUTHENTICATED",
                "message": "Aucune session enregistrée."}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=path)
            page = await context.new_page()
            try:
                await page.goto(DASHBOARD_URL, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1200)
                url = page.url.lower()
                content = await page.content()

                is_login = (
                    "login" in url
                    or "expert_.phtml" in content
                    or await page.locator("input[name='login'], #login, #password").count() > 0
                )
                if is_login:
                    return {"account_id": account_id, "valid": False, "health": "EXPIRED",
                            "message": "Session expirée — reconnexion requise."}

                await context.storage_state(path=path)
                return {"account_id": account_id, "valid": True, "health": "HEALTHY",
                        "message": "Session active."}
            finally:
                await browser.close()
    except Exception as e:
        return {"account_id": account_id, "valid": False, "health": "UNKNOWN",
                "message": f"Erreur de connexion : {e}"}
