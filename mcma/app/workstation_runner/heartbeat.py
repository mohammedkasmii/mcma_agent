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
    RegistryConnectionError, RegistryProtocolError, RegistryUnauthorized,
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
    decision and its failure handling live in exactly one place, not two."""

    def __init__(self, client, on_event: Callable[[LifecycleEvent], None], *, wait: Callable[[threading.Event, float], bool] = _default_wait) -> None:
        self._client = client
        self._on_event = on_event
        self._wait = wait

    def run_once_loop(self, runner_secret: str, stop_event: threading.Event, *, sessions: tuple = ()) -> None:
        # `sessions` is real, currently-configured browser-session state --
        # see RegistryHttpClient.heartbeat's docstring. Phase 1B-A has none,
        # so this is always (); a later phase reporting actual sessions
        # would recompute this per iteration rather than resending a
        # locally-cached authorization claim (RELEASE BLOCKER 3).
        try:
            backoff = _INITIAL_BACKOFF_SECONDS
            while not stop_event.is_set():
                try:
                    result = self._client.heartbeat(runner_secret, sessions=sessions)
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

    def __init__(self, lifecycle, runner_secret: str, *, sessions: tuple = ()) -> None:
        self._lifecycle = lifecycle
        self._runner_secret = runner_secret
        self._sessions = sessions
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
            kwargs={"sessions": self._sessions},
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
