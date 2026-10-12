"""mcma.app.workstation_runner.notification_login -- the portal-touching
glue for notification onboarding: local account -> canonical profile ->
fixed auth contracts, a fresh HEADED browser per request, and cleanup on
every exit path. mcma.portal's launch_browser/open_login_session are faked:
no Playwright, no real window, no network."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from mcma.app.workstation_runner import notification_login as module
from mcma.app.workstation_runner.notification_login import (
    NotificationLoginFailed, UnknownNotificationAccount, perform_notification_login, profile_for_account,
)
from mcma.domain.portal_accounts import PortalEntity, PortalScope
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST


class Recorder:
    def __init__(self):
        self.launches: list = []
        self.contract_calls: list = []
        self.opened: list = []
        self.browser_exits = 0
        self.login_closes = 0
        self.login_behaviour = "success"
        self.open_raises = None
        self.login_kwargs: list = []


def _install(monkeypatch, rec: Recorder):
    @asynccontextmanager
    async def fake_launch(*, headless=False):
        rec.launches.append(headless)
        try:
            yield object()
        finally:
            rec.browser_exits += 1

    class FakeLogin:
        async def perform_manual_login(self, *, poll_interval_seconds=1.0, timeout_seconds=300.0):
            rec.login_kwargs.append((poll_interval_seconds, timeout_seconds))
            if rec.login_behaviour == "wait":
                await asyncio.Event().wait()
            if isinstance(rec.login_behaviour, BaseException):
                raise rec.login_behaviour
            return "MATERIAL"

        async def close(self):
            rec.login_closes += 1

    async def fake_open(browser, account_id, contracts, allowed_host, **kwargs):
        rec.opened.append((account_id, tuple(contracts), allowed_host, kwargs))
        if rec.open_raises is not None:
            raise rec.open_raises
        return FakeLogin()

    real_auth = module.auth_contracts

    def spy_auth(host, entity):
        rec.contract_calls.append((host, entity))
        return real_auth(host, entity)

    monkeypatch.setattr(module, "launch_browser", fake_launch)
    monkeypatch.setattr(module, "open_login_session", fake_open)
    monkeypatch.setattr(module, "auth_contracts", spy_auth)


@pytest.mark.parametrize("account_id,entity", [
    ("acct-mcma-oujda", "MCMA"), ("acct-mcma-nador", "MCMA"),
    ("acct-mamda-oujda", "MAMDA"), ("acct-mamda-nador", "MAMDA"),
])
def test_each_account_maps_to_its_own_entity_contracts_on_the_fixed_host(monkeypatch, account_id, entity):
    rec = Recorder()
    _install(monkeypatch, rec)
    opened = []
    result = asyncio.run(perform_notification_login(account_id, lambda: opened.append(1), 120.0))
    assert result == "MATERIAL"
    assert rec.launches == [False]                                  # visible, headed browser
    assert rec.contract_calls == [(DEFAULT_SINAUTO_HOST, entity)]   # entity derived locally
    assert rec.opened[0][0] == account_id and rec.opened[0][2] == DEFAULT_SINAUTO_HOST
    assert opened == [1]                                            # window-opened signal after the page opened
    assert rec.login_kwargs[0][1] == 120.0
    assert rec.login_closes == 1 and rec.browser_exits == 1


def test_profiles_come_from_the_canonical_four():
    assert profile_for_account("acct-mamda-nador").entity is PortalEntity.MAMDA
    assert profile_for_account("acct-mamda-nador").scope is PortalScope.NADOR
    assert profile_for_account("acct-mcma-oujda").is_mcma


@pytest.mark.parametrize("bad", ["acct-other", "", None, 5, "acct-mcma-oujda ", "ACCT-MCMA-OUJDA"])
def test_unknown_account_is_refused_before_any_browser(monkeypatch, bad):
    rec = Recorder()
    _install(monkeypatch, rec)
    with pytest.raises(UnknownNotificationAccount):
        asyncio.run(perform_notification_login(bad, lambda: None, 60.0))
    assert rec.launches == []


def test_page_open_failure_is_typed_and_closes_the_browser(monkeypatch):
    rec = Recorder()
    rec.open_raises = RuntimeError("playwright said: secret page text")
    _install(monkeypatch, rec)
    with pytest.raises(NotificationLoginFailed) as info:
        asyncio.run(perform_notification_login("acct-mcma-oujda", lambda: None, 60.0))
    assert info.value.reason == "LOGIN_PAGE_UNREACHABLE"
    assert "secret page text" not in str(info.value) and info.value.__cause__ is None
    assert rec.browser_exits == 1


def test_login_failure_propagates_and_closes_login_and_browser_once(monkeypatch):
    rec = Recorder()
    rec.login_behaviour = ValueError("x")
    _install(monkeypatch, rec)
    with pytest.raises(ValueError):
        asyncio.run(perform_notification_login("acct-mcma-oujda", lambda: None, 60.0))
    assert rec.login_closes == 1 and rec.browser_exits == 1


def test_cancellation_closes_login_and_browser_once(monkeypatch):
    rec = Recorder()
    rec.login_behaviour = "wait"
    _install(monkeypatch, rec)

    async def scenario():
        task = asyncio.ensure_future(perform_notification_login("acct-mamda-oujda", lambda: None, 60.0))
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert rec.login_closes == 1 and rec.browser_exits == 1


def test_function_signature_accepts_no_credentials_url_or_selector():
    import inspect

    params = set(inspect.signature(perform_notification_login).parameters)
    assert params == {"account_id", "on_window_opened", "timeout_seconds"}
