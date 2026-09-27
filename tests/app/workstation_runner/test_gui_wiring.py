"""End-to-end proof that the pairing form's typed values actually reach the
enroll() call -- this is the exact wiring a code review found broken:
gui.py's server_form_values() existed but nothing ever called it, so
RunnerController always enrolled against whatever config app.py built at
startup (empty on first run), and a restart could never recover a saved
identity either (IdentityStore.load(expected_server_origin=...) would
always mismatch). Uses the REAL Tkinter widgets (a real display is
available on this machine) -- no mocking of gui.py itself, only of the
network/identity/heartbeat layers below the controller.

Each test is backed by conftest.py's `tk_root` fixture (a tk.Toplevel
attached to the single session-wide tk.Tk() interpreter, not a fresh
tk.Tk() of its own) -- see that fixture's docstring for why creating and
destroying independent Tk() interpreters per test is measurably unstable
on this Python 3.14 / Tcl-Tk combination."""

import time

from mcma.app.workstation_runner.config import RunnerConfig
from mcma.app.workstation_runner.controller import RunnerController
from mcma.app.workstation_runner.gui import RunnerApp
from mcma.app.workstation_runner.http_client import EnrollResult

ORIGIN = "https://central.example.local"


class _FakeIdentityStore:
    def __init__(self):
        self.saved = None

    def load(self, *, expected_server_origin):
        return None

    def save(self, identity):
        self.saved = identity

    def clear(self):
        pass


class _NullLifecycle:
    def run_once_loop(self, secret, stop_event, *, sessions=()):
        stop_event.wait()


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_clicking_associer_uses_the_form_values_for_enroll(tk_root):
    seen_configs = []
    seen_pairing_codes = []
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="x",
        allowed_account_ids=(), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )

    class _RecordingClient:
        def enroll(self, pairing_code, *, workstation_label):
            seen_pairing_codes.append((pairing_code, workstation_label))
            return result

        def close(self):
            pass

    def client_factory(config):
        seen_configs.append(config)
        return _RecordingClient()

    store = _FakeIdentityStore()
    app = RunnerApp(root=tk_root)
    try:
        # blank config at construction time, exactly like a first-ever launch
        controller = RunnerController(
            RunnerConfig(server_origin="", ca_cert_path=None, workstation_label=""),
            store, client_factory, lambda client: _NullLifecycle(), app._enqueue_status,
        )
        app.bind_controller(controller)

        # simulate the human filling in the pairing form
        app._server_origin_var.set(ORIGIN)
        app._label_var.set("Poste-Reel")
        app._pairing_code_var.set("mcma_pc_real_code")

        controller.start()
        app._on_associate_clicked()  # exactly what clicking "Associer ce poste" does

        assert _wait_until(lambda: len(seen_configs) >= 1)
        assert seen_configs[-1].server_origin == ORIGIN
        assert _wait_until(lambda: len(seen_pairing_codes) >= 1)
        assert seen_pairing_codes[-1] == ("mcma_pc_real_code", "Poste-Reel")
        assert _wait_until(lambda: store.saved is not None)
        assert store.saved.server_origin == ORIGIN

        # the pairing code must never linger in the widget/variable
        assert app._pairing_code_var.get() == ""
    finally:
        controller.shutdown(timeout=2)


def test_clicking_associer_with_an_invalid_url_shows_a_fixed_message_and_never_calls_the_controller(tk_root):
    calls = []

    class _NeverCalledController:
        def submit_pairing(self, *args, **kwargs):
            calls.append((args, kwargs))

    app = RunnerApp(root=tk_root)
    app._controller = _NeverCalledController()
    app._server_origin_var.set("http://not-https.example.local")  # invalid: not https
    app._label_var.set("Poste-1")
    app._pairing_code_var.set("mcma_pc_x")

    app._on_associate_clicked()

    assert calls == []
    assert app._status_var.get() != ""
    assert app._pairing_code_var.get() == ""  # still cleared even on a local validation failure
