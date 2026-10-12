"""mcma.app.workstation_runner.notification_login -- the ONE portal-touching
piece of notification onboarding (composition-root side, like app.py: the
lightweight lifecycle in notification_onboarding.py never imports
mcma.portal, this module does and is injected into it).

perform_notification_login(account_id, on_window_opened, timeout_seconds):
  * maps the server-named account id LOCALLY to one of the four canonical
    PortalAccountProfile values (MCMA/MAMDA x OUJDA/NADOR) -- the server
    never supplies an entity, scope, host, URL or selector;
  * builds the reviewed auth contracts for THAT profile's entity on the
    fixed DEFAULT_SINAUTO_HOST: LoginCapability can only GET the one login
    page and poll fixed logged-in markers. There is no parameter anywhere
    for a credential, OTP, URL, route or selector;
  * launches a FRESH visible (headed) browser per request and opens an
    isolated guarded login context in it -- never an existing profile,
    never the agent-session browser, never headless;
  * returns the redacted SessionMaterial once the logged-in markers are
    positively observed. The login and the browser are closed on every
    exit path (success, timeout, window closed, any error, task
    cancellation) by the `finally` / `async with` below.

The captured storage state is never written anywhere here; it travels
only inside the returned SessionMaterial (single-consumption)."""

from __future__ import annotations

from typing import Callable

from mcma.domain.portal_accounts import THE_FOUR_PROFILES, PortalAccountProfile, canonical_account_id
from mcma.portal.browser import launch_browser
from mcma.portal.capabilities import SessionMaterial, open_login_session
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST, auth_contracts

_PROFILE_BY_ACCOUNT_ID = {canonical_account_id(profile): profile for profile in THE_FOUR_PROFILES}


class UnknownNotificationAccount(ValueError):
    """Not one of the four canonical notification accounts. Fixed message;
    the rejected value is never retained."""

    def __init__(self) -> None:
        super().__init__("account_id is not one of the four canonical notification accounts")


class NotificationLoginFailed(Exception):
    """A typed, text-free failure (only a fixed reason)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def profile_for_account(account_id: object) -> PortalAccountProfile:
    if not isinstance(account_id, str) or account_id not in _PROFILE_BY_ACCOUNT_ID:
        raise UnknownNotificationAccount()
    return _PROFILE_BY_ACCOUNT_ID[account_id]


async def perform_notification_login(
    account_id: str, on_window_opened: Callable[[], None], timeout_seconds: float,
) -> SessionMaterial:
    profile = profile_for_account(account_id)
    contracts = auth_contracts(DEFAULT_SINAUTO_HOST, profile.entity.value)
    async with launch_browser(headless=False) as browser:
        try:
            login = await open_login_session(browser, account_id, contracts, DEFAULT_SINAUTO_HOST)
        except Exception:
            # Fixed reason only: the underlying text can quote page content.
            raise NotificationLoginFailed("LOGIN_PAGE_UNREACHABLE") from None
        try:
            on_window_opened()
            return await login.perform_manual_login(timeout_seconds=timeout_seconds)
        finally:
            await login.close()
