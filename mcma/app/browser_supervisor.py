"""
mcma.app.browser_supervisor -- the readiness contract for the process's
ONE Playwright browser.

The browser was published by assigning into a plain dict from inside the
poll-loop task, after that task had already started and after the ASGI
lifespan had already yielded. Three things followed from that, all of
them observed on a real Windows install:

  * The dashboard served requests before the browser existed, so a login
    click raced startup and failed.
  * The failure surfaced as RuntimeError("no browser is available yet"),
    which the API flattened into a portal-login 409 -- telling the
    employee they had not completed a sign-in they were never shown.
  * If launch_browser() itself failed, the task ended and nothing
    observed it. Uvicorn kept serving a dashboard whose login buttons
    were permanently broken, with no error anywhere.

This module replaces that dict with a state machine that can be waited on
and that cannot fail silently:

    STARTING -> READY        the browser launched; get() returns it
    STARTING -> FAILED       launch failed; get() raises the real cause
    READY    -> FAILED       the loop died later; get() raises again

Startup awaits READY before the application accepts traffic, so the race
cannot happen rather than being reported when it does. A launch failure
becomes a startup failure. There is exactly one browser: login,
notification reads, the dossier runner and the human handoff all take it
from here.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class BrowserNotReady(Exception):
    """The browser is still starting. Distinct from BrowserUnavailable
    because it is transient -- the caller may simply be early -- and it
    must never be reported as a failed portal login."""


class BrowserUnavailable(Exception):
    """The browser could not be started, or the task owning it has died.
    Carries the original cause so the real reason is never lost."""


class BrowserSupervisor:
    def __init__(self) -> None:
        self._browser = None
        self._failure: BaseException | None = None
        self._ready = asyncio.Event()
        self._shutting_down = False

    # -- owner side ------------------------------------------------------

    def mark_ready(self, browser) -> None:
        self._browser = browser
        self._failure = None
        self._ready.set()

    def mark_failed(self, cause: BaseException) -> None:
        """Recorded whether the failure happens before or after READY: a
        browser that dies at hour six leaves the same broken buttons as
        one that never started, and the dashboard must be able to say so
        either way."""
        self._browser = None
        self._failure = cause
        logger.error("shared browser unavailable: %s: %s", type(cause).__name__, cause)
        # Wake anything waiting; waiters re-check state rather than
        # assuming the event means success.
        self._ready.set()

    def begin_shutdown(self) -> None:
        """Declares that what follows is a deliberate stop.

        Shutdown intent is recorded EXPLICITLY rather than inferred from
        whatever exception the teardown happens to produce. On Ctrl+C the
        Playwright driver connection is often already gone by the time
        browser.close() runs, so closing raises -- and an exception raised
        in a `finally` replaces the CancelledError that got us there. The
        task then looks like it failed rather than like it was cancelled,
        and a clean shutdown was being reported as a browser failure,
        traceback and all.

        Guessing from the exception would mean pattern-matching driver
        messages to decide whether a failure was real. The caller knows;
        it says so."""
        self._shutting_down = True

    # -- consumer side ---------------------------------------------------

    def get(self):
        """The single accessor. Never returns None: callers get a browser
        or a typed exception explaining which of the two situations they
        are in."""
        if self._failure is not None:
            raise BrowserUnavailable(
                f"the shared browser is not available ({type(self._failure).__name__})"
            ) from self._failure
        if self._browser is None:
            raise BrowserNotReady("the shared browser is still starting")
        return self._browser

    async def wait_until_ready(self, timeout: float) -> None:
        """Awaited by startup before the application serves anything.
        Raises BrowserUnavailable if the launch failed or did not complete
        in time -- so a browser problem stops the application instead of
        producing a healthy-looking dashboard nobody can log in from."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except asyncio.TimeoutError as exc:
            raise BrowserUnavailable(
                f"the browser did not start within {timeout:.0f}s"
            ) from exc
        if self._failure is not None:
            raise BrowserUnavailable(
                f"the browser failed to start ({type(self._failure).__name__})"
            ) from self._failure

    def watch(self, task: "asyncio.Task") -> None:
        """Attaches a done-callback so the task owning the browser can
        never end unobserved. Without this, an exception inside the task
        is stored on a Task object nobody awaits and is reported, if at
        all, only as a warning when the loop shuts down."""

        def _on_done(finished: "asyncio.Task") -> None:
            if finished.cancelled() or self._shutting_down:
                # Deliberate shutdown. Note this covers a task that ended
                # with an ordinary exception DURING shutdown too, which is
                # exactly the Ctrl+C case: cancellation arrives, teardown
                # fails to close an already-disconnected browser, and the
                # task's final exception is no longer CancelledError.
                return
            exc = finished.exception()
            if exc is not None:
                self.mark_failed(exc)
            else:
                self.mark_failed(RuntimeError("the browser task ended unexpectedly"))

        task.add_done_callback(_on_done)
