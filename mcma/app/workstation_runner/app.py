"""mcma.app.workstation_runner.app -- composition root. Builds real
backends (DPAPI, httpx, Tkinter, and -- Phase 1B-B -- the reviewed
mcma.portal.workstation_sessions functions), acquires the single-instance
mutex, and runs the GUI. The only place in this package that constructs
DpapiCurrentUserBackend / RegistryHttpClient / RunnerApp / BrowserSessionWorker
together, and the ONLY lightweight-layer module allowed to import
mcma.portal (see tests/app/workstation_runner/test_import_isolation.py's
"full" check, and pyproject.toml's allow_indirect_imports=true note)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

from mcma.app.workstation_runner.browser_worker import BrowserSessionWorker
from mcma.app.workstation_runner.config import ConfigError, RunnerConfig, build_config
from mcma.app.workstation_runner.controller import RunnerController
from mcma.app.workstation_runner.gui import RunnerApp
from mcma.app.workstation_runner.heartbeat import HeartbeatLifecycle
from mcma.app.workstation_runner.http_client import RegistryHttpClient
from mcma.app.workstation_runner.identity import IdentityStore, default_identity_path, select_production_crypto_backend
from mcma.app.workstation_runner.logging_setup import configure_logging, log_event
from mcma.app.workstation_runner.session_store import (
    WorkstationSessionStore, default_sessions_dir,
    select_production_crypto_backend as select_session_crypto_backend,
)
from mcma.app.workstation_runner.sessions import VerificationScheduler, WorkstationSessionManager
from mcma.core.mutex import MutexAcquisitionError, create_single_instance_mutex
from mcma.portal.workstation_sessions import perform_manual_login, verify_saved_session

_MUTEX_BASE_NAME = "MCMA_WorkstationRunner"

_SINGLE_INSTANCE_MESSAGE = "Une autre instance du poste agent MCMA est déjà en cours d'exécution."
_FATAL_STARTUP_MESSAGE = "Le poste agent MCMA n'a pas pu démarrer."
_APP_TITLE = "MCMA — Poste agent"

_SAFE_MUTEX_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")
_SID_FALLBACK_NAME = "sid_unavailable"

_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1  # TOKEN_INFORMATION_CLASS.TokenUser


def _current_windows_user_sid() -> str | None:
    """Real Win32 SID query via ctypes -- no pywin32 dependency, matching
    mcma.core.mutex's own pattern. Returns the authenticated user's SID
    (e.g. "S-1-5-21-...") for the CURRENT process's own security token, or
    None off Windows or if the query fails for any reason. Deliberately
    NOT the USERNAME/USER environment variables: any process can set those
    to an arbitrary string, which could either force a spurious
    "already running" refusal against a different account or collide two
    different accounts onto the same mutex name. A SID is queried directly
    from the OS and survives an account rename (a display username does
    not)."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    token_handle = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token_handle)):
        return None
    try:
        needed = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token_handle, _TOKEN_USER, None, 0, ctypes.byref(needed))
        if needed.value == 0:
            return None
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(token_handle, _TOKEN_USER, buffer, needed, ctypes.byref(needed)):
            return None
        # TOKEN_USER's first (and only) field is a SID_AND_ATTRIBUTES whose
        # first field is a PSID -- a plain pointer at the start of the buffer.
        sid_ptr = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not sid_ptr:
            return None
        string_sid = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(string_sid)):
            return None
        try:
            return ctypes.wstring_at(string_sid)
        finally:
            kernel32.LocalFree(string_sid)
    except OSError:
        return None
    finally:
        kernel32.CloseHandle(token_handle)


def single_instance_mutex_name(*, _sid_query: Callable[[], str | None] = _current_windows_user_sid) -> str:
    """Per-Windows-user, not machine-wide: mcma.core.mutex's
    WindowsSingleInstanceMutex uses a `Global\\` namespace, which spans
    every session on the machine (including other users via Fast User
    Switching or Remote Desktop). The spec requires "one poste agent per
    Windows user", so the user's own SID -- never USERNAME/USER, see
    _current_windows_user_sid -- is folded into the mutex name itself; the
    reused mutex primitive is not changed, only parameterized. If the SID
    query itself fails, this fails closed to a fixed, shared name (the
    single-instance guarantee still applies, just without per-user
    distinction, exactly as it did before this fix existed) rather than a
    randomized name that would silently disable it."""
    sid = _sid_query() or _SID_FALLBACK_NAME
    return f"{_MUTEX_BASE_NAME}_{_SAFE_MUTEX_NAME_RE.sub('_', sid)}"


_MB_OK = 0x00000000
_MB_ICONERROR = 0x00000010
_MB_SETFOREGROUND = 0x00010000


def _native_message_box(title: str, message: str, *, _user32=None) -> bool:
    """Last-resort Windows-native fallback (ctypes user32.MessageBoxW, no
    pywin32) for when Tk itself cannot even be constructed (e.g. a broken
    or missing Tcl install) -- covers exactly the gap a Tk-only fallback
    chain leaves under pythonw with no working Tk. Off Windows, or on any
    failure, returns False and never raises; `_user32` is an injectable
    seam for tests (never a real modal dialog in automated tests)."""
    if sys.platform != "win32":
        return False
    try:
        if _user32 is None:
            import ctypes

            _user32 = ctypes.windll.user32
        result = _user32.MessageBoxW(None, message, title, _MB_OK | _MB_ICONERROR | _MB_SETFOREGROUND)
        return bool(result)
    except Exception:
        return False


def _print_safely(message: str) -> None:
    """print() is a silent no-op (or can raise, depending on interpreter
    state) under pythonw, where sys.stdout is None -- never call it
    blindly. Only ever prints the fixed message it is given; never raises."""
    try:
        if sys.stdout is None:
            return
        print(message)
    except Exception:
        pass


def _show_message_box(
    title: str, message: str, *, tk_module=None, messagebox_module=None, _native_message_box_fn=_native_message_box,
) -> None:
    """Shows a message with no console required (works under pythonw,
    unlike print()). `tk_module`/`messagebox_module` are injectable seams
    for tests -- they default to the real tkinter modules, imported lazily
    so this module stays importable without a display until this function
    actually runs.

    Fallback chain, each step never raising and never showing anything but
    the fixed `title`/`message` given (never a secret, never raw exception
    text):
      1. Tk's messagebox (the normal path).
      2. A native Win32 MessageBoxW via ctypes, Windows only -- covers a
         broken/missing Tcl install where Tk cannot even be constructed.
      3. print(), but ONLY if sys.stdout is a real, writable stream (never
         under pythonw, where it is None), and only as the last resort.
      4. Return safely with no visible effect if every fallback failed."""
    try:
        if tk_module is None or messagebox_module is None:
            import tkinter as _tk
            from tkinter import messagebox as _messagebox

            tk_module = tk_module or _tk
            messagebox_module = messagebox_module or _messagebox
        root = tk_module.Tk()
        root.withdraw()
        try:
            messagebox_module.showerror(title, message)
        finally:
            root.destroy()
        return
    except Exception:
        pass
    if _native_message_box_fn(title, message):
        return
    _print_safely(message)


def _local_app_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set")
    return Path(local_app_data) / "MCMA Runner"


def _config_path() -> Path:
    return _local_app_data_dir() / "config.json"


def build_default_config_from_env() -> RunnerConfig | None:
    """Non-secret pairing-form defaults (server origin, CA cert path,
    workstation label) saved on first successful pairing, so a restart does
    not require retyping them -- and, critically, so
    IdentityStore.load(expected_server_origin=...) is given the SAME origin
    the identity was saved under; without this, a restart would always see
    an origin mismatch and treat a perfectly valid saved identity as
    unusable. Never contains a secret or pairing code."""
    path = _config_path()
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return build_config(
            server_origin=obj.get("server_origin"),
            ca_cert_path=obj.get("ca_cert_path"),
            workstation_label=obj.get("workstation_label"),
        )
    except (ConfigError, ValueError, OSError):
        return None


def save_config_defaults(config: RunnerConfig) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "server_origin": config.server_origin,
        "ca_cert_path": str(config.ca_cert_path) if config.ca_cert_path else None,
        "workstation_label": config.workstation_label,
    }
    tmp = path.parent / f".{path.name}.tmp"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def run(config: RunnerConfig | None = None) -> int:
    mutex = create_single_instance_mutex(single_instance_mutex_name())
    try:
        mutex.acquire()
    except MutexAcquisitionError:
        _show_message_box(_APP_TITLE, _SINGLE_INSTANCE_MESSAGE)
        return 1

    try:
        try:
            return _run_with_mutex_held(config)
        except Exception:
            # Startup must fail closed and be VISIBLE: under pythonw a
            # raised exception has no console to print to and the process
            # just silently disappears. Never include the exception's text
            # (it could quote a path, a config value, or worse).
            _show_message_box(_APP_TITLE, _FATAL_STARTUP_MESSAGE)
            return 1
    finally:
        mutex.release()


def _run_with_mutex_held(config: RunnerConfig | None) -> int:
    logger = configure_logging(_local_app_data_dir() / "logs")
    log_event(logger, "startup")

    resolved_config = config or build_default_config_from_env() or RunnerConfig(
        server_origin="", ca_cert_path=None, workstation_label="",
    )
    identity_store = IdentityStore(default_identity_path(), select_production_crypto_backend())

    # Phase 1B-B: the workstation portal-session stack. session_store is a
    # SEPARATE encrypted file per MCMA account under its own subdirectory
    # (never the runner identity file, never the server's notification
    # vault -- see session_store.py's own docstring). perform_manual_login/
    # verify_saved_session are the reviewed mcma.portal functions, used
    # completely unchanged; this composition root injects them into the
    # browser worker as plain callables and never calls Playwright itself.
    session_store = WorkstationSessionStore(default_sessions_dir(), select_session_crypto_backend())
    session_manager = WorkstationSessionManager(has_saved_session=session_store.has_saved_session)
    verification_scheduler = VerificationScheduler()

    def client_factory(config: RunnerConfig) -> RegistryHttpClient:
        return RegistryHttpClient(config.server_origin, ca_cert_path=config.ca_cert_path)

    gui_app = RunnerApp()
    if resolved_config.server_origin:
        gui_app.prefill_form(resolved_config)

    def on_worker_update() -> None:
        controller._handle_worker_update()

    browser_worker = BrowserSessionWorker(
        session_manager=session_manager, session_store=session_store,
        perform_manual_login=perform_manual_login, verify_saved_session=verify_saved_session,
        on_update=on_worker_update,
    )

    def lifecycle_factory(client):
        return HeartbeatLifecycle(
            client, controller._handle_lifecycle_event,
            sessions_provider=controller._current_sessions,
            on_allowed_accounts=controller._handle_allowed_accounts,
        )

    controller = RunnerController(
        resolved_config, identity_store, client_factory, lifecycle_factory, gui_app._enqueue_status,
        on_config_saved=save_config_defaults, on_log=lambda event: log_event(logger, event),
        session_manager=session_manager, session_store=session_store, browser_worker=browser_worker,
        verification_scheduler=verification_scheduler, on_accounts_changed=gui_app._enqueue_accounts,
    )
    gui_app.bind_controller(controller)
    gui_app.run()
    log_event(logger, "shutdown")
    return 0


if __name__ == "__main__":  # pragma: no cover -- exercised via __main__.py
    sys.exit(run())
