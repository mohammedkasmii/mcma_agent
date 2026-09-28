"""Phase 1C-B, item F: the small, non-sensitive workstation job-status
label. Uses the REAL Tkinter widgets (see test_gui_wiring.py's own
docstring on why) via the session-wide `tk_root` fixture -- exercises only
RunnerApp's own enqueue/poll/render plumbing, never a real controller or
worker thread."""

from mcma.app.workstation_runner.gui import RunnerApp


def test_job_status_starts_blank(tk_root):
    app = RunnerApp(root=tk_root)
    assert app._job_status_var.get() == ""


def test_enqueued_job_status_is_rendered_on_poll(tk_root):
    app = RunnerApp(root=tk_root)
    app._enqueue_job_status("Vérification du dossier en cours")
    # _poll_job_status re-schedules itself via root.after(); drain the
    # queue directly rather than pumping the real Tk event loop.
    while not app._job_status_queue.empty():
        app._render_job_status(app._job_status_queue.get_nowait())
    assert app._job_status_var.get() == "Vérification du dossier en cours"


def test_only_the_newest_enqueued_status_wins_after_multiple_updates(tk_root):
    app = RunnerApp(root=tk_root)
    for text in ("En attente de travail", "Vérification du dossier en cours", "Vérification terminée"):
        app._enqueue_job_status(text)
    while not app._job_status_queue.empty():
        app._render_job_status(app._job_status_queue.get_nowait())
    assert app._job_status_var.get() == "Vérification terminée"


def test_render_job_status_is_a_no_op_once_closing_has_begun():
    from mcma.app.workstation_runner.gui import RunnerApp as _RunnerApp

    app = _RunnerApp.__new__(_RunnerApp)  # bypass __init__ -- no real widget needed for this check
    app._closing_ui = True

    class _FakeVar:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    app._job_status_var = _FakeVar()
    app._render_job_status("Vérification terminée")
    assert app._job_status_var.value is None


def test_job_status_queue_never_blocks_when_full(tk_root):
    app = RunnerApp(root=tk_root)
    for i in range(10_000):
        app._enqueue_job_status(f"status-{i}")  # must never raise/block even past maxsize
