"""mcma.app.workstation_runner.notification_onboarding -- the dedicated
lifecycle that lets an employee (re)connect one of the four SERVER-OWNED
notification accounts from this Windows workstation.

What it does, per request the central server queued for THIS runner:
  claim -> ONE visible manual login (the employee types the real portal
  credentials and OTP straight into SinAuto; nothing here can see them) ->
  the in-memory Playwright storage state is uploaded ONCE over the already
  verified-HTTPS RegistryHttpClient -> everything is discarded.

What it deliberately is NOT:
  * not the saved-session store: the captured notification state is never
    written to WorkstationSessionStore / DPAPI / disk. It lives in memory
    from SessionMaterial.consume_for_handoff() until the upload returns;
  * not job dispatch: it never touches RUNNER_ACCOUNT_IDS, heartbeat
    readiness or form-filling eligibility -- MAMDA accounts are accepted
    HERE (notification onboarding only) and nowhere else;
  * not a URL/entity chooser: the server names only an account id. The
    injected `perform_login` maps it locally to the canonical profile and
    fixed reviewed auth contracts (see notification_login.py).

Dependency boundary (same discipline as job_worker.py, enforced by
test_import_isolation.py): no Playwright, no mcma.portal, no tkinter, no
SQLite/FastAPI. The login and the HTTP client are injected. UI is reached
only through the payload-free `on_event` callback, which the controller
forwards to thread-safe queues -- no Tk call is ever made from here.

Concurrency: one request at a time (the server enforces it too). Before it
even asks for work the lifecycle takes the shared BrowserOperationGate; if
the saved-session worker or the job worker owns a browser it simply does
not claim (the request stays queued server-side until its own expiry --
bounded, explicit, never two windows). Shutdown: `stop_event` is checked
before any browser opens, and while a login is open it cancels it; every
exit path (success, timeout, window closed, cancel, upload failure,
shutdown, a crash) closes the login exactly once via the injected
function's own context managers and releases the gate."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Protocol

from mcma.app.workstation_runner.browser_gate import OWNER_ONBOARDING, BrowserOperationGate
from mcma.app.workstation_runner.http_client import (
    RegistryAccountBusy, RegistryClaimNotFound, RegistrySessionRejected, RegistryUnauthorized,
)

_INITIAL_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 60.0
_DEFAULT_POLL_INTERVAL_SECONDS = 3.0
_DEFAULT_RENEW_INTERVAL_SECONDS = 15.0
_FIRST_WAITING_DELAY_SECONDS = 2.0
_DEFAULT_TICK_SECONDS = 0.2
_DEFAULT_LOGIN_TIMEOUT_SECONDS = 240.0
_MIN_LOGIN_TIMEOUT_SECONDS = 30.0
_MAX_LOGIN_TIMEOUT_SECONDS = 300.0
# Time arithmetic (see test_lease_arithmetic):
#   lease TTL (server)                      60 s
#   renew interval                          15 s
#   worst single HTTP call (http_client)    connect 5 + write 5 + read 10 + pool 5 = 25 s
#   => longest gap between two successful renews with a call in flight:
#      15 + 25 = 40 s < 60 s, and every call timeout (25 s) < 60 s.
# Calls are strictly serialized: the drive loop awaits each to_thread call,
# and the upload runs on the worker thread only after that loop has finished.
# The hard request deadline after a claim is 420 s; the login window is closed
# UPLOAD_RESERVE seconds before it (420 - 75 = 345, clamped to 300 s), and the
# upload retries are additionally gated on the lease and the hard deadline.
_LEASE_TTL_SECONDS = 60.0
_UPLOAD_RESERVE_SECONDS = 75.0

_LOGIN_REASONS = frozenset({"LOGIN_TIMED_OUT", "LOGIN_WINDOW_CLOSED", "LOGIN_PAGE_UNREACHABLE"})
_CANCEL_REASONS = frozenset({"CANCELLED", "RUNNER_SHUTDOWN"})


class OnboardingEvent(Enum):
    """Payload-free change signals. Never an account id, token or text."""

    CLAIMED = "CLAIMED"
    WINDOW_OPENED = "WINDOW_OPENED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    LEASE_LOST = "LEASE_LOST"
    CONNECTION_FAILED = "CONNECTION_FAILED"


class SessionMaterialLike(Protocol):
    def consume_for_handoff(self) -> dict: ...


# (account_id, on_window_opened, timeout_seconds) -> SessionMaterial. Owns the
# whole browser lifetime: it must close browser+context on EVERY exit path,
# including asyncio.CancelledError.
PerformLogin = Callable[[str, Callable[[], None], float], Awaitable[SessionMaterialLike]]


class ClaimedOnboardingLike(Protocol):
    request_id: str
    account_id: str
    generation: int
    claim_token: str
    expires_at: str
    server_time: str


@dataclass(frozen=True)
class _Outcome:
    kind: str                      # MATERIAL | FAIL | LOST
    material: Any = None
    reason: Optional[str] = None
    last_ok: float = 0.0           # clock() of the last successful renew


def _default_wait(event: threading.Event, timeout: float) -> bool:
    return event.wait(timeout)


class NotificationOnboardingLifecycle:
    def __init__(
        self,
        client,
        perform_login: PerformLogin,
        *,
        gate: BrowserOperationGate,
        is_ready: Callable[[], bool] = lambda: True,
        on_event: Callable[[OnboardingEvent], None] = lambda event: None,
        wait: Callable[[threading.Event, float], bool] = _default_wait,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        renew_interval_seconds: float = _DEFAULT_RENEW_INTERVAL_SECONDS,
        tick_seconds: float = _DEFAULT_TICK_SECONDS,
        max_renew_failures: int = 3,
        upload_attempts: int = 4,
        upload_retry_delay_seconds: float = 2.0,
    ) -> None:
        self._client = client
        self._clock = clock
        self._perform_login = perform_login
        self._gate = gate
        self._is_ready = is_ready
        self._on_event = on_event
        self._wait = wait
        self._poll_interval_seconds = poll_interval_seconds
        self._renew_interval_seconds = renew_interval_seconds
        self._tick_seconds = tick_seconds
        self._max_renew_failures = max_renew_failures
        self._upload_attempts = upload_attempts
        self._upload_retry_delay_seconds = upload_retry_delay_seconds
        self._backoff = _INITIAL_BACKOFF_SECONDS

    # ------------------------------------------------------------------ #

    def _emit(self, event: OnboardingEvent) -> None:
        try:
            self._on_event(event)
        except Exception:
            pass

    def run_forever(self, runner_secret: str, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                if not self._is_ready():
                    delay = self._poll_interval_seconds
                else:
                    delay = self._attempt(runner_secret, stop_event)
                if self._wait(stop_event, delay):
                    return
        finally:
            try:
                self._client.close()
            except Exception:
                pass

    def _attempt(self, runner_secret: str, stop_event: threading.Event) -> float:
        """One gated claim attempt. Returns how long to wait before the
        next. The gate is held ONLY across the claim and the work it yields
        -- never across a poll/backoff wait."""
        if not self._gate.try_acquire(OWNER_ONBOARDING):
            return self._poll_interval_seconds       # another browser owner is active: do not claim
        try:
            try:
                claimed = self._client.claim_notification_onboarding(runner_secret)
            except Exception:
                self._emit(OnboardingEvent.CONNECTION_FAILED)
                delay = self._backoff
                self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)
                return delay
            self._backoff = _INITIAL_BACKOFF_SECONDS
            if claimed is None:
                return self._poll_interval_seconds
            self._handle(runner_secret, claimed, stop_event)
            return 0.0
        finally:
            self._gate.release(OWNER_ONBOARDING)

    # ------------------------------------------------------------------ #

    def _handle(self, runner_secret: str, claimed: ClaimedOnboardingLike, stop_event: threading.Event) -> None:
        self._emit(OnboardingEvent.CLAIMED)
        if stop_event.is_set():
            # Shutdown landed between the claim and any browser launch: never
            # open one -- tell the server the request is cancelled.
            self._finish_with_reason(runner_secret, claimed, "RUNNER_SHUTDOWN")
            return
        claimed_at = self._clock()
        outcome = asyncio.run(self._drive(runner_secret, claimed, stop_event, claimed_at))
        if outcome.kind == "LOST":
            self._emit(OnboardingEvent.LEASE_LOST)
            return
        if outcome.kind == "FAIL":
            self._finish_with_reason(runner_secret, claimed, outcome.reason or "INTERNAL_ERROR")
            return
        self._upload(runner_secret, claimed, outcome.material, stop_event, outcome.last_ok,
                     self._hard_deadline(claimed, claimed_at))

    @staticmethod
    def _hard_deadline(claimed: ClaimedOnboardingLike, claimed_at: float) -> Optional[float]:
        try:
            span = (
                datetime.fromisoformat(claimed.expires_at) - datetime.fromisoformat(claimed.server_time)
            ).total_seconds()
        except (TypeError, ValueError):
            return None
        return claimed_at + span

    def _login_timeout(self, claimed: ClaimedOnboardingLike) -> float:
        """Server-clock-relative: the window is closed shortly before the
        request's own server-side expiry, so an expired request never keeps
        a window open. Falls back to a fixed bound on anything unparsable."""
        try:
            remaining = (
                datetime.fromisoformat(claimed.expires_at) - datetime.fromisoformat(claimed.server_time)
            ).total_seconds() - _UPLOAD_RESERVE_SECONDS
        except (TypeError, ValueError):
            return _DEFAULT_LOGIN_TIMEOUT_SECONDS
        return max(_MIN_LOGIN_TIMEOUT_SECONDS, min(_MAX_LOGIN_TIMEOUT_SECONDS, remaining))

    @staticmethod
    def _reason_for(exc: BaseException) -> str:
        reason = getattr(exc, "reason", None)
        return reason if isinstance(reason, str) and reason in _LOGIN_REASONS else "INTERNAL_ERROR"

    async def _drive(
        self, runner_secret: str, claimed: ClaimedOnboardingLike, stop_event: threading.Event, claimed_at: float,
    ) -> _Outcome:
        """Runs the login while renewing the lease FROM THE MOMENT OF THE
        CLAIM (phase OPENING_WINDOW while Chromium/the login page start, then
        WINDOW_OPENED, then WAITING_FOR_LOGIN). ALWAYS returns with the login
        task finished (cancelled and awaited if need be), so the injected
        perform_login's own cleanup has run before anything else happens.
        Anything it raises as a BaseException propagates after that cleanup."""
        opened = threading.Event()
        login_task = asyncio.ensure_future(
            self._perform_login(claimed.account_id, opened.set, self._login_timeout(claimed))
        )
        stop_reason: Optional[str] = None
        lost = False
        phase_sent: Optional[str] = None
        last_renew: Optional[float] = None
        last_ok = claimed_at
        failures = 0
        announced_open = False
        try:
            while not login_task.done():
                if stop_event.is_set():
                    stop_reason = "RUNNER_SHUTDOWN"
                    break
                is_open = opened.is_set()
                if is_open and not announced_open:
                    announced_open = True
                    self._emit(OnboardingEvent.WINDOW_OPENED)
                now = self._clock()
                if now - last_ok >= _LEASE_TTL_SECONDS:
                    lost = True                    # the server lease has lapsed by our own clock
                    break
                phase = (
                    "OPENING_WINDOW" if not is_open
                    else "WINDOW_OPENED" if phase_sent in (None, "OPENING_WINDOW") else "WAITING_FOR_LOGIN"
                )
                if last_renew is None or phase_sent is None:
                    due = True
                elif is_open and phase_sent == "OPENING_WINDOW":
                    due = True
                elif phase_sent == "WINDOW_OPENED":
                    due = now - last_renew >= min(_FIRST_WAITING_DELAY_SECONDS, self._renew_interval_seconds)
                else:
                    due = now - last_renew >= self._renew_interval_seconds
                if due:
                    try:
                        result = await asyncio.to_thread(
                            self._client.renew_notification_onboarding, runner_secret,
                            request_id=claimed.request_id, claim_token=claimed.claim_token,
                            generation=claimed.generation, phase=phase,
                        )
                    except (RegistryClaimNotFound, RegistryUnauthorized):
                        lost = True                # fenced: this request is no longer ours
                        break
                    except Exception:
                        failures += 1
                        last_renew = self._clock()
                        if failures >= self._max_renew_failures:
                            self._emit(OnboardingEvent.CONNECTION_FAILED)
                            lost = True
                            break
                    else:
                        failures = 0
                        phase_sent = phase
                        last_renew = last_ok = self._clock()
                        if result.cancel_requested:
                            stop_reason = "CANCELLED"
                            break
                await asyncio.wait({login_task}, timeout=self._tick_seconds)
        except BaseException:
            await self._cancel_and_await(login_task)
            raise

        if lost or stop_reason is not None:
            await self._cancel_and_await(login_task)
            return _Outcome("LOST") if lost else _Outcome("FAIL", reason=stop_reason)
        if login_task.cancelled():
            return _Outcome("FAIL", reason="INTERNAL_ERROR")
        exc = login_task.exception()
        if exc is not None:
            return _Outcome("FAIL", reason=self._reason_for(exc))
        return _Outcome("MATERIAL", material=login_task.result(), last_ok=last_ok)

    @staticmethod
    async def _cancel_and_await(task: "asyncio.Future") -> None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    # ------------------------------------------------------------------ #

    def _finish_with_reason(self, runner_secret: str, claimed: ClaimedOnboardingLike, reason: str) -> None:
        try:
            self._client.fail_notification_onboarding(
                runner_secret, request_id=claimed.request_id, claim_token=claimed.claim_token,
                generation=claimed.generation, reason_code=reason,
            )
        except Exception:
            pass       # best effort: the server's own lease expiry fences the request either way
        self._emit(OnboardingEvent.CANCELLED if reason in _CANCEL_REASONS else OnboardingEvent.FAILED)

    def _upload(
        self, runner_secret: str, claimed: ClaimedOnboardingLike, material: SessionMaterialLike,
        stop_event: threading.Event, last_ok: float, deadline: Optional[float],
    ) -> None:
        """Uploads once while keeping the lease alive: a renew precedes the
        first complete (it also reveals a cancellation, in which case
        complete() is NEVER called) and another whenever renew_interval has
        elapsed before a retry. Retrying stops as soon as the lease or the hard
        deadline can no longer allow success (<= semantics, like the server)."""
        storage_state: Optional[dict] = None
        try:
            try:
                storage_state = material.consume_for_handoff()       # single consumption
            except Exception:
                self._finish_with_reason(runner_secret, claimed, "INTERNAL_ERROR")
                return
            finally:
                del material
            for attempt in range(self._upload_attempts):
                if attempt > 0:
                    if self._wait(stop_event, self._upload_retry_delay_seconds):
                        break
                if stop_event.is_set():
                    break
                now = self._clock()
                if (deadline is not None and now >= deadline) or now - last_ok >= _LEASE_TTL_SECONDS:
                    self._emit(OnboardingEvent.LEASE_LOST)
                    return
                if attempt == 0 or now - last_ok >= self._renew_interval_seconds:
                    try:
                        renewed = self._client.renew_notification_onboarding(
                            runner_secret, request_id=claimed.request_id, claim_token=claimed.claim_token,
                            generation=claimed.generation, phase="WAITING_FOR_LOGIN",
                        )
                    except (RegistryClaimNotFound, RegistryUnauthorized):
                        self._emit(OnboardingEvent.LEASE_LOST)
                        return
                    except Exception:
                        continue               # transient: the lease/deadline guards above bound the retrying
                    last_ok = self._clock()
                    if renewed.cancel_requested:
                        self._finish_with_reason(runner_secret, claimed, "CANCELLED")
                        return
                try:
                    self._client.complete_notification_onboarding(
                        runner_secret, request_id=claimed.request_id, claim_token=claimed.claim_token,
                        generation=claimed.generation, storage_state=storage_state,
                    )
                except RegistrySessionRejected:
                    self._emit(OnboardingEvent.FAILED)             # the server already closed the request
                    return
                except (RegistryClaimNotFound, RegistryUnauthorized):
                    self._emit(OnboardingEvent.LEASE_LOST)
                    return
                except RegistryAccountBusy:
                    continue
                except Exception:
                    # Includes a lost response: the server-side /complete is
                    # idempotent for the same claim, so a retry is safe.
                    continue
                self._emit(OnboardingEvent.SUCCEEDED)
                return
            if stop_event.is_set():
                self._finish_with_reason(runner_secret, claimed, "RUNNER_SHUTDOWN")
            else:
                self._finish_with_reason(runner_secret, claimed, "UPLOAD_FAILED")
        finally:
            storage_state = None           # discard the in-memory session material
