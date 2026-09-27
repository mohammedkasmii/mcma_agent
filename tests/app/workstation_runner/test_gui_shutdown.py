"""RELEASE BLOCKER 4 -- the GUI's window-close behavior: enter a fixed
"Fermeture..." state, poll controller.shutdown() with a short bounded
timeout via Tk's own after() (never a single long blocking call), and only
destroy the root once shutdown() reports True. Uses a REAL RunnerApp/
RunnerController pair (a real display is available on this machine); only
Tk's after()/destroy() are monkeypatched, so the test controls ticking
deterministically instead of depending on real timing or a live mainloop.

Every test uses the `gui_app` fixture below, built on top of conftest.py's
`tk_root` fixture (a tk.Toplevel attached to the single session-wide
tk.Tk() -- see conftest.py's docstring for why). `gui_app` monkeypatches
after()/destroy() on that Toplevel for deterministic control; `tk_root`
itself captures the REAL bound destroy method before any monkeypatching
and always calls it at test teardown, so no real Toplevel survives its
test regardless of what the test itself monkeypatched or triggered."""

import threading
import time

import pytest

from mcma.app.workstation_runner.config import RunnerConfig
from mcma.app.workstation_runner.controller import ControllerState, RunnerController, StatusMessage
from mcma.app.workstation_runner.gui import RunnerApp
from mcma.app.workstation_runner.http_client import RegistryConnectionError

ORIGIN = "https://central.example.local"


class _FakeIdentityStore:
    def load(self, *, expected_server_origin):
        return None

    def save(self, identity):
        pass

    def clear(self):
        pass


class _NullLifecycle:
    def run_once_loop(self, secret, stop_event, *, sessions=()):
        stop_event.wait()


class _SlowClient:
    """Blocks in enroll() until `gate` is set, then fails -- used to keep
    a pairing thread (and so shutdown()) incomplete for as long as a test
    needs."""

    def __init__(self, gate: threading.Event):
        self._gate = gate

    def enroll(self, pairing_code, *, workstation_label):
        self._gate.wait(3)
        raise RegistryConnectionError("x")

    def close(self):
        pass


@pytest.fixture
def gui_app(monkeypatch, tk_root):
    """Yields a factory `build(client_factory) -> (app, controller,
    scheduled, destroyed)`. `scheduled` collects callbacks passed to the
    (patched) root.after(); `destroyed` records calls to the (patched)
    root.destroy(). Every app built through this factory is backed by
    `tk_root` (a Toplevel on the single session-wide Tk() interpreter, not
    a fresh Tk() of its own) -- real cleanup is `tk_root`'s job, which
    captures the real destroy method before this fixture ever
    monkeypatches it."""

    def build(client_factory):
        app = RunnerApp(root=tk_root)
        controller = RunnerController(
            RunnerConfig(server_origin=ORIGIN, ca_cert_path=None, workstation_label="Poste-1"),
            _FakeIdentityStore(), client_factory, lambda client: _NullLifecycle(), app._enqueue_status,
        )
        app.bind_controller(controller)

        scheduled: list = []
        destroyed: list = []
        monkeypatch.setattr(app._root, "after", lambda ms, callback: scheduled.append(callback))
        monkeypatch.setattr(app._root, "destroy", lambda: destroyed.append(True))
        return app, controller, scheduled, destroyed

    return build


def _drain_scheduled(scheduled, destroyed, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not destroyed and time.monotonic() < deadline and scheduled:
        callback = scheduled.pop(0)
        callback()
        time.sleep(0.01)


def test_on_close_shows_fermeture_and_does_not_destroy_while_pairing_is_blocked(gui_app):
    gate = threading.Event()
    app, controller, scheduled, destroyed = gui_app(lambda config: _SlowClient(gate))

    try:
        controller.start()
        controller.submit_pairing("mcma_pc_x")

        app.on_close()
        assert app._status_var.get() == "Fermeture…"
        assert destroyed == [], "must not destroy while the pairing thread is still blocked in enroll()"
        assert len(scheduled) == 1, "must schedule exactly one poll via root.after()"
        assert "disabled" in app._associate_button.state()

        gate.set()
        _drain_scheduled(scheduled, destroyed)
        assert destroyed == [True]
    finally:
        gate.set()
        controller.shutdown(timeout=2)


def test_repeated_window_close_events_are_harmless(gui_app):
    gate = threading.Event()
    app, controller, scheduled, destroyed = gui_app(lambda config: _SlowClient(gate))

    try:
        controller.start()
        controller.submit_pairing("mcma_pc_x")

        app.on_close()
        app.on_close()  # a second WM_DELETE_WINDOW-style call
        app.on_close()  # and a third
        assert len(scheduled) == 1, "on_close must start closing only once"

        gate.set()
        _drain_scheduled(scheduled, destroyed)
        assert destroyed == [True]
    finally:
        gate.set()
        controller.shutdown(timeout=2)


def test_on_close_with_no_pairing_or_heartbeat_running_destroys_promptly(gui_app):
    app, controller, _scheduled, destroyed = gui_app(lambda config: None)

    controller.start()  # no saved identity -> PAIRING_IDLE, nothing running
    app.on_close()
    assert destroyed == [True]


def test_late_statuses_after_close_never_overwrite_fermeture_or_reenable_the_button(gui_app):
    """RELEASE FOLLOW-UP: once _closing_ui is set, "Fermeture..." must
    remain displayed and the association button must remain disabled no
    matter what StatusMessage arrives afterward (PAIRING_IDLE,
    PAIRED_CONNECTED, a failure message, or anything else already queued
    from a worker thread when closing began) -- and shutdown polling must
    keep working normally regardless."""
    gate = threading.Event()
    app, controller, scheduled, destroyed = gui_app(lambda config: _SlowClient(gate))

    try:
        controller.start()
        controller.submit_pairing("mcma_pc_x")

        app.on_close()
        assert app._status_var.get() == "Fermeture…"
        assert len(scheduled) == 1

        # Late statuses -- as if a worker thread's _enqueue_status() call
        # had raced on_close() and was only now drained by _poll_queue().
        for late_status in (
            StatusMessage(ControllerState.PAIRED_CONNECTED, "Poste connecté"),
            StatusMessage(ControllerState.PAIRING_IDLE, "Non associé. Saisissez un code d'association."),
            StatusMessage(ControllerState.PAIRED_DISCONNECTED, "Serveur inaccessible"),
            StatusMessage(ControllerState.PAIRING_IN_PROGRESS, "Association en cours…"),
        ):
            app._render(late_status)
            assert app._status_var.get() == "Fermeture…", f"overwritten by {late_status.state}"
            assert "disabled" in app._associate_button.state(), f"re-enabled by {late_status.state}"

        # Shutdown polling still proceeds normally afterward.
        gate.set()
        _drain_scheduled(scheduled, destroyed)
        assert destroyed == [True]
    finally:
        gate.set()
        controller.shutdown(timeout=2)
