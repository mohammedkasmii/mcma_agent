"""mcma.app.workstation_runner.heartbeat -- the heartbeat state machine.
Single-threaded by construction (one HeartbeatWorker thread runs one
sequential loop), so "only one heartbeat in flight" is structural, not a
lock. Uses a monotonic wait function (default: threading.Event.wait, which
is itself monotonic-clock-backed) so scheduling never depends on wall-clock
time; the wait function is injectable for deterministic tests."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable

from mcma.app.workstation_runner.http_client import (
    RegistryAccountNotAllowed, RegistryConnectionError, RegistryProtocolError, RegistryUnauthorized,
)
from mcma.app.workstation_runner.protocol import (
    MAX_HEARTBEAT_INTERVAL_SECONDS, MIN_HEARTBEAT_INTERVAL_SECONDS,
)

_INITIAL_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 60.0
_DEFAULT_INTERVAL_SECONDS = 10.0


class LifecycleEvent(Enum):
    CONNECTED = "CONNECTED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"


def _default_wait(event: threading.Event, timeout: float) -> bool:
    return event.wait(timeout)


def _bounded_interval(seconds: object) -> float:
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) \
            and MIN_HEARTBEAT_INTERVAL_SECONDS <= seconds <= MAX_HEARTBEAT_INTERVAL_SECONDS:
        return float(seconds)
    return _DEFAULT_INTERVAL_SECONDS


class HeartbeatLifecycle:
    """Owns the heartbeat network loop only. It does NOT own identity
    deletion: a 401 (UNAUTHORIZED) is reported to `on_event` and the loop
    ends there -- the CONTROLLER is the sole owner of clearing the local
    identity (see RunnerController._handle_lifecycle_event), so that
    decision and its failure handling live in exactly one place, not two.

    `sessions_provider` is called FRESH on every single iteration -- never
    cached, never reused across calls -- so a heartbeat always reports the
    browser-session state exactly as WorkstationSessionManager sees it at
    that instant (RELEASE BLOCKER 3: resending a locally-cached
    allowed_account_ids as if it were an authorization claim is exactly
    the bug this must never reintroduce). `on_allowed_accounts` is called
    with the server's own `allowed_account_ids` after EVERY successful
    heartbeat (including the ACCOUNT_NOT_ALLOWED retry below), BEFORE the
    next iteration's sessions_provider() call -- this is what lets the
    controller reconcile WorkstationSessionManager in time for the next
    heartbeat to already reflect it."""

    def __init__(
        self, client, on_event: Callable[[LifecycleEvent], None], *,
        wait: Callable[[threading.Event, float], bool] = _default_wait,
        sessions_provider: Callable[[], tuple] = lambda: (),
        on_allowed_accounts: Callable[[tuple], None] = lambda allowed_account_ids: None,
    ) -> None:
        self._client = client
        self._on_event = on_event
        self._wait = wait
        self._sessions_provider = sessions_provider
        self._on_allowed_accounts = on_allowed_accounts

    def run_once_loop(self, runner_secret: str, stop_event: threading.Event) -> None:
        try:
            backoff = _INITIAL_BACKOFF_SECONDS
            while not stop_event.is_set():
                sessions = self._sessions_provider()
                try:
                    result = self._client.heartbeat(runner_secret, sessions=sessions)
                except RegistryAccountNotAllowed:
                    # An administrator removed one of these accounts before
                    # this runner learned about it. Exactly ONE immediate
                    # retry with an empty sessions claim -- never the
                    # response body, never an unbounded loop -- then the
                    # retry's own outcome (success or failure) is handled
                    # exactly like any other heartbeat result below.
                    try:
                        result = self._client.heartbeat(runner_secret, sessions=())
                    except RegistryUnauthorized:
                        self._on_event(LifecycleEvent.UNAUTHORIZED)
                        return
                    except (RegistryConnectionError, RegistryProtocolError):
                        self._on_event(LifecycleEvent.CONNECTION_FAILED)
                        if self._wait(stop_event, backoff):
                            return
                        backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                        continue
                except RegistryUnauthorized:
                    self._on_event(LifecycleEvent.UNAUTHORIZED)
                    return
                except (RegistryConnectionError, RegistryProtocolError):
                    self._on_event(LifecycleEvent.CONNECTION_FAILED)
                    if self._wait(stop_event, backoff):
                        return
                    backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                    continue
                backoff = _INITIAL_BACKOFF_SECONDS
                self._on_allowed_accounts(result.allowed_account_ids)
                self._on_event(LifecycleEvent.CONNECTED)
                if self._wait(stop_event, _bounded_interval(result.heartbeat_interval_seconds)):
                    return
        finally:
            # Close on EVERY exit path -- normal stop, unauthorized, or any
            # other return -- never leaked to a re-pair or a long-running
            # session that never reconnects.
            try:
                self._client.close()
            except Exception:
                pass


class HeartbeatWorker:
    """Thread wrapper: one non-daemon thread running one HeartbeatLifecycle
    loop, stoppable with a bounded join."""

    def __init__(self, lifecycle, runner_secret: str) -> None:
        self._lifecycle = lifecycle
        self._runner_secret = runner_secret
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # Assign self._thread only AFTER Thread.start() has returned, never
        # before: stop()'s "if self._thread is not None: self._thread.join()"
        # guard must never be able to see a Thread object that exists but
        # was never actually started (Thread.join() raises RuntimeError on
        # one). A concurrent stop() racing this method either sees
        # self._thread still None (safe no-op join, the stop_event it sets
        # still stops the thread promptly once it runs) or sees a thread
        # that is guaranteed already started.
        thread = threading.Thread(
            target=self._lifecycle.run_once_loop,
            args=(self._runner_secret, self._stop_event),
            name="mcma-runner-heartbeat",
            daemon=False,
        )
        thread.start()
        self._thread = thread

    def stop(self, timeout: float) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
