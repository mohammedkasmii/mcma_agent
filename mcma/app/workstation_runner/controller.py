"""mcma.app.workstation_runner.controller -- the pure-Python state machine
behind the GUI. Imports no tkinter: every state transition here is
independently testable without a display. The GUI layer (gui.py) only
renders StatusMessage values this controller emits and forwards user input
(submit_pairing) back in."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from mcma.app.workstation_runner.browser_worker import BrowserSessionWorker
from mcma.app.workstation_runner.config import RunnerConfig
from mcma.app.workstation_runner.heartbeat import HeartbeatWorker, LifecycleEvent
from mcma.app.workstation_runner.http_client import RegistryConnectionError, RegistryProtocolError
from mcma.app.workstation_runner.job_worker import JobPollingWorker
from mcma.app.workstation_runner.job_worker import LifecycleEvent as JobLifecycleEvent
from mcma.app.workstation_runner.sessions import AccountState, VerificationScheduler, WorkstationSessionManager

# Phase 1C-B, item F: a small, non-sensitive workstation job-status
# indication. Fixed French text only -- never a dossier identifier, a
# claim token, a credential, or raw exception text (JobLifecycleEvent
# itself carries no such payload; see job_worker.py's own docstring).
_JOB_STATUS_TEXT = {
    JobLifecycleEvent.JOB_STARTED: "Vérification du dossier en cours",
    JobLifecycleEvent.JOB_SUCCEEDED: "Vérification terminée",
    JobLifecycleEvent.JOB_FAILED: "Échec de la vérification",
    JobLifecycleEvent.CONNECTION_FAILED: "En attente de travail",
}
_JOB_STATUS_IDLE_TEXT = "En attente de travail"


class ControllerState(Enum):
    PAIRING_IDLE = "PAIRING_IDLE"
    PAIRING_IN_PROGRESS = "PAIRING_IN_PROGRESS"
    PAIRED_CONNECTING = "PAIRED_CONNECTING"
    PAIRED_CONNECTED = "PAIRED_CONNECTED"
    PAIRED_DISCONNECTED = "PAIRED_DISCONNECTED"


@dataclass(frozen=True)
class StatusMessage:
    state: ControllerState
    text: str


_TEXT = {
    ControllerState.PAIRING_IDLE: "Non associé. Saisissez un code d'association.",
    ControllerState.PAIRING_IN_PROGRESS: "Association en cours…",
    ControllerState.PAIRED_CONNECTING: "Connexion en cours…",
    ControllerState.PAIRED_CONNECTED: "Poste connecté",
    ControllerState.PAIRED_DISCONNECTED: "Serveur inaccessible",
}

_ENROLL_FAILED_TEXT = "Échec de l'association. Vérifiez le code et réessayez."
_ENROLL_CONNECTION_FAILED_TEXT = "Serveur inaccessible."
_CONFIG_PERSIST_FAILED_TEXT = "Impossible d'enregistrer la configuration locale. Réessayez."
_IDENTITY_PERSIST_FAILED_TEXT = (
    "Le poste a été créé sur le serveur mais n'a pas pu être enregistré sur cet ordinateur. "
    "Demandez à un administrateur de révoquer ce poste avant une nouvelle tentative d'association."
)


class RunnerController:
    def __init__(
        self,
        config: RunnerConfig,
        identity_store,
        client_factory: Callable[[RunnerConfig], object],
        lifecycle_factory: Callable[[object], object],
        on_status: Callable[[StatusMessage], None],
        *,
        on_config_saved: Callable[[RunnerConfig], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        session_manager: WorkstationSessionManager,
        session_store,
        browser_worker: BrowserSessionWorker,
        verification_scheduler: VerificationScheduler,
        on_accounts_changed: Callable[[tuple], None] | None = None,
        job_lifecycle_factory: Callable[[object], object] | None = None,
        on_job_status: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config
        self._identity_store = identity_store
        self._client_factory = client_factory
        self._lifecycle_factory = lifecycle_factory
        self._on_status = on_status
        self._on_config_saved = on_config_saved
        self._on_log = on_log
        self._pairing_lock = threading.Lock()
        self._pairing_in_progress = False
        self._heartbeat_worker: HeartbeatWorker | None = None
        self._pairing_thread: threading.Thread | None = None
        # RELEASE BLOCKER 4: a thread-safe closing flag. threading.Event's
        # set()/is_set() are already safe to call from any thread without
        # extra locking.
        self._closing = threading.Event()

        # Phase 1B-B integration: browser-session ownership. All four are
        # injected, already-reviewed objects -- this controller composes
        # them, it does not construct or re-review their behavior.
        self._session_manager = session_manager
        self._session_store = session_store
        self._browser_worker = browser_worker
        self._verification_scheduler = verification_scheduler
        self._on_accounts_changed = on_accounts_changed

        # Phase 1C-B integration: the DRY_RUN job-polling worker. Started
        # only once identity exists (same gate as heartbeat -- see
        # _start_heartbeat), on its OWN RegistryHttpClient instance (never
        # shared with the heartbeat worker's), and torn down in shutdown()
        # alongside the other two non-daemon workers this controller owns.
        # `job_lifecycle_factory`/`on_job_status` are both optional so
        # EXISTING callers/tests that construct a RunnerController without
        # any knowledge of Phase 1C-B keep working unchanged.
        self._job_lifecycle_factory = job_lifecycle_factory
        self._on_job_status = on_job_status
        self._job_worker: JobPollingWorker | None = None
        # Tracks "currently CONNECTED" for the job worker's own is_ready()
        # gate (claims no job while disconnected) -- set/cleared from
        # _handle_lifecycle_event, on whatever thread the heartbeat worker
        # runs on. threading.Event is already safe to read/set from any
        # thread without extra locking.
        self._connected = threading.Event()
        if self._on_job_status is not None:
            self._on_job_status(_JOB_STATUS_IDLE_TEXT)

    def _emit(self, state: ControllerState, text: str | None = None) -> None:
        self._on_status(StatusMessage(state, text if text is not None else _TEXT[state]))

    def _log(self, event: str) -> None:
        """Fixed, safe event names ONLY -- never interpolate a pairing
        code, secret, path or exception text into `event`."""
        if self._on_log is not None:
            self._on_log(event)

    def start(self) -> None:
        # Started exactly once here, regardless of pairing outcome:
        # BrowserSessionWorker.start() is itself idempotent (at most one
        # thread ever, across any number of calls), so relying on that
        # already-reviewed guarantee is simpler and no less correct than a
        # second "started" flag here. The worker being up before any
        # accounts exist is harmless -- request_login/request_verification
        # both refuse until WorkstationSessionManager actually authorizes
        # an account, which only happens once a heartbeat reconciles one.
        self._browser_worker.start()
        identity = self._identity_store.load(expected_server_origin=self._config.server_origin)
        if identity is None:
            self._emit(ControllerState.PAIRING_IDLE)
            return
        self._start_heartbeat(identity.runner_secret)

    def request_login(self, account_id: str) -> bool:
        """The GUI's only browser-session entry point. Never touches
        Playwright/portal code directly -- forwards to the already-owned
        BrowserSessionWorker, which does everything on its own thread."""
        return self._browser_worker.request_login(account_id)

    def _current_sessions(self) -> tuple:
        """sessions_provider for HeartbeatLifecycle -- recomputed fresh on
        every call, straight from WorkstationSessionManager. Never cached
        here; see heartbeat.py's own docstring for why."""
        return self._session_manager.heartbeat_sessions()

    def _handle_allowed_accounts(self, allowed_account_ids: tuple) -> None:
        """on_allowed_accounts for HeartbeatLifecycle -- called after EVERY
        successful heartbeat (including the ACCOUNT_NOT_ALLOWED retry),
        from the heartbeat worker's own thread. Reconciles
        WorkstationSessionManager against the server's authoritative
        answer, then acts on what changed:
          * newly allowed accounts already got NOT_CONFIGURED or
            PENDING_VERIFICATION assigned by reconcile_allowed_accounts()
            itself -- this only needs to actually REQUEST the immediate
            verification for the ones that need it;
          * removed accounts are cancelled first (invalidating any queued
            or in-flight browser work AND acting as a persistence barrier
            -- see BrowserSessionWorker.cancel_account), then their local
            encrypted session is cleared. reconcile_allowed_accounts()
            already dropped them from tracking as part of computing this
            same result, so no stale result can ever resurrect one."""
        result = self._session_manager.reconcile_allowed_accounts(allowed_account_ids)
        for account_id in result.removed:
            self._browser_worker.cancel_account(account_id)
            self._verification_scheduler.forget(account_id)
            try:
                self._session_store.clear(account_id)
            except Exception:
                pass  # best-effort -- never crash the heartbeat thread over this
        for account_id in result.added_needing_verification:
            self._verification_scheduler.mark_verified(account_id)
            self._browser_worker.request_verification(account_id)
        self._publish_accounts_snapshot()

    def _run_periodic_verification(self) -> None:
        """Driven off every CONNECTED heartbeat tick (see
        _handle_lifecycle_event) -- never a second timer thread. Testable
        without real waiting via VerificationScheduler's own injectable
        clock."""
        tracked = self._session_manager.tracked_account_ids()
        for account_id in self._verification_scheduler.due_accounts(tracked):
            self._verification_scheduler.mark_verified(account_id)
            self._browser_worker.request_verification(account_id)

    def _handle_worker_update(self) -> None:
        """on_update for BrowserSessionWorker -- payload-free by design
        (see browser_worker.py's own docstring for why). Reacts by reading
        a FRESH, authoritative snapshot from WorkstationSessionManager and
        publishing THAT to the GUI -- never a captured account_id/state
        pair from the moment the worker's command happened to finish."""
        self._publish_accounts_snapshot()

    def _publish_accounts_snapshot(self) -> None:
        if self._on_accounts_changed is not None:
            try:
                self._on_accounts_changed(self._session_manager.snapshot())
            except Exception:
                pass  # a GUI callback failure must never break the caller's thread

    def submit_pairing(self, pairing_code: str, *, config: RunnerConfig | None = None) -> None:
        """`config`, when given, REPLACES the controller's current config
        before enrolling -- this is how the pairing form's just-typed server
        origin / CA cert / workstation label actually reach the enroll call
        and (on success) get persisted for the next restart. The caller
        (gui.py) validates the form with config.build_config() and only
        passes a config here once it is already valid; this method does not
        validate it again."""
        if self._closing.is_set():
            return  # RELEASE BLOCKER 4: shutdown has started, refuse new attempts
        with self._pairing_lock:
            if self._pairing_in_progress:
                return  # duplicate concurrent attempt: dropped, not queued
            self._pairing_in_progress = True
        if config is not None:
            self._config = config
        self._log("pairing_started")
        self._emit(ControllerState.PAIRING_IN_PROGRESS)
        self._pairing_thread = threading.Thread(target=self._run_pairing, args=(pairing_code,), daemon=False)
        self._pairing_thread.start()

    def _run_pairing(self, pairing_code: str) -> None:
        try:
            result = self._persist_config_then_enroll(pairing_code)
        finally:
            with self._pairing_lock:
                self._pairing_in_progress = False
        if result is None:
            return  # a fixed failure status was already emitted
        self._finish_successful_pairing(result)

    def _persist_config_then_enroll(self, pairing_code: str):
        """RELEASE BLOCKER 2: the validated non-secret configuration is
        persisted BEFORE the enrollment request is ever sent. If local
        storage cannot even hold a non-secret config, it is not going to
        durably hold the encrypted identity either -- and the pairing code
        is single-use server-side, so it must never be spent on an attempt
        already doomed to fail persistence."""
        if self._on_config_saved is not None:
            try:
                self._on_config_saved(self._config)
            except Exception:
                self._log("pairing_failed_config_persistence")
                self._emit(ControllerState.PAIRING_IDLE, _CONFIG_PERSIST_FAILED_TEXT)
                return None
        return self._attempt_enroll(pairing_code)

    def _attempt_enroll(self, pairing_code: str):
        """Returns an EnrollResult on success, or None after emitting a
        fixed failure status. Never raises: a client-construction failure
        (e.g. an unreadable/invalid CA certificate file) or any other
        unanticipated error must never leave the pairing attempt hung
        forever with the button disabled and no status ever emitted."""
        try:
            client = self._client_factory(self._config)
        except Exception:
            self._log("pairing_failed_client_construction")
            self._emit(ControllerState.PAIRING_IDLE, _ENROLL_FAILED_TEXT)
            return None
        try:
            return client.enroll(pairing_code, workstation_label=self._config.workstation_label)
        except RegistryConnectionError:
            self._log("pairing_failed_connection")
            self._emit(ControllerState.PAIRING_IDLE, _ENROLL_CONNECTION_FAILED_TEXT)
            return None
        except RegistryProtocolError:
            self._log("pairing_failed_protocol")
            self._emit(ControllerState.PAIRING_IDLE, _ENROLL_FAILED_TEXT)
            return None
        except Exception:
            self._log("pairing_failed_unexpected")
            self._emit(ControllerState.PAIRING_IDLE, _ENROLL_FAILED_TEXT)
            return None
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _finish_successful_pairing(self, result) -> None:
        """RELEASE BLOCKER 2: enroll() already succeeded server-side -- the
        server now holds an ACTIVE runner for this employee. Encrypted
        local persistence of the identity is now MANDATORY, not
        best-effort: reporting success or starting a heartbeat with a
        secret that only exists in this thread's memory would silently
        lose it the moment the process exits, leaving the server-side
        runner orphaned with no way for this app to ever heartbeat it
        again."""
        from mcma.app.workstation_runner.identity import IDENTITY_FORMAT_VERSION, RunnerIdentity

        identity = RunnerIdentity(
            format_version=IDENTITY_FORMAT_VERSION, server_origin=self._config.server_origin,
            runner_id=result.runner_id, runner_secret=result.runner_secret,
            allowed_account_ids=result.allowed_account_ids,
        )
        try:
            self._identity_store.save(identity)
        except Exception:
            # Catches DPAPI failures (DpapiUnavailable), filesystem errors
            # (OSError), and any other unexpected failure crossing this
            # thread boundary -- all handled the same fail-closed way.
            # Never log the exception's text: it could be surfaced from a
            # path or (in a future backend) certificate/key material.
            self._log("pairing_failed_identity_persistence")
            self._emit(ControllerState.PAIRING_IDLE, _IDENTITY_PERSIST_FAILED_TEXT)
            return
        self._log("pairing_succeeded")
        if self._closing.is_set():
            # RELEASE BLOCKER 4: the identity is durably saved above -- the
            # server-side runner is never orphaned -- but the process is on
            # its way out, so no new heartbeat thread is started only to be
            # immediately stopped again.
            self._log("pairing_succeeded_during_shutdown_no_heartbeat")
            return
        self._start_heartbeat(identity.runner_secret)

    def _start_heartbeat(self, runner_secret: str) -> None:
        # RELEASE BLOCKER 3: no allowed_account_ids parameter here at all --
        # Phase 1B-A has no browser sessions to report, so HeartbeatWorker
        # is given no `sessions` (defaults to empty). See
        # RegistryHttpClient.heartbeat's docstring for why resending a
        # locally-cached account list is wrong, not just unnecessary.
        client = None
        try:
            client = self._client_factory(self._config)
            lifecycle = self._lifecycle_factory(client)
            worker = HeartbeatWorker(lifecycle, runner_secret)
        except Exception:
            # A local problem (e.g. a corrupt saved CA certificate path)
            # must show a fixed status, never crash controller.start() (and
            # so the whole app, since start() runs on app startup). Close
            # the client if it was built before the failure -- never leak
            # it just because a LATER construction step failed.
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            self._log("heartbeat_start_failed")
            self._emit(ControllerState.PAIRED_DISCONNECTED)
            return
        self._heartbeat_worker = worker
        # Emit PAIRED_CONNECTING THEN start the worker, never the reverse:
        # the worker thread does not exist until start() runs, so emitting
        # first guarantees this status is always observed before anything
        # the worker itself might emit (e.g. an immediate UNAUTHORIZED) --
        # otherwise the two could race and a stale "Connexion en cours"
        # could overwrite a more recent, more correct status. Join-safety
        # against a concurrent shutdown() is HeartbeatWorker.start()'s job
        # (see its comment), not an ordering concern here.
        self._emit(ControllerState.PAIRED_CONNECTING)
        worker.start()
        self._start_job_worker(runner_secret)

    def _job_worker_is_ready(self) -> bool:
        """Claims no job while disconnected, shutting down, or before
        account reconciliation has reported at least one account READY --
        checked fresh on every poll, never cached."""
        if self._closing.is_set() or not self._connected.is_set():
            return False
        return any(view.state is AccountState.READY for view in self._session_manager.snapshot())

    def _start_job_worker(self, runner_secret: str) -> None:
        """Phase 1C-B: started alongside the heartbeat, on its own
        RegistryHttpClient instance (never shared with the heartbeat
        worker's own client). A no-op when this controller was constructed
        without job-worker support (job_lifecycle_factory is None) -- kept
        optional so existing callers/tests are unaffected."""
        if self._job_lifecycle_factory is None:
            return
        client = None
        try:
            client = self._client_factory(self._config)
            lifecycle = self._job_lifecycle_factory(client)
            worker = JobPollingWorker(lifecycle, runner_secret)
        except Exception:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            self._log("job_worker_start_failed")
            return
        self._job_worker = worker
        worker.start()

    def _handle_job_event(self, event: JobLifecycleEvent) -> None:
        """on_event for JobPollingLifecycle -- fixed, non-sensitive French
        text only (item F). JobLifecycleEvent itself carries no dossier
        identifier, claim token, credential, or exception text -- see
        job_worker.py's own docstring -- so there is nothing here to
        redact, only to translate."""
        if self._on_job_status is not None:
            self._on_job_status(_JOB_STATUS_TEXT.get(event, _JOB_STATUS_IDLE_TEXT))

    def _handle_lifecycle_event(self, event: LifecycleEvent) -> None:
        # CONNECTED is deliberately not logged here: it recurs on every
        # successful heartbeat (every ~10s), which would dominate the
        # bounded rotating log with pure noise. CONNECTION_FAILED and
        # UNAUTHORIZED are real, comparatively rare anomalies worth a
        # record.
        if event is LifecycleEvent.CONNECTED:
            self._connected.set()
            self._emit(ControllerState.PAIRED_CONNECTED)
            self._run_periodic_verification()
        elif event is LifecycleEvent.CONNECTION_FAILED:
            self._connected.clear()
            self._log("heartbeat_connection_failed")
            self._emit(ControllerState.PAIRED_DISCONNECTED)
        elif event is LifecycleEvent.UNAUTHORIZED:
            self._connected.clear()
            # CLEANUP: this controller is the SOLE owner of clearing the
            # local identity on a 401 -- HeartbeatLifecycle only reports the
            # event and never touches identity_store itself (single
            # ownership, not two layers racing to delete the same file).
            # A deletion failure is made VISIBLE with its own distinct log
            # event, not folded into the same "cleared" event a real
            # success gets, and is caught broadly so it can never propagate
            # back into (and kill) the calling heartbeat thread.
            #
            # Browser-session cleanup happens FIRST, before the identity
            # itself is touched: cancel every tracked account's browser
            # work (this also acts as a persistence barrier -- see
            # BrowserSessionWorker.cancel_account), forget their
            # verification schedule, clear every encrypted local session,
            # and reset WorkstationSessionManager -- so no stale command
            # from before this revocation can ever recreate a session for
            # an account this employee no longer has access to.
            tracked = self._session_manager.tracked_account_ids()
            for account_id in tracked:
                self._browser_worker.cancel_account(account_id)
                self._verification_scheduler.forget(account_id)
            try:
                self._session_store.clear_all()
            except Exception:
                pass
            self._session_manager.reset()
            try:
                self._identity_store.clear()
                self._log("heartbeat_unauthorized_cleared")
            except Exception:
                self._log("heartbeat_unauthorized_clear_failed")
            self._emit(ControllerState.PAIRING_IDLE)
            self._publish_accounts_snapshot()

    def shutdown(self, timeout: float = 5.0) -> bool:
        """RELEASE BLOCKER 4: a single BOUNDED attempt -- never a long
        blocking wait -- safe to call repeatedly (e.g. from a GUI poll
        loop via Tk's after()). Returns True once the pairing thread AND
        the heartbeat worker have both actually finished, False if
        `timeout` was not enough this time (call again). A flat single
        join was insufficient: enrollment can legitimately remain in
        network I/O (this package's own httpx timeouts allow more than 5s
        end-to-end) longer than any one bounded call should block a GUI.

        Idempotent: sets the closing flag every call (submit_pairing()
        checks it and refuses new attempts from the moment this is first
        called), and only does work that is still outstanding.

        Ordering: the pairing thread is joined/checked FIRST, THEN the
        heartbeat worker, THEN the job-polling worker (Phase 1C-B), THEN
        the browser session worker -- never any other order. If a pairing
        attempt already in flight succeeds while shutdown() is being
        polled, its identity is persisted but _finish_successful_pairing()
        skips starting a new heartbeat/job worker once closing has begun
        (see there) -- so by the time this method observes the pairing
        thread has finished, self._heartbeat_worker/self._job_worker can no
        longer change underneath it, and checking them after is safe. The
        job worker's OWN internal shutdown handling (release before start,
        cancel-and-report-RUNNER_CANCELLED once RUNNING) already ran on its
        own thread by the time its stop() here returns -- this method only
        sets the stop signal and joins, exactly like the heartbeat worker.
        The browser session worker is always owned (never None) and its
        own stop() is itself bounded, idempotent, and safe even if it was
        never started -- so it is always the final step here, and this
        method returns True only once every one of the (up to) four
        non-daemon workers it owns has actually finished."""
        self._closing.set()
        pairing_done = self._pairing_thread is None or not self._pairing_thread.is_alive()
        if not pairing_done:
            self._pairing_thread.join(timeout=timeout)
            pairing_done = not self._pairing_thread.is_alive()
        if not pairing_done:
            return False
        heartbeat_done = self._heartbeat_worker is None or not self._heartbeat_worker.is_alive()
        if not heartbeat_done:
            self._heartbeat_worker.stop(timeout=timeout)
            heartbeat_done = not self._heartbeat_worker.is_alive()
        if not heartbeat_done:
            return False
        job_worker_done = self._job_worker is None or not self._job_worker.is_alive()
        if not job_worker_done:
            job_worker_done = self._job_worker.stop(timeout=timeout)
        if not job_worker_done:
            return False
        return self._browser_worker.stop(timeout=timeout)
