"""The shared browser's readiness contract.

The bug these pin: the browser was published by assigning into a plain
dict from inside the poll-loop task, after the ASGI lifespan had already
yielded. The dashboard therefore served requests before the browser
existed, a login click raced startup, and the resulting
RuntimeError("no browser is available yet") was flattened into a
portal-login 409 -- telling the employee they had failed a sign-in they
were never shown. Worse, a launch failure ended the task with nobody
observing it, leaving a healthy-looking dashboard whose login buttons
could never work.
"""

import asyncio

import pytest

from api_test_support import (
    MAMDA_OUJDA,
    NADOR,
    OUJDA,
    conn,  # noqa: F401
    create_user,
    csrf_headers,
    db_path,  # noqa: F401
    grant_access,
    login_client,
)
from mcma.app.browser_supervisor import (
    BrowserNotReady,
    BrowserSupervisor,
    BrowserUnavailable,
)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# The supervisor's own contract
# --------------------------------------------------------------------- #


def test_before_launch_the_browser_is_not_ready_not_missing():
    """Transient, and distinguishable from a failure -- the caller may
    simply be early."""
    supervisor = BrowserSupervisor()
    with pytest.raises(BrowserNotReady):
        supervisor.get()


def test_after_launch_the_browser_is_returned():
    supervisor = BrowserSupervisor()
    browser = object()
    supervisor.mark_ready(browser)
    assert supervisor.get() is browser


def test_a_launch_failure_is_reported_with_its_real_cause():
    supervisor = BrowserSupervisor()
    supervisor.mark_failed(FileNotFoundError("chromium is not installed"))
    with pytest.raises(BrowserUnavailable) as raised:
        supervisor.get()
    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_a_browser_that_dies_after_starting_stops_being_reported_as_ready():
    """A browser that dies at hour six leaves the same broken buttons as
    one that never started."""
    supervisor = BrowserSupervisor()
    supervisor.mark_ready(object())
    supervisor.mark_failed(RuntimeError("driver exited"))
    with pytest.raises(BrowserUnavailable):
        supervisor.get()


def test_startup_waits_for_the_browser_before_continuing():
    supervisor = BrowserSupervisor()

    async def _scenario():
        async def _launch_later():
            await asyncio.sleep(0.05)
            supervisor.mark_ready(object())

        asyncio.create_task(_launch_later())
        await supervisor.wait_until_ready(timeout=2)
        # Returned only once the browser genuinely exists.
        return supervisor.get()

    assert _run(_scenario()) is not None


def test_startup_fails_when_the_browser_cannot_launch():
    """Requirement: a Playwright failure becomes an explicit application
    failure, not a healthy dashboard with dead buttons."""
    supervisor = BrowserSupervisor()

    async def _scenario():
        supervisor.mark_failed(RuntimeError("playwright driver missing"))
        await supervisor.wait_until_ready(timeout=2)

    with pytest.raises(BrowserUnavailable):
        _run(_scenario())


def test_startup_fails_rather_than_hanging_forever():
    supervisor = BrowserSupervisor()
    with pytest.raises(BrowserUnavailable):
        _run(supervisor.wait_until_ready(timeout=0.05))


def test_a_dying_task_is_observed_even_if_nobody_awaits_it():
    """Without the done-callback the exception sits on a Task object
    nobody awaits and is reported, if at all, only at loop shutdown."""
    supervisor = BrowserSupervisor()

    async def _scenario():
        async def _fails():
            raise RuntimeError("browser task exploded")

        task = asyncio.create_task(_fails())
        supervisor.watch(task)
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    _run(_scenario())
    with pytest.raises(BrowserUnavailable):
        supervisor.get()


def test_a_cancelled_task_is_not_treated_as_a_failure():
    """Shutdown is deliberate, not a fault."""
    supervisor = BrowserSupervisor()
    browser = object()

    async def _scenario():
        async def _forever():
            await asyncio.sleep(3600)

        task = asyncio.create_task(_forever())
        supervisor.mark_ready(browser)
        supervisor.watch(task)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    _run(_scenario())
    assert supervisor.get() is browser


# --------------------------------------------------------------------- #
# What the employee is told
# --------------------------------------------------------------------- #


def _app_with_supervisor(conn, supervisor):
    from fastapi.testclient import TestClient

    from mcma.app.api.app import create_api_app
    from mcma.app.auth.provider import LocalUserAuthProvider
    from mcma.app.auth.sessions import SessionStore
    from mcma.execution.inputs import TestOnlyPlaintextEncryptor

    opened = []

    async def _opener(account_id):
        browser = supervisor.get()      # raises the typed errors
        opened.append((account_id, browser))
        return "session-1"

    app = create_api_app(
        conn,
        auth_provider=LocalUserAuthProvider(conn),
        session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(),
        secure_cookies=False,
        portal_login_opener=_opener,
    )
    return TestClient(app, client=("127.0.0.1", 12345)), opened


def _signed_in(conn, client, *accounts):
    user_id = create_user(conn, "alice", "pw12345", "operator")
    for account_id in accounts:
        grant_access(conn, user_id, account_id)
    return login_client(client, "alice", "pw12345")


def test_a_login_while_starting_says_so_instead_of_blaming_the_employee(conn):
    supervisor = BrowserSupervisor()          # still starting
    client, _ = _app_with_supervisor(conn, supervisor)
    csrf = _signed_in(conn, client, OUJDA)

    response = client.post(f"/accounts/{OUJDA}/login", headers=csrf_headers(csrf))
    assert response.status_code == 503
    assert response.json()["error"] == "BROWSER_NOT_READY"
    # Specifically NOT the old behaviour.
    assert "PORTAL_LOGIN_FAILED" not in response.text


def test_a_login_with_a_dead_browser_says_the_browser_is_unavailable(conn):
    supervisor = BrowserSupervisor()
    supervisor.mark_failed(RuntimeError("driver exited"))
    client, _ = _app_with_supervisor(conn, supervisor)
    csrf = _signed_in(conn, client, OUJDA)

    response = client.post(f"/accounts/{OUJDA}/login", headers=csrf_headers(csrf))
    assert response.status_code == 503
    assert response.json()["error"] == "BROWSER_UNAVAILABLE"


def test_all_four_accounts_use_the_same_browser_instance(conn):
    """One browser for login, notifications, the runner and the handoff --
    never one per account."""
    supervisor = BrowserSupervisor()
    browser = object()
    supervisor.mark_ready(browser)
    client, opened = _app_with_supervisor(conn, supervisor)
    csrf = _signed_in(conn, client, OUJDA, NADOR, MAMDA_OUJDA)

    for account_id in (OUJDA, NADOR, MAMDA_OUJDA):
        assert client.post(f"/accounts/{account_id}/login",
                           headers=csrf_headers(csrf)).status_code == 200

    assert [account for account, _ in opened] == [OUJDA, NADOR, MAMDA_OUJDA]
    assert {id(b) for _, b in opened} == {id(browser)}


def test_readiness_never_widens_account_access(conn):
    """A ready browser is not authorisation: an account this user cannot
    reach is still refused, and no window is opened for it."""
    supervisor = BrowserSupervisor()
    supervisor.mark_ready(object())
    client, opened = _app_with_supervisor(conn, supervisor)
    csrf = _signed_in(conn, client, OUJDA)

    denied = client.post(f"/accounts/{NADOR}/login", headers=csrf_headers(csrf))
    assert denied.status_code in (403, 404)
    assert opened == []


def test_entity_routing_and_final_endpoint_blocks_are_unaffected():
    """This change touches lifecycle only -- the guards must be exactly
    where they were."""
    from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS, is_permanently_blocked
    from mcma.portal.sinauto_contracts import auth_contracts, portal_base_for

    assert portal_base_for("MCMA") == "/SinAuto_MCMA"
    assert portal_base_for("MAMDA") == "/SinAuto_MAMDA"
    assert auth_contracts(entity="MAMDA")[0].route == "/SinAuto_MAMDA"
    for blocked in PERMANENTLY_BLOCKED_ENDPOINTS:
        assert is_permanently_blocked(f"/SinAuto_MCMA/expertise/{blocked}")


# --------------------------------------------------------------------- #
# Shutdown
# --------------------------------------------------------------------- #


def test_shutdown_is_not_a_failure_even_if_closing_the_browser_errors():
    """The Ctrl+C case. Cancellation arrives, teardown cannot close an
    already-disconnected Playwright driver, and the exception raised in
    `finally` REPLACES the CancelledError -- so the task no longer looks
    cancelled. Shutdown intent is declared explicitly so that is not read
    as a browser failure."""
    supervisor = BrowserSupervisor()
    supervisor.mark_ready(object())

    async def _scenario():
        async def _loop():
            try:
                await asyncio.sleep(3600)
            finally:
                # Exactly what Playwright does on Ctrl+C.
                raise RuntimeError("Browser.close: Connection closed while reading from the driver")

        task = asyncio.create_task(_loop())
        supervisor.watch(task)
        await asyncio.sleep(0)

        supervisor.begin_shutdown()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    _run(_scenario())
    # No transition to FAILED: get() still answers as it did before.
    assert supervisor._failure is None


def test_a_browser_dying_during_normal_runtime_is_still_a_failure():
    """The distinction that matters: the same exception, without a
    declared shutdown, must still produce BROWSER_UNAVAILABLE."""
    supervisor = BrowserSupervisor()
    supervisor.mark_ready(object())

    async def _scenario():
        async def _dies():
            raise RuntimeError("Browser.close: Connection closed while reading from the driver")

        task = asyncio.create_task(_dies())
        supervisor.watch(task)
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    _run(_scenario())
    with pytest.raises(BrowserUnavailable):
        supervisor.get()


def test_shutdown_intent_does_not_hide_an_earlier_runtime_failure():
    """A failure recorded while running must survive a later shutdown --
    stopping the application does not retroactively make it healthy."""
    supervisor = BrowserSupervisor()
    supervisor.mark_ready(object())
    supervisor.mark_failed(RuntimeError("driver exited mid-run"))
    supervisor.begin_shutdown()
    with pytest.raises(BrowserUnavailable):
        supervisor.get()


def test_startup_failure_still_fails_startup_after_the_shutdown_change():
    """Regression guard on the previous commit: declaring shutdown intent
    must not weaken the startup readiness contract."""
    supervisor = BrowserSupervisor()
    supervisor.mark_failed(RuntimeError("playwright driver missing"))
    with pytest.raises(BrowserUnavailable):
        _run(supervisor.wait_until_ready(timeout=1))


@pytest.mark.skip(reason="REAL_LOGIN_OTP_PENDING_ONSITE: needs the company network and a real OTP")
def test_REAL_LOGIN_OTP_PENDING_ONSITE():
    """Deferred onsite verification, recorded here so it is visible in
    every test run rather than living only in a chat message.

    For EACH of the four accounts (MCMA Oujda, MCMA Nador, MAMDA Oujda,
    MAMDA Nador), onsite, verify:

      1. the login window opens on the account's OWN application --
         MCMA -> /SinAuto_MCMA/, MAMDA -> /SinAuto_MAMDA/
      2. a valid username and password are accepted
      3. the SMS OTP completes the sign-in
      4. the logged-in markers are positively detected -- if a correct
         sign-in instead runs to LOGIN_TIMED_OUT, LOGGED_IN_MARKERS is
         wrong for the live portal and needs the real post-login page
      5. the session is stored under that EXACT account, and no other
      6. the account card turns Connecté

    Cannot be automated here: it needs the company network, real
    credentials and a phone."""
