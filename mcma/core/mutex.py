"""
mcma.core.mutex -- OS single-instance mutex (INC-11, ADR-0007).

The real single-writer guarantee for this application is an OS-level
guarantee: only one process may ever hold row-write capability, because
SinAuto itself does not validate any application-level fencing token
(DATA_MODEL.md §5's fencing caveat). `WindowsSingleInstanceMutex` is the
production implementation (a named Win32 mutex via `ctypes` -- no
`pywin32` dependency needed for this narrow use). `PortableTestOnlyMutex`
exists ONLY so this module's own behavior and callers can be exercised on
non-Windows CI; `create_single_instance_mutex()` refuses to hand it out
unless the caller explicitly opts in via the underscore-prefixed
test-only parameter, so no production code path can ever reach it by
omission.
"""

from __future__ import annotations

import sys
import threading


class MutexAcquisitionError(Exception):
    """Another holder already owns this named single-instance mutex."""


class WindowsSingleInstanceMutex:
    """Production single-instance guarantee: a named, global Win32 mutex.
    Held for the process lifetime (acquire once at service startup,
    release at shutdown). A second process requesting the same name
    fails to acquire -- Windows itself is the arbiter, not this process."""

    def __init__(self, name: str) -> None:
        self._name = f"Global\\{name}"
        self._handle = None
        self._kernel32 = None

    def acquire(self) -> None:
        import ctypes  # local import: ctypes.WinDLL only exists on Windows

        ERROR_ALREADY_EXISTS = 183
        # Fable-review correction: ctypes.windll.kernel32.GetLastError()
        # is unreliable -- ctypes' own machinery can make further Win32
        # calls between CreateMutexW and the GetLastError query,
        # clobbering the thread's last-error value, which would let a
        # missed ERROR_ALREADY_EXISTS make two processes both believe
        # they hold the mutex (the single-writer guarantee failing open).
        # WinDLL(..., use_last_error=True) + ctypes.get_last_error()
        # captures the error atomically as part of the same call.
        # CreateMutexW.restype is set to a proper (64-bit-safe) handle
        # type -- an untyped return defaults to c_int and can truncate
        # the handle on 64-bit Windows.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        handle = kernel32.CreateMutexW(None, False, self._name)
        last_error = ctypes.get_last_error()
        if not handle:
            raise MutexAcquisitionError(f"CreateMutexW failed for {self._name!r} (error {last_error})")
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            raise MutexAcquisitionError(f"another instance already holds mutex {self._name!r}")
        self._handle = handle
        self._kernel32 = kernel32

    def release(self) -> None:
        if self._handle is not None:
            import ctypes

            self._kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None

    def __enter__(self) -> "WindowsSingleInstanceMutex":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


class PortableTestOnlyMutex:
    """TEST-ONLY in-process single-instance guard for platforms without the
    Windows API. Never selectable in production -- see
    create_single_instance_mutex(). State is process-local (a class-level
    set), which is exactly what makes this unsuitable as a real
    cross-process guarantee; it exists only to exercise this module's
    contract in CI."""

    _lock = threading.Lock()
    _held_names: set = set()

    def __init__(self, name: str) -> None:
        self._name = name
        self._acquired = False

    def acquire(self) -> None:
        with PortableTestOnlyMutex._lock:
            if self._name in PortableTestOnlyMutex._held_names:
                raise MutexAcquisitionError(f"another holder already holds {self._name!r}")
            PortableTestOnlyMutex._held_names.add(self._name)
            self._acquired = True

    def release(self) -> None:
        with PortableTestOnlyMutex._lock:
            if self._acquired:
                PortableTestOnlyMutex._held_names.discard(self._name)
                self._acquired = False

    def __enter__(self) -> "PortableTestOnlyMutex":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


def create_single_instance_mutex(name: str, *, _test_only_portable_backend: bool = False):
    """The one factory production code calls. On Windows, always returns
    the real OS mutex. Off Windows, refuses by default -- a caller must
    explicitly pass `_test_only_portable_backend=True` (a name deliberately
    ugly enough that no production call site would pass it by accident) to
    receive the portable, non-authoritative test backend."""
    if sys.platform == "win32":
        return WindowsSingleInstanceMutex(name)
    if not _test_only_portable_backend:
        raise RuntimeError(
            "no OS single-instance mutex is available on this platform; "
            "the portable fallback is test-only and must be explicitly requested"
        )
    return PortableTestOnlyMutex(name)
