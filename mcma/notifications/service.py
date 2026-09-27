"""
mcma.notifications.service -- the notification polling service, extracted
from the local composition root so the Windows application and the central
Ubuntu server run the SAME code.

It owns exactly two things:

  * ONE long-lived HEADLESS browser, used only for notification reads. It
    is never a form-filling browser and it never falls back to one -- a
    silent fallback would reintroduce the flashing windows the separate
    browser exists to remove (and on a server there is no display at all).
  * The poll schedule: a pass over every active account roughly every
    `notification_poll_interval_seconds`.

It deliberately owns NO job processing, no review registry and no mock
portal. The composition roots decide what else runs beside it.

Failure model. A browser that cannot start is not fatal to the process --
the service reports DEGRADED, skips poll passes with a log line, and
retries the launch at the next due pass, so a transient failure heals
without a restart. Manual refresh keeps failing visibly meanwhile
(mcma.app.browser_supervisor.get_notification raises), which is the
intended behaviour: no silent fallback.

Runtime disconnection. A launched Chromium can die later (OOM kill, crash,
driver exit). The stored handle is then a corpse that every poll and manual
refresh would fail on, while health kept saying READY. So liveness
(`browser.is_connected()`) is checked on every tick and every state read:
a dead browser is dropped and its context closed, the service reports
DEGRADED at once, and the browser is relaunched after a short retry delay
(or at the next due pass). Ordinary account/session polling failures never
touch this -- only the browser's own connection does.

State is exposed as a plain enum for health reporting. Nothing here places
an exception message, session material or portal text in that state.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import Any, Callable, Optional

from mcma.core.config import Settings
from mcma.notifications.poller import poll_all_accounts
from mcma.portal.browser import launch_browser

logger = logging.getLogger(__name__)


class NotificationServiceState(str, enum.Enum):
    STARTING = "starting"     # constructed; browser launch not finished
    READY = "ready"           # headless browser up; polling active
    DEGRADED = "degraded"     # browser could not start; polling suspended
    STOPPING = "stopping"     # shutdown begun
    STOPPED = "stopped"       # browser closed


# How soon after a failed or lost browser a relaunch is attempted, at most.
# Independent of the (much longer) notification interval so that a crash is
# healed in well under a poll period, and of notifications_enabled so that a
# manual-refresh-only install heals too.
BROWSER_RETRY_SECONDS = 30.0


def _is_connected(browser) -> bool:
    check = getattr(browser, "is_connected", None)
    if check is None:
        return True  # a handle that cannot say is presumed alive
    try:
        return bool(check())
    except Exception:
        return False


def _default_launcher():
    # Looked up at call time so the module attribute can be replaced.
    # headless=True is hard-coded, not a parameter: this service has no
    # legitimate reason to ever show a window.
    return launch_browser(headless=True)


class NotificationService:
    def __init__(
        self,
        conn,
        settings: Settings,
        *,
        crypto_backend,
        session_observer=None,
        browser_launcher: Optional[Callable[[], Any]] = None,
        on_browser_ready: Optional[Callable[[Any], None]] = None,
        on_browser_lost: Optional[Callable[[], None]] = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._crypto_backend = crypto_backend
        self._session_observer = session_observer
        self._launcher = browser_launcher or _default_launcher
        self._on_browser_ready = on_browser_ready
        self._on_browser_lost = on_browser_lost
        self._since_attempt = 0.0
        self._context = None
        self._browser = None
        self._state = NotificationServiceState.STARTING
        # Start "due" so the first pass polls immediately, as the original
        # inline loop did.
        self._since_poll = settings.notification_poll_interval_seconds

    @property
    def state(self) -> NotificationServiceState:
        # A browser that died since the last tick is reported DEGRADED
        # immediately, without waiting for the next reap.
        if (self._state is NotificationServiceState.READY
                and self._browser is not None and not _is_connected(self._browser)):
            return NotificationServiceState.DEGRADED
        return self._state

    @property
    def browser(self):
        """The live browser, or None. Never a known-dead one."""
        if self._browser is not None and not _is_connected(self._browser):
            return None
        return self._browser

    async def _reap_dead_browser(self) -> None:
        if self._browser is None or _is_connected(self._browser):
            return
        logger.warning("the headless notification browser disconnected; it will be relaunched")
        context, self._context, self._browser = self._context, None, None
        self._state = NotificationServiceState.DEGRADED
        if self._on_browser_lost is not None:
            self._on_browser_lost()
        if context is not None:
            try:
                await context.__aexit__(None, None, None)
            except Exception:
                logger.info("the disconnected notification browser was already gone", exc_info=True)

    async def start(self) -> None:
        """Launches the headless browser. Never raises for a launch
        failure: it lands the service in DEGRADED instead."""
        if self._browser is not None or self._state in (
            NotificationServiceState.STOPPING, NotificationServiceState.STOPPED,
        ):
            return
        self._since_attempt = 0.0
        context = None
        try:
            context = self._launcher()
            browser = await context.__aenter__()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._context = None
            self._state = NotificationServiceState.DEGRADED
            logger.warning(
                "the headless notification browser could not start; "
                "notification polling is unavailable until it does",
                exc_info=True,
            )
            return
        self._context = context
        self._browser = browser
        self._state = NotificationServiceState.READY
        if self._on_browser_ready is not None:
            self._on_browser_ready(browser)

    async def poll_if_due(self, elapsed_seconds: float) -> None:
        """Advances the schedule by `elapsed_seconds` and, when a pass is
        due, runs it. Exceptions from a pass propagate to the caller,
        which owns the "keep looping" policy."""
        self._since_poll += elapsed_seconds
        self._since_attempt += elapsed_seconds
        await self._reap_dead_browser()
        if (self._browser is None and self._since_attempt >= BROWSER_RETRY_SECONDS
                and self._state is not NotificationServiceState.STARTING):
            await self.start()
        if not (self._settings.notifications_enabled
                and self._since_poll >= self._settings.notification_poll_interval_seconds):
            return
        self._since_poll = 0
        if self._browser is None:
            logger.warning(
                "skipping the notification poll pass: the headless "
                "notification browser is not available"
            )
            return
        await poll_all_accounts(
            self._conn,
            self._browser,
            self._settings.notification_category_codes,
            instance_id=self._settings.instance_id,
            allowed_host=self._settings.portal_host,
            vault_dir=self._settings.vault_dir,
            crypto_backend=self._crypto_backend,
            session_observer=self._session_observer,
        )

    async def run(self, tick_seconds: float) -> None:
        """The central server's loop: start, then poll forever until
        cancelled. A failing pass is logged and never ends the loop."""
        await self.start()
        while True:
            try:
                await self.poll_if_due(tick_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("notification poll pass failed")
            await asyncio.sleep(tick_seconds)

    async def stop(self) -> None:
        self._state = NotificationServiceState.STOPPING
        context, self._context, self._browser = self._context, None, None
        if context is not None:
            try:
                await context.__aexit__(None, None, None)
            except Exception:
                logger.info("the notification browser was already gone at shutdown", exc_info=True)
        self._state = NotificationServiceState.STOPPED
