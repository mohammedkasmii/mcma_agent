"""GUI rendering and interaction for the per-account MCMA rows -- Phase
1B-B integration. Real Tkinter widgets (see conftest.py's tk_root
fixture), no mocking of gui.py itself. No real controller/browser
worker/portal anywhere in this file -- only a tiny fake controller
recording request_login() calls."""

import threading

from mcma.app.workstation_runner.gui import RunnerApp
from mcma.app.workstation_runner.sessions import AccountState, AccountView

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"


class _FakeController:
    def __init__(self, *, accept: bool = True):
        self.login_requests: list[str] = []
        self._accept = accept

    def request_login(self, account_id: str) -> bool:
        self.login_requests.append(account_id)
        return self._accept


def test_account_row_shows_the_required_french_state_text(tk_root):
    app = RunnerApp(root=tk_root)
    app._render_accounts((AccountView(OUJDA, AccountState.READY),))
    assert app._account_rows[OUJDA]["status_var"].get() == "Prêt"
    assert app._account_rows[OUJDA]["frame"].winfo_manager() == "pack"
    assert app._account_rows[NADOR]["frame"].winfo_manager() == ""  # never in the snapshot -> hidden


def test_all_states_match_the_required_french_label_and_button_mapping(tk_root):
    app = RunnerApp(root=tk_root)
    expectations = {
        AccountState.NOT_CONFIGURED: ("Connexion requise", "Se connecter"),
        AccountState.PENDING_VERIFICATION: ("Vérification…", None),
        AccountState.LOGIN_REQUIRED: ("Connexion requise", "Se connecter"),
        AccountState.READY: ("Prêt", "Reconnecter"),
        AccountState.ERROR: ("Erreur de vérification", "Reconnecter"),
    }
    for state, (expected_text, expected_button) in expectations.items():
        app._render_accounts((AccountView(OUJDA, state),))
        assert app._account_rows[OUJDA]["status_var"].get() == expected_text
        button = app._account_rows[OUJDA]["button"]
        if expected_button is None:
            assert button.winfo_manager() == "", state
        else:
            assert button.winfo_manager() == "pack", state
            assert button["text"] == expected_button, state


def test_removed_account_disappears_on_the_next_snapshot(tk_root):
    app = RunnerApp(root=tk_root)
    app._render_accounts((
        AccountView(OUJDA, AccountState.READY), AccountView(NADOR, AccountState.NOT_CONFIGURED),
    ))
    assert app._account_rows[NADOR]["frame"].winfo_manager() == "pack"
    app._render_accounts((AccountView(OUJDA, AccountState.READY),))  # NADOR removed by the server
    assert app._account_rows[NADOR]["frame"].winfo_manager() == ""
    assert app._account_rows[OUJDA]["frame"].winfo_manager() == "pack"  # unaffected


def test_clicking_the_account_button_calls_controller_request_login(tk_root):
    app = RunnerApp(root=tk_root)
    controller = _FakeController()
    app.bind_controller(controller)
    app._render_accounts((AccountView(OUJDA, AccountState.LOGIN_REQUIRED),))
    app._on_account_button_clicked(OUJDA)
    assert controller.login_requests == [OUJDA]


def test_accepted_login_disables_the_button_until_a_fresh_render(tk_root):
    app = RunnerApp(root=tk_root)
    controller = _FakeController(accept=True)
    app.bind_controller(controller)
    app._render_accounts((AccountView(OUJDA, AccountState.LOGIN_REQUIRED),))
    app._on_account_button_clicked(OUJDA)
    assert "disabled" in app._account_rows[OUJDA]["button"].state()
    # A fresh snapshot (the real update the worker eventually publishes)
    # re-enables it based on the CURRENT state.
    app._render_accounts((AccountView(OUJDA, AccountState.READY),))
    assert "disabled" not in app._account_rows[OUJDA]["button"].state()


def test_rejected_login_request_never_disables_the_button(tk_root):
    """request_login() returning False (duplicate/unauthorized) means
    nothing new started -- the button must not be optimistically disabled
    for work that will never run."""
    app = RunnerApp(root=tk_root)
    controller = _FakeController(accept=False)
    app.bind_controller(controller)
    app._render_accounts((AccountView(OUJDA, AccountState.LOGIN_REQUIRED),))
    app._on_account_button_clicked(OUJDA)
    assert "disabled" not in app._account_rows[OUJDA]["button"].state()


def test_no_credential_or_otp_field_exists_anywhere_in_the_account_row_widgets(tk_root):
    """Structural proof: the account row only ever holds a frame, a status
    label variable, and a button -- there is no Entry widget (and so no
    place to type a credential or OTP) anywhere in this part of the GUI."""
    app = RunnerApp(root=tk_root)
    for widgets in app._account_rows.values():
        assert set(widgets) == {"frame", "status_var", "button"}


def test_enqueue_accounts_is_thread_safe_and_never_touches_a_widget_itself(tk_root):
    """Simulates a controller/worker callback arriving from a background
    thread: _enqueue_accounts() must never raise and must never itself
    mutate a widget -- only the (Tk-thread) poll loop's _render_accounts()
    call does that."""
    app = RunnerApp(root=tk_root)
    errors: list[Exception] = []

    def _from_worker_thread():
        try:
            app._enqueue_accounts((AccountView(OUJDA, AccountState.READY),))
        except Exception as exc:  # pragma: no cover -- must never happen
            errors.append(exc)

    thread = threading.Thread(target=_from_worker_thread)
    thread.start()
    thread.join(timeout=2.0)
    assert errors == []
    assert not thread.is_alive()

    # Nothing was rendered yet -- only queued.
    assert app._account_rows[OUJDA]["frame"].winfo_manager() == ""
    snapshot = app._accounts_queue.get_nowait()
    app._render_accounts(snapshot)  # standing in for the Tk-thread poll loop
    assert app._account_rows[OUJDA]["frame"].winfo_manager() == "pack"


def test_closing_the_gui_disables_every_account_button(tk_root, monkeypatch):
    app = RunnerApp(root=tk_root)

    class _NeverDoneController:
        def shutdown(self, timeout):
            return False  # keep polling -- never actually destroy the window mid-test

    app._controller = _NeverDoneController()
    monkeypatch.setattr(app._root, "after", lambda ms, callback: None)  # never actually reschedule
    app._render_accounts((AccountView(OUJDA, AccountState.READY), AccountView(NADOR, AccountState.READY)))
    app.on_close()
    for widgets in app._account_rows.values():
        assert "disabled" in widgets["button"].state()
