"""Test-only doubles. Never imported by mcma/app/workstation_runner itself --
production code always selects a real backend (identity.select_production_crypto_backend,
mcma.core.mutex.create_single_instance_mutex)."""

from __future__ import annotations

import threading


class InMemoryCryptoBackend:
    """A clearly-named, test-only stand-in for DPAPI. XORs with a fixed key
    so a corrupted/truncated/wrong-key ciphertext is detectable, without
    ever being mistaken for a real crypto primitive."""

    def __init__(self, key: bytes = b"test-only-key-not-secure") -> None:
        self._key = key

    def _xor(self, data: bytes) -> bytes:
        key = self._key
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def protect(self, data: bytes) -> bytes:
        return b"TESTBOX1:" + self._xor(data)

    def unprotect(self, data: bytes) -> bytes:
        prefix = b"TESTBOX1:"
        if not data.startswith(prefix):
            raise ValueError("not a value produced by InMemoryCryptoBackend")
        return self._xor(data[len(prefix):])


class WrongUserCryptoBackend(InMemoryCryptoBackend):
    """Simulates DPAPI CURRENT_USER decrypting a different Windows account's
    ciphertext: it always fails to unprotect, exactly like a real
    CryptUnprotectData call would for another user's blob."""

    def unprotect(self, data: bytes) -> bytes:
        raise ValueError("simulated wrong-user DPAPI failure")


class FakeClock:
    """Monotonic-clock double: .now advances only when told to."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeStopWaiter:
    """Replaces `threading.Event.wait` in tests: records requested delays,
    never actually sleeps, and lets a test signal "stop requested" on a
    chosen call."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self._stop_on_call: int | None = None
        self._event = threading.Event()

    def stop_on_next_wait(self) -> None:
        self._stop_on_call = len(self.waits)

    def stop_after(self, call_index: int) -> None:
        """Signal stop during the wait() call at this 0-based index (i.e.
        after call_index+1 wait() calls have been recorded)."""
        self._stop_on_call = call_index

    def __call__(self, event: threading.Event, timeout: float) -> bool:
        self.waits.append(timeout)
        if self._stop_on_call is not None and len(self.waits) - 1 >= self._stop_on_call:
            event.set()
        return event.is_set()
