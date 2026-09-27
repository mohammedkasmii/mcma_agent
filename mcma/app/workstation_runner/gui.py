"""mcma.app.workstation_runner.gui -- French Tkinter GUI. Contains no
business logic: it renders StatusMessage values from RunnerController and
forwards the pairing form to controller.submit_pairing(). All
controller-thread -> UI-thread communication goes through a bounded Queue
drained on the Tk main loop via root.after(), so Tkinter calls always
happen on the UI thread.

Two-phase construction: RunnerApp() builds every widget with no controller
yet (the controller itself needs RunnerApp._enqueue_status as its on_status
callback, so the two cannot be constructed in one step without a cycle).
Call bind_controller() before run()."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from mcma.app.workstation_runner.config import ConfigError, build_config
from mcma.app.workstation_runner.controller import ControllerState, RunnerController, StatusMessage

_CONFIG_INVALID_TEXT = "URL du serveur, certificat CA ou nom du poste invalide."
_CLOSING_TEXT = "Fermeture…"

_POLL_INTERVAL_MS = 150
_QUEUE_MAXSIZE = 64

# RELEASE BLOCKER 4: shutdown is polled, never a single long blocking call.
# Each poll bounds controller.shutdown() to this many seconds -- short
# enough that the Tk event loop stays responsive between polls -- and is
# rescheduled via root.after() until shutdown() reports True. Enrollment
# can legitimately take longer than any one bounded call (this package's
# own httpx timeouts allow it), so the window simply keeps polling rather
# than giving up.
_SHUTDOWN_POLL_INTERVAL_MS = 200
_SHUTDOWN_POLL_TIMEOUT_SECONDS = 0.15


class RunnerApp:
    def __init__(self, *, root: "tk.Tk | tk.Toplevel | None" = None) -> None:
        """`root`, when given, REPLACES the window this app builds itself
        with -- an existing tk.Tk()/tk.Toplevel the caller already owns.
        Production never passes it (RunnerApp() always creates its own
        tk.Tk(), unchanged). Tests pass a tk.Toplevel attached to a single,
        session-wide tk.Tk() interpreter instead of creating a fresh Tk()
        per test -- see tests/app/workstation_runner/conftest.py's
        `tk_root` fixture docstring for why creating and destroying many
        independent Tk() interpreters within one process is unstable on
        some Python/Tcl-Tk combinations. Every Tk variable below is built
        with an explicit `master=self._root` so it is never implicitly
        bound to tkinter's own global default root instead of this
        window -- required for a Toplevel-backed window to behave
        identically to a Tk()-backed one."""
        self._controller: RunnerController | None = None
        self._closing_ui = False  # RELEASE BLOCKER 4: on_close starts closing only once
        self._queue: "queue.Queue[StatusMessage]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._root = root if root is not None else tk.Tk()
        self._root.title("MCMA — Poste agent")
        self._root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._status_var = tk.StringVar(master=self._root, value="")
        ttk.Label(self._root, textvariable=self._status_var, wraplength=360).pack(padx=16, pady=(16, 8))

        self._pairing_frame = ttk.Frame(self._root)
        ttk.Label(self._pairing_frame, text="URL du serveur central").pack(anchor="w")
        self._server_origin_var = tk.StringVar(master=self._root)
        ttk.Entry(self._pairing_frame, textvariable=self._server_origin_var, width=48).pack(fill="x")

        ttk.Label(self._pairing_frame, text="Certificat CA (optionnel)").pack(anchor="w", pady=(8, 0))
        self._ca_cert_var = tk.StringVar(master=self._root)
        ttk.Entry(self._pairing_frame, textvariable=self._ca_cert_var, width=48).pack(fill="x")

        ttk.Label(self._pairing_frame, text="Nom du poste").pack(anchor="w", pady=(8, 0))
        self._label_var = tk.StringVar(master=self._root)
        ttk.Entry(self._pairing_frame, textvariable=self._label_var, width=48).pack(fill="x")

        ttk.Label(self._pairing_frame, text="Code d'association").pack(anchor="w", pady=(8, 0))
        self._pairing_code_var = tk.StringVar(master=self._root)
        self._pairing_code_entry = ttk.Entry(self._pairing_frame, textvariable=self._pairing_code_var, width=48, show="•")
        self._pairing_code_entry.pack(fill="x")

        self._associate_button = ttk.Button(self._pairing_frame, text="Associer ce poste", command=self._on_associate_clicked)
        self._associate_button.pack(pady=(12, 0))
        self._pairing_frame.pack(padx=16, pady=8, fill="x")

        self._paired_frame = ttk.Frame(self._root)
        ttk.Label(self._paired_frame, text="Comptes MCMA").pack(anchor="w")
        self._accounts_var = tk.StringVar(
            master=self._root, value="acct-mcma-oujda: NOT_CONFIGURED\nacct-mcma-nador: NOT_CONFIGURED",
        )
        ttk.Label(self._paired_frame, textvariable=self._accounts_var).pack(anchor="w")

    def bind_controller(self, controller: RunnerController) -> None:
        self._controller = controller

    def prefill_form(self, config) -> None:
        """Populate the pairing form from a previously-saved, non-secret
        config (see app.py's build_default_config_from_env()), so a human
        re-pairing after a restart does not have to retype the server URL,
        CA certificate path or workstation label."""
        self._server_origin_var.set(config.server_origin)
        self._ca_cert_var.set(str(config.ca_cert_path) if config.ca_cert_path else "")
        self._label_var.set(config.workstation_label)

    def server_form_values(self) -> tuple:
        """(server_origin, ca_cert_path_or_empty, workstation_label) as
        currently typed."""
        return (self._server_origin_var.get().strip(), self._ca_cert_var.get().strip(), self._label_var.get().strip())

    def _clear_pairing_code(self) -> None:
        self._pairing_code_var.set("")
        self._pairing_code_entry.delete(0, "end")

    def _on_associate_clicked(self) -> None:
        assert self._controller is not None, "bind_controller() must be called before use"
        pairing_code = self._pairing_code_var.get().strip()
        server_origin, ca_cert_path, workstation_label = self.server_form_values()
        try:
            new_config = build_config(
                server_origin=server_origin, ca_cert_path=ca_cert_path or None, workstation_label=workstation_label,
            )
        except ConfigError:
            self._status_var.set(_CONFIG_INVALID_TEXT)
            self._clear_pairing_code()
            pairing_code = None  # noqa: F841
            return
        self._associate_button.state(["disabled"])
        try:
            self._controller.submit_pairing(pairing_code, config=new_config)
        finally:
            self._clear_pairing_code()  # never kept in a Tkinter variable a moment longer than needed
            pairing_code = None  # noqa: F841

    def _enqueue_status(self, status: StatusMessage) -> None:
        try:
            self._queue.put_nowait(status)
        except queue.Full:
            pass  # a full queue means a stale event; the next poll drains the newest we could keep

    def _poll_queue(self) -> None:
        try:
            while True:
                status = self._queue.get_nowait()
                self._render(status)
        except queue.Empty:
            pass
        self._root.after(_POLL_INTERVAL_MS, self._poll_queue)

    def _render(self, status: StatusMessage) -> None:
        if self._closing_ui:
            # RELEASE FOLLOW-UP: once closing has begun, "Fermeture..." and
            # the disabled button must never be overwritten by a status a
            # worker thread queued before (or even during) on_close() --
            # _poll_queue() keeps draining the queue throughout the
            # shutdown-poll phase (it is a separate root.after() chain from
            # _poll_shutdown()), so without this guard a late
            # PAIRING_IDLE/PAIRED_CONNECTED/failure status would silently
            # replace the closing UI and re-enable the button while the
            # process is already on its way out.
            return
        self._status_var.set(status.text)
        if status.state in (ControllerState.PAIRING_IDLE, ControllerState.PAIRING_IN_PROGRESS):
            self._paired_frame.pack_forget()
            self._pairing_frame.pack(padx=16, pady=8, fill="x")
            self._associate_button.state(["!disabled"] if status.state == ControllerState.PAIRING_IDLE else ["disabled"])
        else:
            self._pairing_frame.pack_forget()
            self._paired_frame.pack(padx=16, pady=8, fill="x")

    def on_close(self) -> None:
        """RELEASE BLOCKER 4: repeated WM_DELETE_WINDOW events (or a second
        call from anywhere) must be harmless -- closing starts only once.
        The window stays open and responsive (and, in app.py, the
        single-instance mutex stays held) until controller.shutdown()
        reports every thread has actually finished; a single flat timeout
        was insufficient because enrollment can remain in network I/O
        longer than any one bounded call should block this method."""
        if self._closing_ui:
            return
        self._closing_ui = True
        self._associate_button.state(["disabled"])
        self._status_var.set(_CLOSING_TEXT)
        if self._controller is None:
            self._root.destroy()
            return
        self._poll_shutdown()

    def _poll_shutdown(self) -> None:
        assert self._controller is not None
        if self._controller.shutdown(timeout=_SHUTDOWN_POLL_TIMEOUT_SECONDS):
            self._root.destroy()
        else:
            self._root.after(_SHUTDOWN_POLL_INTERVAL_MS, self._poll_shutdown)

    def run(self) -> None:
        assert self._controller is not None, "bind_controller() must be called before run()"
        self._root.after(_POLL_INTERVAL_MS, self._poll_queue)
        self._controller.start()
        self._root.mainloop()
