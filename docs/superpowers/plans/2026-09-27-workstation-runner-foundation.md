# Windows Workstation Runner Foundation (Phase 1B-A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This run uses Native execution** (chosen by the requester: continue in the
> current session, no worktree, execute immediately). **Do not commit or
> push** — every task's "commit" step is replaced by "leave the change
> staged/unstaged; no `git commit`".

**Goal:** Build `mcma/app/workstation_runner/`, a standalone Windows
interactive-user GUI application (Tkinter) that pairs a workstation against
the central server's existing `/runner/enroll` + `/runner/heartbeat`
registry, persists its identity with DPAPI `CURRENT_USER`, and reports the
two MCMA accounts as `NOT_CONFIGURED` on a heartbeat loop. No browsers, no
MCMA login, no job dispatch, no installer/service/autostart in this phase.

**Architecture:** A small package under `mcma.app` (top layer, so it may use
`httpx`/`tkinter`/`mcma.core`, but must not reach into `mcma.execution`,
`mcma.persistence`, `mcma.portal`, or any legacy module). Business logic
(config validation, identity persistence, HTTP client, heartbeat state
machine, GUI controller) is plain Python with no Tkinter/`ctypes` calls
except at the narrow real-DPAPI/real-mutex/real-Tk edges, so everything else
is unit-testable headless. Wire-protocol constants are **duplicated as
literals** in a small `protocol.py` (mirroring
`mcma/app/runners/registry.py`) rather than imported from it — importing the
server registry module would pull in `mcma.app.auth.*` (which itself may
import `fastapi`/reach `mcma.persistence`), defeating the "this package
imports no FastAPI/SQLite/portal/execution code" isolation the spec
requires. The two copies are pinned to the same values and a comment in each
cross-references the other.

**Tech Stack:** Python ≥3.14 stdlib `tkinter`, `ctypes` (via existing
`mcma.core.dpapi` / `mcma.core.mutex`), `httpx==0.28.1` (already pinned,
unused elsewhere) for the HTTPS client, `logging.handlers.RotatingFileHandler`
for local logs, `threading`/`queue` for GUI/worker separation.

**Spec:** the requester's Phase 1B-A prompt (reproduced in full in this
session's transcript; not a separate file). Key wire facts confirmed against
`mcma/app/api/runners.py` and `mcma/app/runners/registry.py`:

- `POST /runner/enroll` — no auth. Body: `{"pairing_code": str, "runner_label"?: str, "protocol_version": 1, "app_version": str}` (extra/missing fields → 400). Success `201`: `{"runner_id", "runner_secret", "runner_label", "allowed_account_ids": [...], "heartbeat_interval_seconds", "offline_after_seconds", "server_time"}`. `runner_secret` = `"mcma_rs_" + urlsafe(32 bytes)`, ≤200 chars.
- `POST /runner/heartbeat` — `Authorization: Bearer <runner_secret>` only. Body: `{"protocol_version": 1, "app_version": str, "sessions": [{"account_id": str, "state": str}, ...]}`. Success `200`: `{"status": "ACTIVE", "server_time", "heartbeat_interval_seconds", "offline_after_seconds", "allowed_account_ids"}`. `401` on any invalid/unknown/revoked credential.
- Accounts: `("acct-mcma-oujda", "acct-mcma-nador")`. Session states: `("NOT_CONFIGURED", "LOGIN_REQUIRED", "READY", "ERROR")`. Protocol version: `{1}`. `app_version` regex: `^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$`.
- Error envelope (not to be parsed/shown): `{"error": code, "message": ..., "correlation_id": ...}` — the client only ever branches on HTTP status.

## Global Constraints

- Python ≥3.14, `uv`-managed; no new dependency may be added (spec: reuse `mcma.core.dpapi`, reuse the pinned HTTP dependency — `httpx` is already pinned and unused, so it is the one to use; no `pywin32`).
- Import layering (`pyproject.toml` `[tool.importlinter]`): `mcma.app` may import `fastapi`/anything below it, but `workstation_runner` must import **none** of `mcma.execution`, `mcma.persistence`, `mcma.portal`, `mcma.notifications`, `fastapi`, `sqlite3`, `playwright` — verified by a fresh-process import-proof test, not just convention.
- `mcma` must never import legacy baseline modules (`core`, `browser`, `mapper`, `main`, `mock_server`, `run_dossier`, `menu`, `trigger`, `auth_setup`, `session_keeper`, `get_notifications`, `garage_conventionne`, `testsupport`, `api`, `portal`, `workflows`, `tools`).
- Tests run under the egress lockdown (`pytest-socket`, loopback-only); all new tests must be pure/local — no real network. Real-Windows-only tests (DPAPI round-trip, real mutex) use the existing `skipif(sys.platform != "win32", reason="REAL_DPAPI_WINDOWS_ROUNDTRIP_PENDING_LOCAL_TEST: ...")` idiom from `tests/execution/jobs/test_inputs_dpapi_windows.py:14-21`.
- GUI must be French; no secret (pairing code, runner secret, Authorization header value) may ever reach disk, logs, exception text, URLs, process args, env vars, or `repr()`/debug output.
- `run_dossier.py` / INC-00 is untouched by this work; this package never imports it and never launches a browser.
- Do not modify, stage, or delete `Lancer_MCMA.cmd`, `Lancer_MCMA_Silencieux.vbs`, `MCMA_Ubuntu_Server_State_and_Deployment_Readiness_Report.md`.
- Do not commit or push.

## Review Focus

- **Corrupt/tampered ciphertext on disk** (bit-flipped, truncated, or a stray plaintext byte prepended) must fail closed to the pairing view, never raise an uncaught exception that crashes the app or (worse) get treated as valid after a partial parse.
- **Wrong-Windows-user ciphertext** (identity file copied from another account's LocalAppData) must fail closed exactly like corruption — DPAPI `CryptUnprotectData` itself refuses this, but the surrounding code must not treat the resulting exception as "no identity" vs. "corrupt identity" differently in a way that skips validation.
- **Server sends a 401 mid-heartbeat-loop** (association revoked from the admin UI while the runner is running) must stop the loop, wipe the local encrypted identity file, and return the GUI to the pairing view — not just log the error and keep retrying with a now-useless secret.
- **Closing the window while an enroll or heartbeat HTTP call is in flight** must not hang the process, corrupt the identity file (partial write), or raise from a Tkinter callback running after the window is destroyed.
- **A second launch while one instance already holds the mutex** must show the fixed French message and exit `0`/cleanly without ever starting a second heartbeat thread or opening a second identity file handle — tested by injecting the same test-only mutex backend across two controller instances in one process.

---

## File Structure

```
mcma/app/workstation_runner/
  __init__.py         one-line docstring only (matches mcma/app/runners/__init__.py convention)
  protocol.py          wire-protocol constants mirrored from mcma.app.runners.registry (literals, no import)
  config.py            RunnerConfig dataclass + validation (server origin, CA cert path, workstation label)
  identity.py          RunnerIdentity envelope, CryptoBackend protocol, DPAPI production backend, atomic
                        encrypted persistence, fail-closed validation
  http_client.py        RegistryHttpClient: enroll()/heartbeat() over httpx, origin/response validation,
                        no-cookie/no-redirect/no-proxy/bounded-timeout enforcement
  heartbeat.py          HeartbeatLifecycle (state machine) + HeartbeatWorker (thread wrapper)
  logging_setup.py      bounded rotating file logger + safe event-logging helpers (fixed messages only)
  controller.py         RunnerController: pure Python state machine tying config/identity/http/heartbeat
                        together; drives the GUI via a callback + a Queue, no Tkinter import
  gui.py                Tkinter views (PairingFrame, StatusFrame, RunnerApp) — thin, delegates to controller
  app.py                composition root: builds real backends, acquires the single-instance mutex, runs
                        the Tk mainloop, handles shutdown
  __main__.py           `python -m mcma.app.workstation_runner` entry point (also pythonw-safe)

tests/app/workstation_runner/
  __init__.py
  _fakes.py             test-only fakes: InMemoryCryptoBackend, FakeClock, a queue-backed fake transport
  test_config.py
  test_identity.py
  test_identity_dpapi_windows.py     (skipif not win32 — real DPAPI round trip + restart recovery)
  test_http_client.py
  test_heartbeat.py
  test_controller.py
  test_app_single_instance.py
  test_import_isolation.py          (fresh-process import proof, subprocess-based like
                                      tests/contracts/test_import_boundaries.py)

docs/architecture/CENTRAL_SERVER_DEPLOYMENT.md   append a new section documenting Phase 1B-A
```

---

### Task 1: Package skeleton, protocol constants, config validation

**Files:**
- Create: `mcma/app/workstation_runner/__init__.py`
- Create: `mcma/app/workstation_runner/protocol.py`
- Create: `mcma/app/workstation_runner/config.py`
- Test: `tests/app/workstation_runner/__init__.py`
- Test: `tests/app/workstation_runner/test_config.py`

**Interfaces:**
- Produces: `protocol.PROTOCOL_VERSION: int`, `protocol.APP_VERSION: str`, `protocol.RUNNER_ACCOUNT_IDS: tuple[str, ...]`, `protocol.SESSION_STATE_NOT_CONFIGURED: str`, `protocol.RUNNER_SECRET_PREFIX: str`, `protocol.MAX_RUNNER_SECRET_LENGTH: int`, `protocol.MIN_HEARTBEAT_INTERVAL_SECONDS/MAX_HEARTBEAT_INTERVAL_SECONDS`, `protocol.MIN_OFFLINE_AFTER_SECONDS/MAX_OFFLINE_AFTER_SECONDS`.
- Produces: `config.RunnerConfig` (frozen dataclass: `server_origin: str`, `ca_cert_path: Path | None`, `workstation_label: str`), `config.ConfigError(Exception)`, `config.validate_server_origin(raw: str) -> str`, `config.validate_workstation_label(raw: str) -> str`, `config.build_config(*, server_origin, ca_cert_path, workstation_label) -> RunnerConfig`.

- [ ] **Step 1: Write `protocol.py`**

```python
"""mcma.app.workstation_runner.protocol -- wire-protocol constants for the
central runner registry (mcma/app/api/runners.py + mcma/app/runners/registry.py).

Deliberately duplicated as literals rather than imported from
mcma.app.runners.registry: that module pulls in mcma.app.auth.* (which may
reach fastapi / mcma.persistence), which would break this package's
"imports no server/FastAPI/SQLite code" isolation (see
tests/app/workstation_runner/test_import_isolation.py). Keep these values
byte-for-byte identical to the server's; a mismatch is a protocol bug."""

from __future__ import annotations

PROTOCOL_VERSION = 1
APP_VERSION = "1.0.0"  # must match ^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$

# mirrors mcma.app.runners.registry.RUNNER_ACCOUNT_IDS
RUNNER_ACCOUNT_IDS = ("acct-mcma-oujda", "acct-mcma-nador")

# mirrors mcma.app.runners.registry.SESSION_STATES -- this phase only ever reports NOT_CONFIGURED
SESSION_STATE_NOT_CONFIGURED = "NOT_CONFIGURED"

# mirrors mcma.app.runners.registry.RUNNER_SECRET_PREFIX / MAX_RUNNER_SECRET_LENGTH
RUNNER_SECRET_PREFIX = "mcma_rs_"
MAX_RUNNER_SECRET_LENGTH = 200

# sane bounds for server-provided scheduling values -- never trust the
# network to hand us 0, a negative number, or something absurdly large
MIN_HEARTBEAT_INTERVAL_SECONDS = 1
MAX_HEARTBEAT_INTERVAL_SECONDS = 3600
MIN_OFFLINE_AFTER_SECONDS = 1
MAX_OFFLINE_AFTER_SECONDS = 7200
```

- [ ] **Step 2: Write the failing config tests**

```python
# tests/app/workstation_runner/test_config.py
import pytest
from pathlib import Path

from mcma.app.workstation_runner.config import (
    ConfigError, build_config, validate_server_origin, validate_workstation_label,
)


@pytest.mark.parametrize("raw,expected", [
    ("https://central.example.local", "https://central.example.local"),
    ("https://central.example.local/", "https://central.example.local"),
    ("https://central.example.local:8443", "https://central.example.local:8443"),
])
def test_validate_server_origin_accepts_bare_https_origin(raw, expected):
    assert validate_server_origin(raw) == expected


@pytest.mark.parametrize("raw", [
    "http://central.example.local",                       # not https
    "https://user:pass@central.example.local",             # embedded credentials
    "https://central.example.local/runner",                # unexpected path
    "https://central.example.local?x=1",                   # query string
    "https://central.example.local#frag",                  # fragment
    "not a url",
    "",
    "ftp://central.example.local",
])
def test_validate_server_origin_rejects_everything_else(raw):
    with pytest.raises(ConfigError):
        validate_server_origin(raw)


def test_validate_workstation_label_trims_and_accepts():
    assert validate_workstation_label(" Poste-1 ") == "Poste-1"


@pytest.mark.parametrize("raw", ["", "   ", "x" * 41, "bad;label"])
def test_validate_workstation_label_rejects_invalid(raw):
    with pytest.raises(ConfigError):
        validate_workstation_label(raw)


def test_build_config_accepts_missing_ca_cert():
    cfg = build_config(server_origin="https://central.example.local", ca_cert_path=None, workstation_label="Poste-1")
    assert cfg.server_origin == "https://central.example.local"
    assert cfg.ca_cert_path is None
    assert cfg.workstation_label == "Poste-1"


def test_build_config_rejects_nonexistent_ca_cert(tmp_path: Path):
    with pytest.raises(ConfigError):
        build_config(
            server_origin="https://central.example.local",
            ca_cert_path=tmp_path / "missing.pem",
            workstation_label="Poste-1",
        )
```

- [ ] **Step 3: Run to verify failure** — `python -m pytest tests/app/workstation_runner/test_config.py -v` → `ModuleNotFoundError: mcma.app.workstation_runner.config`.

- [ ] **Step 4: Write `config.py`**

```python
"""mcma.app.workstation_runner.config -- validated local configuration for
the pairing GUI. Everything a human can type into the pairing form is
validated here before it touches the network or the filesystem."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(Exception):
    """A fixed, French-safe validation failure. The caller decides the
    exact French text shown in the GUI; this carries only a stable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$")  # mirrors registry._LABEL_RE


def validate_server_origin(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        raise ConfigError("SERVER_ORIGIN_INVALID") from None
    if parts.scheme != "https":
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if not parts.hostname:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if parts.username or parts.password:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if parts.query or parts.fragment:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if parts.path not in ("", "/"):
        raise ConfigError("SERVER_ORIGIN_INVALID")
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"https://{netloc}"


def validate_workstation_label(raw: object) -> str:
    if not isinstance(raw, str):
        raise ConfigError("WORKSTATION_LABEL_INVALID")
    trimmed = raw.strip()
    if not _LABEL_RE.match(trimmed):
        raise ConfigError("WORKSTATION_LABEL_INVALID")
    return trimmed


@dataclass(frozen=True)
class RunnerConfig:
    server_origin: str
    ca_cert_path: Path | None
    workstation_label: str


def build_config(*, server_origin: object, ca_cert_path: object, workstation_label: object) -> RunnerConfig:
    origin = validate_server_origin(server_origin)
    label = validate_workstation_label(workstation_label)
    cert_path: Path | None = None
    if ca_cert_path:
        cert_path = Path(ca_cert_path)
        if not cert_path.is_file():
            raise ConfigError("CA_CERT_NOT_FOUND")
    return RunnerConfig(server_origin=origin, ca_cert_path=cert_path, workstation_label=label)
```

- [ ] **Step 5: Run to verify pass** — `python -m pytest tests/app/workstation_runner/test_config.py -v` → all PASS.

- [ ] **Step 6 (no commit):** leave the files as-is; this repo's instruction for this task is "do not commit or push".

---

### Task 2: Identity envelope + DPAPI-protected persistence

**Files:**
- Create: `mcma/app/workstation_runner/identity.py`
- Create: `tests/app/workstation_runner/_fakes.py`
- Test: `tests/app/workstation_runner/test_identity.py`

**Interfaces:**
- Consumes: `protocol.RUNNER_ACCOUNT_IDS`, `protocol.RUNNER_SECRET_PREFIX`, `protocol.MAX_RUNNER_SECRET_LENGTH` (Task 1); `mcma.core.dpapi.{protect, unprotect, DpapiScope, DpapiUnavailable, is_available}`.
- Produces: `identity.RunnerIdentity` (frozen dataclass: `format_version: int`, `server_origin: str`, `runner_id: str`, `runner_secret: str`, `allowed_account_ids: tuple[str, ...]`), `identity.IDENTITY_FORMAT_VERSION = 1`, `identity.CryptoBackend` (a `typing.Protocol` with `protect(data: bytes) -> bytes` / `unprotect(data: bytes) -> bytes`), `identity.DpapiCurrentUserBackend` (real backend), `identity.select_production_crypto_backend() -> CryptoBackend` (raises `RuntimeError` off Windows), `identity.IdentityStore(path: Path, backend: CryptoBackend)` with `.load(*, expected_server_origin: str) -> RunnerIdentity | None` and `.save(identity: RunnerIdentity) -> None` and `.clear() -> None`, `identity.default_identity_path() -> Path` (returns `%LOCALAPPDATA%/MCMA Runner/identity.bin`, raising `RuntimeError` if `LOCALAPPDATA` is unset).

- [ ] **Step 1: Write the test-only fakes**

```python
# tests/app/workstation_runner/_fakes.py
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

    def __call__(self, event: threading.Event, timeout: float) -> bool:
        self.waits.append(timeout)
        if self._stop_on_call is not None and len(self.waits) - 1 >= self._stop_on_call:
            event.set()
        return event.is_set()
```

- [ ] **Step 2: Write the failing identity tests**

```python
# tests/app/workstation_runner/test_identity.py
import pytest

from mcma.app.workstation_runner.identity import (
    IDENTITY_FORMAT_VERSION, IdentityStore, RunnerIdentity, select_production_crypto_backend,
)
from tests.app.workstation_runner._fakes import InMemoryCryptoBackend, WrongUserCryptoBackend

ORIGIN = "https://central.example.local"


def _identity(**overrides) -> RunnerIdentity:
    base = dict(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN,
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40,
        allowed_account_ids=("acct-mcma-oujda",),
    )
    base.update(overrides)
    return RunnerIdentity(**base)


def test_save_then_load_round_trips(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())
    identity = _identity()
    store.save(identity)
    loaded = store.load(expected_server_origin=ORIGIN)
    assert loaded == identity


def test_load_missing_file_returns_none(tmp_path):
    store = IdentityStore(tmp_path / "missing.bin", InMemoryCryptoBackend())
    assert store.load(expected_server_origin=ORIGIN) is None


def test_save_is_atomic_no_tmp_file_left_behind(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())
    store.save(_identity())
    leftovers = [p for p in tmp_path.iterdir() if p.name != "identity.bin"]
    assert leftovers == []


def test_save_never_writes_plaintext_secret(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())
    store.save(_identity(runner_secret="mcma_rs_" + "s3cr3t-marker" + "z" * 20))
    raw = (tmp_path / "identity.bin").read_bytes()
    assert b"s3cr3t-marker" not in raw


@pytest.mark.parametrize("corrupt", [
    lambda b: b[:-5],                      # truncated
    lambda b: b[:10] + b"\xff" * 10 + b[20:],  # bit-flipped middle
    lambda b: b"not even our format" + b,   # prefixed garbage
    lambda b: b"",                          # empty
])
def test_load_fails_closed_on_corrupt_ciphertext(tmp_path, corrupt):
    path = tmp_path / "identity.bin"
    store = IdentityStore(path, InMemoryCryptoBackend())
    store.save(_identity())
    path.write_bytes(corrupt(path.read_bytes()))
    assert store.load(expected_server_origin=ORIGIN) is None


def test_load_fails_closed_on_wrong_user_backend(tmp_path):
    path = tmp_path / "identity.bin"
    IdentityStore(path, InMemoryCryptoBackend()).save(_identity())
    reader = IdentityStore(path, WrongUserCryptoBackend())
    assert reader.load(expected_server_origin=ORIGIN) is None


def test_load_fails_closed_on_server_origin_mismatch(tmp_path):
    path = tmp_path / "identity.bin"
    IdentityStore(path, InMemoryCryptoBackend()).save(_identity(server_origin=ORIGIN))
    store = IdentityStore(path, InMemoryCryptoBackend())
    assert store.load(expected_server_origin="https://other.example.local") is None


def test_load_fails_closed_on_wrong_format_version(tmp_path):
    path = tmp_path / "identity.bin"
    backend = InMemoryCryptoBackend()
    IdentityStore(path, backend).save(_identity(format_version=999))
    assert IdentityStore(path, backend).load(expected_server_origin=ORIGIN) is None


@pytest.mark.parametrize("bad_secret", ["", "not-prefixed", "mcma_rs_" + "x" * 300])
def test_load_fails_closed_on_invalid_secret_shape(tmp_path, bad_secret):
    path = tmp_path / "identity.bin"
    backend = InMemoryCryptoBackend()
    IdentityStore(path, backend).save(_identity(runner_secret=bad_secret))
    assert IdentityStore(path, backend).load(expected_server_origin=ORIGIN) is None


def test_load_fails_closed_on_disallowed_account_id(tmp_path):
    path = tmp_path / "identity.bin"
    backend = InMemoryCryptoBackend()
    IdentityStore(path, backend).save(_identity(allowed_account_ids=("acct-mamda",)))
    assert IdentityStore(path, backend).load(expected_server_origin=ORIGIN) is None


def test_clear_removes_the_file(tmp_path):
    path = tmp_path / "identity.bin"
    store = IdentityStore(path, InMemoryCryptoBackend())
    store.save(_identity())
    store.clear()
    assert not path.exists()
    store.clear()  # idempotent


def test_clear_on_missing_file_is_a_noop(tmp_path):
    IdentityStore(tmp_path / "missing.bin", InMemoryCryptoBackend()).clear()


def test_select_production_crypto_backend_refuses_off_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(RuntimeError):
        select_production_crypto_backend()
```

- [ ] **Step 3: Run to verify failure.** `python -m pytest tests/app/workstation_runner/test_identity.py -v` → collection/import errors.

- [ ] **Step 4: Write `identity.py`**

```python
"""mcma.app.workstation_runner.identity -- DPAPI CURRENT_USER-protected
runner identity persistence.

Fail-closed by construction: IdentityStore.load() returns None for a
missing file, a corrupt/truncated/altered ciphertext, a ciphertext DPAPI
cannot decrypt for this Windows account, a wrong format version, a
server-origin mismatch, or any structurally invalid field -- there is no
code path that returns a partially-trusted identity. Never falls back to
plaintext, base64, or LOCAL_MACHINE scope: mcma.core.dpapi.DpapiScope.CURRENT_USER
is the only production scope this module will ever select."""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mcma.app.workstation_runner.protocol import (
    MAX_RUNNER_SECRET_LENGTH, RUNNER_ACCOUNT_IDS, RUNNER_SECRET_PREFIX,
)
from mcma.core.dpapi import DpapiScope, DpapiUnavailable, protect, unprotect

IDENTITY_FORMAT_VERSION = 1

_RUNNER_ID_RE_LEN = 32  # uuid.uuid4().hex, matches mcma.app.runners.registry


@dataclass(frozen=True)
class RunnerIdentity:
    format_version: int
    server_origin: str
    runner_id: str
    runner_secret: str
    allowed_account_ids: tuple  # tuple[str, ...]


class CryptoBackend(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class DpapiCurrentUserBackend:
    """The only production CryptoBackend. No LOCAL_MACHINE option is
    exposed here -- runner identity is per-employee, per-account."""

    def protect(self, data: bytes) -> bytes:
        return protect(data, DpapiScope.CURRENT_USER)

    def unprotect(self, data: bytes) -> bytes:
        return unprotect(data, DpapiScope.CURRENT_USER)


def select_production_crypto_backend() -> CryptoBackend:
    if sys.platform != "win32":
        raise RuntimeError(
            "the workstation runner requires Windows DPAPI CURRENT_USER; "
            "no fallback backend exists in production"
        )
    return DpapiCurrentUserBackend()


def default_identity_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set; cannot locate the identity store")
    return Path(local_app_data) / "MCMA Runner" / "identity.bin"


def _valid_runner_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _RUNNER_ID_RE_LEN
        and all(c in "0123456789abcdef" for c in value)
    )


def _valid_runner_secret(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(RUNNER_SECRET_PREFIX)
        and len(RUNNER_SECRET_PREFIX) < len(value) <= MAX_RUNNER_SECRET_LENGTH
    )


def _valid_account_ids(value: object) -> bool:
    if not isinstance(value, list) or len(value) > len(RUNNER_ACCOUNT_IDS):
        return False
    if len(set(value)) != len(value):
        return False
    return all(isinstance(a, str) and a in RUNNER_ACCOUNT_IDS for a in value)


def _parse_envelope(raw: bytes, *, expected_server_origin: str) -> RunnerIdentity | None:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("format_version") != IDENTITY_FORMAT_VERSION:
        return None
    if obj.get("server_origin") != expected_server_origin:
        return None
    if not _valid_runner_id(obj.get("runner_id")):
        return None
    if not _valid_runner_secret(obj.get("runner_secret")):
        return None
    if not _valid_account_ids(obj.get("allowed_account_ids")):
        return None
    return RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION,
        server_origin=expected_server_origin,
        runner_id=obj["runner_id"],
        runner_secret=obj["runner_secret"],
        allowed_account_ids=tuple(obj["allowed_account_ids"]),
    )


class IdentityStore:
    def __init__(self, path: Path, backend: CryptoBackend) -> None:
        self._path = Path(path)
        self._backend = backend

    def load(self, *, expected_server_origin: str) -> RunnerIdentity | None:
        try:
            ciphertext = self._path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return None  # unreadable is as good as missing -- fail closed
        try:
            plaintext = self._backend.unprotect(ciphertext)
        except (DpapiUnavailable, ValueError, TypeError, OSError):
            return None  # corrupt, wrong-user, or backend-refused -- fail closed
        return _parse_envelope(plaintext, expected_server_origin=expected_server_origin)

    def save(self, identity: RunnerIdentity) -> None:
        payload = json.dumps({
            "format_version": identity.format_version,
            "server_origin": identity.server_origin,
            "runner_id": identity.runner_id,
            "runner_secret": identity.runner_secret,
            "allowed_account_ids": list(identity.allowed_account_ids),
        }).encode("utf-8")
        ciphertext = self._backend.protect(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.parent / f".{uuid.uuid4().hex}.identity.tmp"
        tmp_path.write_bytes(ciphertext)
        os.replace(tmp_path, self._path)  # atomic on the same filesystem, same dir as vault.py's pattern

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
```

- [ ] **Step 5: Run to verify pass.** `python -m pytest tests/app/workstation_runner/test_identity.py -v` → all PASS.

---

### Task 3: Real Windows DPAPI round-trip test

**Files:**
- Test: `tests/app/workstation_runner/test_identity_dpapi_windows.py`

**Interfaces:**
- Consumes: `identity.{IdentityStore, RunnerIdentity, IDENTITY_FORMAT_VERSION, DpapiCurrentUserBackend, select_production_crypto_backend}` (Task 2).

- [ ] **Step 1: Write the test file**

```python
# tests/app/workstation_runner/test_identity_dpapi_windows.py
"""Real Windows DPAPI CURRENT_USER round trip -- no fake backend. Mirrors
the skip idiom in tests/execution/jobs/test_inputs_dpapi_windows.py:14-21."""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="REAL_DPAPI_WINDOWS_ROUNDTRIP_PENDING_LOCAL_TEST: Windows DPAPI only",
)

from mcma.app.workstation_runner.identity import (
    IDENTITY_FORMAT_VERSION, DpapiCurrentUserBackend, IdentityStore, RunnerIdentity,
    select_production_crypto_backend,
)

ORIGIN = "https://central.example.local"


def _identity() -> RunnerIdentity:
    return RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN,
        runner_id="f" * 32, runner_secret="mcma_rs_" + "r" * 40,
        allowed_account_ids=("acct-mcma-oujda", "acct-mcma-nador"),
    )


def test_real_dpapi_round_trip(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", DpapiCurrentUserBackend())
    identity = _identity()
    store.save(identity)
    assert store.load(expected_server_origin=ORIGIN) == identity


def test_real_dpapi_ciphertext_is_not_plaintext_json(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", DpapiCurrentUserBackend())
    store.save(_identity())
    raw = (tmp_path / "identity.bin").read_bytes()
    assert b"mcma_rs_" not in raw
    assert b"runner_secret" not in raw


def test_restart_recovery_reopens_a_fresh_store_instance(tmp_path):
    path = tmp_path / "identity.bin"
    IdentityStore(path, DpapiCurrentUserBackend()).save(_identity())
    # simulate process restart: a brand-new IdentityStore object, same file
    reopened = IdentityStore(path, DpapiCurrentUserBackend())
    assert reopened.load(expected_server_origin=ORIGIN) == _identity()


def test_select_production_crypto_backend_returns_real_dpapi_on_windows():
    backend = select_production_crypto_backend()
    assert isinstance(backend, DpapiCurrentUserBackend)
```

- [ ] **Step 2: Run on this Windows machine.** `python -m pytest tests/app/workstation_runner/test_identity_dpapi_windows.py -v` → all PASS (this machine is Windows 11, so the skip does not trigger).

---

### Task 4: HTTPS registry client

**Files:**
- Create: `mcma/app/workstation_runner/http_client.py`
- Test: `tests/app/workstation_runner/test_http_client.py`

**Interfaces:**
- Consumes: `protocol.{PROTOCOL_VERSION, APP_VERSION, RUNNER_ACCOUNT_IDS, SESSION_STATE_NOT_CONFIGURED, RUNNER_SECRET_PREFIX, MAX_RUNNER_SECRET_LENGTH, MIN_HEARTBEAT_INTERVAL_SECONDS, MAX_HEARTBEAT_INTERVAL_SECONDS, MIN_OFFLINE_AFTER_SECONDS, MAX_OFFLINE_AFTER_SECONDS}` (Task 1).
- Produces: `http_client.RegistryConnectionError`, `http_client.RegistryUnauthorized`, `http_client.RegistryProtocolError` (all `Exception` subclasses, fixed messages only), `http_client.EnrollResult` (frozen dataclass: `runner_id, runner_secret, runner_label, allowed_account_ids: tuple, heartbeat_interval_seconds: int, offline_after_seconds: int`), `http_client.HeartbeatResult` (frozen dataclass: `status: str, heartbeat_interval_seconds: int, offline_after_seconds: int, allowed_account_ids: tuple`), `http_client.RegistryHttpClient(server_origin: str, *, ca_cert_path: Path | None = None, transport=None)` with `.enroll(pairing_code: str, *, workstation_label: str) -> EnrollResult`, `.heartbeat(runner_secret: str, *, allowed_account_ids: tuple) -> HeartbeatResult`, `.close() -> None`. `transport` accepts an `httpx.BaseTransport` (tests inject `httpx.MockTransport`).

- [ ] **Step 1: Write the failing HTTP client tests**

```python
# tests/app/workstation_runner/test_http_client.py
import httpx
import pytest

from mcma.app.workstation_runner.http_client import (
    RegistryConnectionError, RegistryHttpClient, RegistryProtocolError, RegistryUnauthorized,
)

ORIGIN = "https://central.example.local"


def _client(handler, **kwargs):
    return RegistryHttpClient(ORIGIN, transport=httpx.MockTransport(handler), **kwargs)


def test_enroll_success_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/runner/enroll"
        body = httpx.Request.read(request)
        import json
        payload = json.loads(body)
        assert payload == {
            "pairing_code": "mcma_pc_abc", "runner_label": "Poste-1",
            "protocol_version": 1, "app_version": "1.0.0",
        }
        return httpx.Response(201, json={
            "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40,
            "runner_label": "Poste-1", "allowed_account_ids": ["acct-mcma-oujda"],
            "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
            "server_time": "2026-01-01T00:00:00+00:00",
        })

    client = _client(handler)
    result = client.enroll("mcma_pc_abc", workstation_label="Poste-1")
    assert result.runner_id == "a" * 32
    assert result.runner_secret == "mcma_rs_" + "b" * 40
    assert result.allowed_account_ids == ("acct-mcma-oujda",)
    assert result.heartbeat_interval_seconds == 10


def test_enroll_never_sends_pairing_code_in_url_or_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(201, json={
            "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40,
            "runner_label": "Poste-1", "allowed_account_ids": [],
            "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
            "server_time": "2026-01-01T00:00:00+00:00",
        })

    client = _client(handler)
    client.enroll("mcma_pc_super-secret", workstation_label="Poste-1")
    assert "super-secret" not in seen["url"]
    assert "super-secret" not in "".join(seen["headers"].values())
    assert "authorization" not in seen["headers"]


def test_enroll_non_201_raises_protocol_error():
    client = _client(lambda r: httpx.Response(400, json={"error": "PAIRING_CODE_INVALID"}))
    with pytest.raises(RegistryProtocolError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


def test_enroll_connection_failure_raises_connection_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(RegistryConnectionError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


@pytest.mark.parametrize("bad_response", [
    {"runner_id": "not-hex!!", "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
     "allowed_account_ids": [], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
     "server_time": "t"},
    {"runner_id": "a" * 32, "runner_secret": "no-prefix", "runner_label": "x",
     "allowed_account_ids": [], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
     "server_time": "t"},
    {"runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
     "allowed_account_ids": ["acct-mamda"], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
     "server_time": "t"},
    {"runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
     "allowed_account_ids": [], "heartbeat_interval_seconds": 0, "offline_after_seconds": 30,
     "server_time": "t"},
])
def test_enroll_rejects_out_of_bounds_response(bad_response):
    client = _client(lambda r: httpx.Response(201, json=bad_response))
    with pytest.raises(RegistryProtocolError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


def test_heartbeat_sends_bearer_header_and_not_configured_sessions():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        import json
        seen["body"] = json.loads(httpx.Request.read(request))
        return httpx.Response(200, json={
            "status": "ACTIVE", "server_time": "t", "heartbeat_interval_seconds": 10,
            "offline_after_seconds": 30, "allowed_account_ids": ["acct-mcma-oujda"],
        })

    client = _client(handler)
    result = client.heartbeat("mcma_rs_" + "s" * 40, allowed_account_ids=("acct-mcma-oujda",))
    assert seen["auth"] == "Bearer mcma_rs_" + "s" * 40
    assert seen["body"]["sessions"] == [{"account_id": "acct-mcma-oujda", "state": "NOT_CONFIGURED"}]
    assert result.status == "ACTIVE"


def test_heartbeat_401_raises_unauthorized():
    client = _client(lambda r: httpx.Response(401, json={"error": "RUNNER_UNAUTHENTICATED"}))
    with pytest.raises(RegistryUnauthorized):
        client.heartbeat("mcma_rs_" + "s" * 40, allowed_account_ids=())


def test_enroll_does_not_persist_cookies_across_calls():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("cookie"))
        headers = {"Set-Cookie": "sid=abc; Path=/"} if len(calls) == 1 else {}
        return httpx.Response(201, json={
            "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
            "allowed_account_ids": [], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
            "server_time": "t",
        }, headers=headers)

    client = _client(handler)
    client.enroll("mcma_pc_x", workstation_label="Poste-1")
    client.enroll("mcma_pc_y", workstation_label="Poste-1")
    assert calls == [None, None]


def test_client_disables_redirects():
    client = RegistryHttpClient(ORIGIN)
    assert client._client.follow_redirects is False


def test_client_disables_environment_proxy_trust():
    client = RegistryHttpClient(ORIGIN)
    assert client._client._trust_env is False


def test_client_rejects_non_https_origin():
    with pytest.raises(ValueError):
        RegistryHttpClient("http://central.example.local")


def test_client_rejects_ca_cert_that_does_not_exist(tmp_path):
    with pytest.raises(ValueError):
        RegistryHttpClient(ORIGIN, ca_cert_path=tmp_path / "missing.pem")
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `http_client.py`**

```python
"""mcma.app.workstation_runner.http_client -- the ONLY place this package
speaks HTTP. Bearer secret only ever appears in the Authorization header of
/runner/heartbeat; pairing code only ever appears in the JSON body of
/runner/enroll. Never logs a request/response body, header, or raw
transport exception text -- callers get one of three typed, fixed-message
exceptions and decide what (fixed, French) text to show."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from mcma.app.workstation_runner.protocol import (
    APP_VERSION, MAX_HEARTBEAT_INTERVAL_SECONDS, MAX_OFFLINE_AFTER_SECONDS,
    MAX_RUNNER_SECRET_LENGTH, MIN_HEARTBEAT_INTERVAL_SECONDS, MIN_OFFLINE_AFTER_SECONDS,
    PROTOCOL_VERSION, RUNNER_ACCOUNT_IDS, RUNNER_SECRET_PREFIX, SESSION_STATE_NOT_CONFIGURED,
)

_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 10.0
_WRITE_TIMEOUT = 5.0
_POOL_TIMEOUT = 5.0

_RUNNER_ID_LEN = 32


class RegistryConnectionError(Exception):
    """Network/DNS/TLS-handshake/timeout failure -- never carries the
    underlying exception's text."""


class RegistryUnauthorized(Exception):
    """The server returned 401: the credential is no longer valid."""


class RegistryProtocolError(Exception):
    """An unexpected status code or a response that failed validation --
    never carries the response body."""


@dataclass(frozen=True)
class EnrollResult:
    runner_id: str
    runner_secret: str
    runner_label: str
    allowed_account_ids: tuple
    heartbeat_interval_seconds: int
    offline_after_seconds: int


@dataclass(frozen=True)
class HeartbeatResult:
    status: str
    heartbeat_interval_seconds: int
    offline_after_seconds: int
    allowed_account_ids: tuple


def _validate_origin(server_origin: str) -> str:
    parts = urlsplit(server_origin)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("server_origin must be a bare https:// origin")
    if parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("server_origin must be a bare https:// origin")
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"https://{netloc}"


def _valid_runner_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == _RUNNER_ID_LEN and all(c in "0123456789abcdef" for c in value)


def _valid_secret(value: object) -> bool:
    return isinstance(value, str) and value.startswith(RUNNER_SECRET_PREFIX) and len(value) <= MAX_RUNNER_SECRET_LENGTH


def _valid_account_ids(value: object) -> tuple | None:
    if not isinstance(value, list) or len(value) > len(RUNNER_ACCOUNT_IDS):
        return None
    if len(set(value)) != len(value) or not all(isinstance(a, str) and a in RUNNER_ACCOUNT_IDS for a in value):
        return None
    return tuple(value)


def _valid_bounded_int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


class RegistryHttpClient:
    def __init__(self, server_origin: str, *, ca_cert_path: Path | None = None, transport: httpx.BaseTransport | None = None) -> None:
        origin = _validate_origin(server_origin)
        if ca_cert_path is not None and not Path(ca_cert_path).is_file():
            raise ValueError("ca_cert_path does not exist")
        verify = str(ca_cert_path) if ca_cert_path is not None else True
        self._client = httpx.Client(
            base_url=origin,
            verify=verify,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=_WRITE_TIMEOUT, pool=_POOL_TIMEOUT),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RegistryHttpClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _post(self, path: str, *, json_body: dict, headers: dict | None = None) -> dict:
        try:
            response = self._client.post(path, json=json_body, headers=headers or {})
        except httpx.HTTPError:
            raise RegistryConnectionError("unreachable") from None
        finally:
            self._client.cookies.clear()  # never let a Set-Cookie survive to the next call
        if response.status_code == 401:
            raise RegistryUnauthorized("credential rejected")
        if response.status_code not in (200, 201):
            raise RegistryProtocolError(f"unexpected status {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise RegistryProtocolError("response was not valid JSON") from None

    def enroll(self, pairing_code: str, *, workstation_label: str) -> EnrollResult:
        body = self._post("/runner/enroll", json_body={
            "pairing_code": pairing_code,
            "runner_label": workstation_label,
            "protocol_version": PROTOCOL_VERSION,
            "app_version": APP_VERSION,
        })
        if (
            not _valid_runner_id(body.get("runner_id"))
            or not _valid_secret(body.get("runner_secret"))
            or not isinstance(body.get("runner_label"), str)
            or (accounts := _valid_account_ids(body.get("allowed_account_ids"))) is None
            or not _valid_bounded_int(body.get("heartbeat_interval_seconds"), MIN_HEARTBEAT_INTERVAL_SECONDS, MAX_HEARTBEAT_INTERVAL_SECONDS)
            or not _valid_bounded_int(body.get("offline_after_seconds"), MIN_OFFLINE_AFTER_SECONDS, MAX_OFFLINE_AFTER_SECONDS)
        ):
            raise RegistryProtocolError("enroll response failed validation")
        return EnrollResult(
            runner_id=body["runner_id"], runner_secret=body["runner_secret"],
            runner_label=body["runner_label"], allowed_account_ids=accounts,
            heartbeat_interval_seconds=body["heartbeat_interval_seconds"],
            offline_after_seconds=body["offline_after_seconds"],
        )

    def heartbeat(self, runner_secret: str, *, allowed_account_ids: tuple) -> HeartbeatResult:
        sessions = [{"account_id": a, "state": SESSION_STATE_NOT_CONFIGURED} for a in allowed_account_ids]
        body = self._post(
            "/runner/heartbeat",
            json_body={"protocol_version": PROTOCOL_VERSION, "app_version": APP_VERSION, "sessions": sessions},
            headers={"Authorization": f"Bearer {runner_secret}"},
        )
        if (
            body.get("status") != "ACTIVE"
            or (accounts := _valid_account_ids(body.get("allowed_account_ids"))) is None
            or not _valid_bounded_int(body.get("heartbeat_interval_seconds"), MIN_HEARTBEAT_INTERVAL_SECONDS, MAX_HEARTBEAT_INTERVAL_SECONDS)
            or not _valid_bounded_int(body.get("offline_after_seconds"), MIN_OFFLINE_AFTER_SECONDS, MAX_OFFLINE_AFTER_SECONDS)
        ):
            raise RegistryProtocolError("heartbeat response failed validation")
        return HeartbeatResult(
            status="ACTIVE", heartbeat_interval_seconds=body["heartbeat_interval_seconds"],
            offline_after_seconds=body["offline_after_seconds"], allowed_account_ids=accounts,
        )
```

- [ ] **Step 4: Run to verify pass.** `python -m pytest tests/app/workstation_runner/test_http_client.py -v` → all PASS. (`httpx.Client` internal attribute names `follow_redirects`/`_trust_env` — confirm against the installed `httpx==0.28.1` during implementation; if either has moved, read `httpx/_client.py` in the installed package and adjust the two attribute-based tests, not the production behavior.)

---

### Task 5: Heartbeat lifecycle state machine

**Files:**
- Create: `mcma/app/workstation_runner/heartbeat.py`
- Test: `tests/app/workstation_runner/test_heartbeat.py`

**Interfaces:**
- Consumes: `http_client.{RegistryHttpClient, HeartbeatResult, RegistryConnectionError, RegistryUnauthorized, RegistryProtocolError}` (Task 4); `identity.IdentityStore` (Task 2); `protocol.{MIN_HEARTBEAT_INTERVAL_SECONDS, MAX_HEARTBEAT_INTERVAL_SECONDS}` (Task 1); `_fakes.FakeStopWaiter` (Task 2) in tests.
- Produces: `heartbeat.LifecycleEvent` (Enum: `CONNECTED`, `CONNECTION_FAILED`, `UNAUTHORIZED`), `heartbeat.HeartbeatLifecycle(client, identity_store, on_event: Callable[[LifecycleEvent], None], *, wait=... )` with `.run_once_loop(identity, allowed_account_ids, stop_event: threading.Event) -> None` (the loop body, injectable `wait`), `heartbeat.HeartbeatWorker(lifecycle, identity, allowed_account_ids)` with `.start() -> None`, `.stop(timeout: float) -> None` wrapping a `threading.Thread`.

- [ ] **Step 1: Write the failing heartbeat tests**

```python
# tests/app/workstation_runner/test_heartbeat.py
import threading

import pytest

from mcma.app.workstation_runner.heartbeat import HeartbeatLifecycle, HeartbeatWorker, LifecycleEvent
from mcma.app.workstation_runner.http_client import (
    HeartbeatResult, RegistryConnectionError, RegistryUnauthorized,
)
from tests.app.workstation_runner._fakes import FakeStopWaiter

SECRET = "mcma_rs_" + "s" * 40


class _ScriptedClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def heartbeat(self, runner_secret, *, allowed_account_ids):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _RecordingIdentityStore:
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


def _ok(interval=10, offline=30):
    return HeartbeatResult(status="ACTIVE", heartbeat_interval_seconds=interval, offline_after_seconds=offline, allowed_account_ids=())


def test_first_heartbeat_is_sent_immediately_without_waiting():
    client = _ScriptedClient([_ok()])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()  # stop as soon as the loop waits after the first success
    events = []
    lifecycle = HeartbeatLifecycle(client, _RecordingIdentityStore(), events.append, wait=waiter)
    lifecycle.run_once_loop(SECRET, (), threading.Event())
    assert client.calls == 1
    assert events == [LifecycleEvent.CONNECTED]


def test_success_waits_for_server_provided_interval():
    client = _ScriptedClient([_ok(interval=42)])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()
    HeartbeatLifecycle(client, _RecordingIdentityStore(), lambda e: None, wait=waiter).run_once_loop(SECRET, (), threading.Event())
    assert waiter.waits == [42]


@pytest.mark.parametrize("bad_interval", [0, -1, 999999])
def test_out_of_bounds_interval_falls_back_to_a_safe_default(bad_interval):
    client = _ScriptedClient([_ok(interval=bad_interval)])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()
    HeartbeatLifecycle(client, _RecordingIdentityStore(), lambda e: None, wait=waiter).run_once_loop(SECRET, (), threading.Event())
    assert 1 <= waiter.waits[0] <= 3600


def test_connection_failure_backs_off_and_retries_then_recovers():
    client = _ScriptedClient([RegistryConnectionError("x"), RegistryConnectionError("x"), _ok()])
    waiter = FakeStopWaiter()
    waiter.stop_on_next_wait()  # stop after the 3rd call succeeds and waits
    events = []
    HeartbeatLifecycle(client, _RecordingIdentityStore(), events.append, wait=waiter).run_once_loop(SECRET, (), threading.Event())
    assert client.calls == 3
    assert events == [LifecycleEvent.CONNECTION_FAILED, LifecycleEvent.CONNECTION_FAILED, LifecycleEvent.CONNECTED]
    assert waiter.waits[0] >= 1 and waiter.waits[1] >= waiter.waits[0]  # never a tight loop, backs off


def test_unauthorized_clears_identity_and_stops_the_loop():
    client = _ScriptedClient([RegistryUnauthorized("x")])
    store = _RecordingIdentityStore()
    waiter = FakeStopWaiter()
    events = []
    HeartbeatLifecycle(client, store, events.append, wait=waiter).run_once_loop(SECRET, (), threading.Event())
    assert store.cleared is True
    assert events == [LifecycleEvent.UNAUTHORIZED]
    assert client.calls == 1
    assert waiter.waits == []  # returns immediately, no further waiting/looping


def test_stop_event_set_before_loop_starts_sends_no_heartbeat():
    client = _ScriptedClient([])
    stop = threading.Event()
    stop.set()
    HeartbeatLifecycle(client, _RecordingIdentityStore(), lambda e: None, wait=FakeStopWaiter()).run_once_loop(SECRET, (), stop)
    assert client.calls == 0


def test_worker_start_and_bounded_stop_join():
    started = threading.Event()

    class _BlockingLifecycle:
        def run_once_loop(self, secret, accounts, stop_event):
            started.set()
            stop_event.wait(5)

    worker = HeartbeatWorker(_BlockingLifecycle(), SECRET, ())
    worker.start()
    assert started.wait(1)
    worker.stop(timeout=2)
    assert not worker.is_alive()
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `heartbeat.py`**

```python
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
    def __init__(self, client, identity_store, on_event: Callable[[LifecycleEvent], None], *, wait: Callable[[threading.Event, float], bool] = _default_wait) -> None:
        self._client = client
        self._identity_store = identity_store
        self._on_event = on_event
        self._wait = wait

    def run_once_loop(self, runner_secret: str, allowed_account_ids: tuple, stop_event: threading.Event) -> None:
        backoff = _INITIAL_BACKOFF_SECONDS
        while not stop_event.is_set():
            try:
                result = self._client.heartbeat(runner_secret, allowed_account_ids=allowed_account_ids)
            except RegistryUnauthorized:
                self._identity_store.clear()
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


class HeartbeatWorker:
    """Thread wrapper: one non-daemon thread running one HeartbeatLifecycle
    loop, stoppable with a bounded join."""

    def __init__(self, lifecycle, runner_secret: str, allowed_account_ids: tuple) -> None:
        self._lifecycle = lifecycle
        self._runner_secret = runner_secret
        self._allowed_account_ids = allowed_account_ids
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._lifecycle.run_once_loop,
            args=(self._runner_secret, self._allowed_account_ids, self._stop_event),
            name="mcma-runner-heartbeat",
            daemon=False,
        )
        self._thread.start()

    def stop(self, timeout: float) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
```

- [ ] **Step 4: Run to verify pass.**

---

### Task 6: Rotating log setup

**Files:**
- Create: `mcma/app/workstation_runner/logging_setup.py`
- Test: `tests/app/workstation_runner/test_logging_setup.py`

**Interfaces:**
- Produces: `logging_setup.LOGGER_NAME = "mcma.workstation_runner"`, `logging_setup.configure_logging(log_dir: Path) -> logging.Logger` (installs a bounded `RotatingFileHandler`, idempotent — safe to call more than once), `logging_setup.log_event(logger: logging.Logger, event: str, **safe_fields) -> None` (fixed event names + primitive safe fields only; raises `ValueError` if a forbidden key like `secret`/`pairing_code`/`authorization`/`runner_secret` is passed, so a future call site cannot accidentally leak one).

- [ ] **Step 1: Write the failing tests**

```python
# tests/app/workstation_runner/test_logging_setup.py
import logging

import pytest

from mcma.app.workstation_runner.logging_setup import configure_logging, log_event


def test_configure_logging_creates_rotating_file(tmp_path):
    logger = configure_logging(tmp_path)
    log_event(logger, "startup")
    for handler in logger.handlers:
        handler.flush()
    files = list(tmp_path.glob("*.log"))
    assert len(files) == 1
    assert "startup" in files[0].read_text(encoding="utf-8")


def test_configure_logging_is_idempotent(tmp_path):
    logger1 = configure_logging(tmp_path)
    logger2 = configure_logging(tmp_path)
    assert logger1 is logger2
    assert len(logger1.handlers) == 1


def test_configure_logging_bounds_rotation_size(tmp_path):
    logger = configure_logging(tmp_path)
    handler = logger.handlers[0]
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert 0 < handler.maxBytes <= 5 * 1024 * 1024
    assert 0 < handler.backupCount <= 10


@pytest.mark.parametrize("forbidden_key", ["secret", "pairing_code", "authorization", "runner_secret", "password"])
def test_log_event_refuses_forbidden_fields(tmp_path, forbidden_key):
    logger = configure_logging(tmp_path)
    with pytest.raises(ValueError):
        log_event(logger, "test_event", **{forbidden_key: "x"})
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `logging_setup.py`**

```python
"""mcma.app.workstation_runner.logging_setup -- bounded rotating local logs.
log_event() is the only sanctioned way to write to this logger: it takes a
fixed event name plus primitive keyword fields and refuses a hardcoded list
of forbidden field names, so a future call site cannot pass a secret by
accident. Never logs request/response bodies, headers, ciphertext, or raw
exception text -- callers pass safe categories (e.g. event="heartbeat_failed",
reason="connection")."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOGGER_NAME = "mcma.workstation_runner"

_MAX_BYTES = 1 * 1024 * 1024
_BACKUP_COUNT = 5

_FORBIDDEN_FIELDS = frozenset({
    "secret", "pairing_code", "authorization", "runner_secret", "password",
    "token", "ciphertext", "body", "headers",
})


def configure_logging(log_dir: Path) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger  # idempotent: already configured
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "workstation_runner.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **safe_fields) -> None:
    forbidden = _FORBIDDEN_FIELDS & set(safe_fields)
    if forbidden:
        raise ValueError(f"refusing to log forbidden field(s): {sorted(forbidden)}")
    fields = " ".join(f"{k}={v!r}" for k, v in sorted(safe_fields.items()))
    logger.info("%s %s", event, fields)
```

- [ ] **Step 4: Run to verify pass.**

---

### Task 7: Runner controller (pure state machine, no Tkinter)

**Files:**
- Create: `mcma/app/workstation_runner/controller.py`
- Test: `tests/app/workstation_runner/test_controller.py`

**Interfaces:**
- Consumes: `config.RunnerConfig`, `identity.{IdentityStore, RunnerIdentity}`, `http_client.{RegistryHttpClient, EnrollResult, RegistryConnectionError, RegistryProtocolError}`, `heartbeat.{HeartbeatLifecycle, HeartbeatWorker, LifecycleEvent}`.
- Produces: `controller.ControllerState` (Enum: `PAIRING_IDLE`, `PAIRING_IN_PROGRESS`, `PAIRED_CONNECTING`, `PAIRED_CONNECTED`, `PAIRED_DISCONNECTED`), `controller.StatusMessage` (frozen dataclass: `state: ControllerState`, `text: str` — the fixed French string to display), `controller.RunnerController(config, identity_store, client_factory: Callable[[], RegistryHttpClient], lifecycle_factory: Callable[[RegistryHttpClient], HeartbeatLifecycle], on_status: Callable[[StatusMessage], None])` with `.start() -> None` (call once at startup: tries to load+resume identity, else idle-pairing), `.submit_pairing(pairing_code: str) -> None` (runs enroll on a worker thread; a no-op if a pairing attempt is already in flight), `.shutdown(timeout: float) -> None`.

- [ ] **Step 1: Write the failing controller tests**

```python
# tests/app/workstation_runner/test_controller.py
import threading
import time

import pytest

from mcma.app.workstation_runner.config import RunnerConfig
from mcma.app.workstation_runner.controller import ControllerState, RunnerController
from mcma.app.workstation_runner.heartbeat import HeartbeatLifecycle, LifecycleEvent
from mcma.app.workstation_runner.http_client import EnrollResult, RegistryConnectionError

ORIGIN = "https://central.example.local"


def _config():
    return RunnerConfig(server_origin=ORIGIN, ca_cert_path=None, workstation_label="Poste-1")


class _FakeIdentityStore:
    def __init__(self, existing=None):
        self._existing = existing
        self.saved = None
        self.cleared = False

    def load(self, *, expected_server_origin):
        return self._existing

    def save(self, identity):
        self.saved = identity

    def clear(self):
        self.cleared = True


class _FakeClient:
    def __init__(self, enroll_result=None, enroll_error=None):
        self._enroll_result = enroll_result
        self._enroll_error = enroll_error

    def enroll(self, pairing_code, *, workstation_label):
        if self._enroll_error:
            raise self._enroll_error
        return self._enroll_result

    def close(self):
        pass


class _NullLifecycle:
    """Never actually loops -- used where the test only cares about pairing."""

    def run_once_loop(self, secret, accounts, stop_event):
        stop_event.wait()  # blocks until controller.shutdown() sets it


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_start_with_no_saved_identity_goes_to_pairing_idle():
    statuses = []
    controller = RunnerController(
        _config(), _FakeIdentityStore(existing=None), lambda: _FakeClient(),
        lambda client: _NullLifecycle(), statuses.append,
    )
    controller.start()
    assert statuses[-1].state == ControllerState.PAIRING_IDLE
    controller.shutdown(timeout=2)


def test_successful_pairing_saves_identity_and_starts_heartbeat():
    statuses = []
    store = _FakeIdentityStore(existing=None)
    result = EnrollResult(
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40, runner_label="Poste-1",
        allowed_account_ids=("acct-mcma-oujda",), heartbeat_interval_seconds=10, offline_after_seconds=30,
    )
    controller = RunnerController(_config(), store, lambda: _FakeClient(enroll_result=result), lambda client: _NullLifecycle(), statuses.append)
    controller.start()
    controller.submit_pairing("mcma_pc_x")
    assert _wait_until(lambda: store.saved is not None)
    assert store.saved.runner_id == "a" * 32
    assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRED_CONNECTING)
    controller.shutdown(timeout=2)


def test_pairing_failure_stays_in_pairing_idle_with_fixed_message():
    statuses = []
    controller = RunnerController(
        _config(), _FakeIdentityStore(), lambda: _FakeClient(enroll_error=RegistryConnectionError("x")),
        lambda client: _NullLifecycle(), statuses.append,
    )
    controller.start()
    controller.submit_pairing("mcma_pc_x")
    assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE and "Serveur inaccessible" in statuses[-1].text)
    controller.shutdown(timeout=2)


def test_duplicate_concurrent_pairing_attempts_are_ignored():
    calls = []
    gate = threading.Event()

    class _SlowClient:
        def enroll(self, pairing_code, *, workstation_label):
            calls.append(pairing_code)
            gate.wait(2)
            raise RegistryConnectionError("x")

        def close(self):
            pass

    controller = RunnerController(_config(), _FakeIdentityStore(), lambda: _SlowClient(), lambda client: _NullLifecycle(), lambda s: None)
    controller.start()
    controller.submit_pairing("mcma_pc_first")
    controller.submit_pairing("mcma_pc_second")  # must be dropped: an attempt is already in flight
    gate.set()
    assert _wait_until(lambda: len(calls) == 1)
    time.sleep(0.05)
    assert calls == ["mcma_pc_first"]
    controller.shutdown(timeout=2)


def test_start_with_saved_identity_resumes_heartbeat_without_reenrolling():
    from mcma.app.workstation_runner.identity import RunnerIdentity, IDENTITY_FORMAT_VERSION
    existing = RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN, runner_id="a" * 32,
        runner_secret="mcma_rs_" + "b" * 40, allowed_account_ids=("acct-mcma-oujda",),
    )
    statuses = []
    controller = RunnerController(_config(), _FakeIdentityStore(existing=existing), lambda: _FakeClient(), lambda client: _NullLifecycle(), statuses.append)
    controller.start()
    assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRED_CONNECTING)
    controller.shutdown(timeout=2)


def test_unauthorized_event_returns_controller_to_pairing_idle():
    statuses = []

    class _UnauthorizingLifecycle:
        def run_once_loop(self, secret, accounts, stop_event):
            controller._handle_lifecycle_event(LifecycleEvent.UNAUTHORIZED)

    from mcma.app.workstation_runner.identity import RunnerIdentity, IDENTITY_FORMAT_VERSION
    existing = RunnerIdentity(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN, runner_id="a" * 32,
        runner_secret="mcma_rs_" + "b" * 40, allowed_account_ids=(),
    )
    store = _FakeIdentityStore(existing=existing)
    controller = RunnerController(_config(), store, lambda: _FakeClient(), lambda client: _UnauthorizingLifecycle(), statuses.append)
    controller.start()
    assert _wait_until(lambda: statuses[-1].state == ControllerState.PAIRING_IDLE)
    controller.shutdown(timeout=2)


def test_shutdown_is_safe_during_pairing_in_progress():
    gate = threading.Event()

    class _SlowClient:
        def enroll(self, pairing_code, *, workstation_label):
            gate.wait(2)
            raise RegistryConnectionError("x")

        def close(self):
            pass

    controller = RunnerController(_config(), _FakeIdentityStore(), lambda: _SlowClient(), lambda client: _NullLifecycle(), lambda s: None)
    controller.start()
    controller.submit_pairing("mcma_pc_x")
    controller.shutdown(timeout=2)  # must not hang or raise
    gate.set()
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Write `controller.py`**

```python
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

from mcma.app.workstation_runner.config import RunnerConfig
from mcma.app.workstation_runner.heartbeat import HeartbeatWorker, LifecycleEvent
from mcma.app.workstation_runner.http_client import RegistryConnectionError, RegistryProtocolError


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


class RunnerController:
    def __init__(
        self,
        config: RunnerConfig,
        identity_store,
        client_factory: Callable[[], object],
        lifecycle_factory: Callable[[object], object],
        on_status: Callable[[StatusMessage], None],
    ) -> None:
        self._config = config
        self._identity_store = identity_store
        self._client_factory = client_factory
        self._lifecycle_factory = lifecycle_factory
        self._on_status = on_status
        self._pairing_lock = threading.Lock()
        self._pairing_in_progress = False
        self._heartbeat_worker: HeartbeatWorker | None = None
        self._pairing_thread: threading.Thread | None = None

    def _emit(self, state: ControllerState, text: str | None = None) -> None:
        self._on_status(StatusMessage(state, text if text is not None else _TEXT[state]))

    def start(self) -> None:
        identity = self._identity_store.load(expected_server_origin=self._config.server_origin)
        if identity is None:
            self._emit(ControllerState.PAIRING_IDLE)
            return
        self._start_heartbeat(identity.runner_secret, identity.allowed_account_ids)

    def submit_pairing(self, pairing_code: str) -> None:
        with self._pairing_lock:
            if self._pairing_in_progress:
                return  # duplicate concurrent attempt: dropped, not queued
            self._pairing_in_progress = True
        self._emit(ControllerState.PAIRING_IN_PROGRESS)
        self._pairing_thread = threading.Thread(target=self._run_pairing, args=(pairing_code,), daemon=False)
        self._pairing_thread.start()

    def _run_pairing(self, pairing_code: str) -> None:
        client = self._client_factory()
        try:
            result = client.enroll(pairing_code, workstation_label=self._config.workstation_label)
        except RegistryConnectionError:
            self._emit(ControllerState.PAIRING_IDLE, _ENROLL_CONNECTION_FAILED_TEXT)
            return
        except RegistryProtocolError:
            self._emit(ControllerState.PAIRING_IDLE, _ENROLL_FAILED_TEXT)
            return
        finally:
            client.close()
            with self._pairing_lock:
                self._pairing_in_progress = False
            pairing_code = None  # noqa: F841 -- drop the last local reference promptly

        from mcma.app.workstation_runner.identity import RunnerIdentity, IDENTITY_FORMAT_VERSION

        identity = RunnerIdentity(
            format_version=IDENTITY_FORMAT_VERSION, server_origin=self._config.server_origin,
            runner_id=result.runner_id, runner_secret=result.runner_secret,
            allowed_account_ids=result.allowed_account_ids,
        )
        self._identity_store.save(identity)
        self._start_heartbeat(identity.runner_secret, identity.allowed_account_ids)

    def _start_heartbeat(self, runner_secret: str, allowed_account_ids: tuple) -> None:
        client = self._client_factory()
        lifecycle = self._lifecycle_factory(client)
        self._heartbeat_worker = HeartbeatWorker(lifecycle, runner_secret, allowed_account_ids)
        self._emit(ControllerState.PAIRED_CONNECTING)
        self._heartbeat_worker.start()

    def _handle_lifecycle_event(self, event: LifecycleEvent) -> None:
        if event is LifecycleEvent.CONNECTED:
            self._emit(ControllerState.PAIRED_CONNECTED)
        elif event is LifecycleEvent.CONNECTION_FAILED:
            self._emit(ControllerState.PAIRED_DISCONNECTED)
        elif event is LifecycleEvent.UNAUTHORIZED:
            self._identity_store.clear()
            self._emit(ControllerState.PAIRING_IDLE)

    def shutdown(self, timeout: float = 5.0) -> None:
        if self._heartbeat_worker is not None:
            self._heartbeat_worker.stop(timeout=timeout)
        if self._pairing_thread is not None:
            self._pairing_thread.join(timeout=timeout)
```

Note for the implementer: `_handle_lifecycle_event` must be wired as the
`on_event` callback the real `HeartbeatLifecycle` calls — pass
`self._handle_lifecycle_event` as `on_event` when building lifecycles via
`lifecycle_factory` in `app.py` (Task 8), not in this file, so `controller.py`
never imports `heartbeat.HeartbeatLifecycle` directly (only the worker/event
enum it already imports). Re-check `test_unauthorized_event_returns_...`
against the actual wiring during implementation — that test calls
`controller._handle_lifecycle_event` directly, so it exercises the method
regardless of how `app.py` wires it, but `app.py`'s wiring is what makes
`_handle_lifecycle_event` a real production code path.

- [ ] **Step 4: Run to verify pass. Fix any race in the duplicate-pairing test** by widening the lock scope or adding a short synchronization primitive if the first `_FakeClient`/`_SlowClient` call's flag-clear races the second `submit_pairing` — prefer making `_pairing_in_progress` cleared strictly after `client.close()` inside the `finally`, as written above, which is already ordered correctly.

---

### Task 8: Tkinter GUI

**Files:**
- Create: `mcma/app/workstation_runner/gui.py`

**Interfaces:**
- Consumes: `controller.{RunnerController, ControllerState, StatusMessage}` (Task 7).
- Produces: `gui.RunnerApp(controller: RunnerController)` with `.run() -> None` (builds the Tk root, starts a `root.after` poll loop, calls `mainloop()`), `.on_close() -> None` (bound to `WM_DELETE_WINDOW`: calls `controller.shutdown()` then `root.destroy()`).

No dedicated automated test file: Tkinter widget behavior cannot be exercised
headlessly, and the controller it wraps is already fully covered by Task 7.
`gui.py` must contain **no business logic** — every decision (what text to
show, when pairing is allowed, when to switch views) lives in `controller.py`
and is driven by `StatusMessage` values `RunnerApp` receives through a
`queue.Queue`, so the split itself is the test coverage guarantee.

- [ ] **Step 1: Write `gui.py`**

```python
"""mcma.app.workstation_runner.gui -- French Tkinter GUI. Contains no
business logic: it renders StatusMessage values from RunnerController and
forwards the pairing form to controller.submit_pairing(). All
controller-thread -> UI-thread communication goes through a bounded Queue
drained on the Tk main loop via root.after(), so Tkinter calls always
happen on the UI thread."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from mcma.app.workstation_runner.controller import ControllerState, RunnerController, StatusMessage

_POLL_INTERVAL_MS = 150
_QUEUE_MAXSIZE = 64


class RunnerApp:
    def __init__(self, controller: RunnerController) -> None:
        self._controller = controller
        self._queue: "queue.Queue[StatusMessage]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._root = tk.Tk()
        self._root.title("MCMA — Poste agent")
        self._root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._status_var = tk.StringVar(value="")
        ttk.Label(self._root, textvariable=self._status_var, wraplength=360).pack(padx=16, pady=(16, 8))

        self._pairing_frame = ttk.Frame(self._root)
        ttk.Label(self._pairing_frame, text="URL du serveur central").pack(anchor="w")
        self._server_origin_var = tk.StringVar()
        ttk.Entry(self._pairing_frame, textvariable=self._server_origin_var, width=48).pack(fill="x")

        ttk.Label(self._pairing_frame, text="Certificat CA (optionnel)").pack(anchor="w", pady=(8, 0))
        self._ca_cert_var = tk.StringVar()
        ttk.Entry(self._pairing_frame, textvariable=self._ca_cert_var, width=48).pack(fill="x")

        ttk.Label(self._pairing_frame, text="Nom du poste").pack(anchor="w", pady=(8, 0))
        self._label_var = tk.StringVar()
        ttk.Entry(self._pairing_frame, textvariable=self._label_var, width=48).pack(fill="x")

        ttk.Label(self._pairing_frame, text="Code d'association").pack(anchor="w", pady=(8, 0))
        self._pairing_code_var = tk.StringVar()
        self._pairing_code_entry = ttk.Entry(self._pairing_frame, textvariable=self._pairing_code_var, width=48, show="•")
        self._pairing_code_entry.pack(fill="x")

        self._associate_button = ttk.Button(self._pairing_frame, text="Associer ce poste", command=self._on_associate_clicked)
        self._associate_button.pack(pady=(12, 0))
        self._pairing_frame.pack(padx=16, pady=8, fill="x")

        self._paired_frame = ttk.Frame(self._root)
        ttk.Label(self._paired_frame, text="Comptes MCMA").pack(anchor="w")
        self._accounts_var = tk.StringVar(value="acct-mcma-oujda: NOT_CONFIGURED\nacct-mcma-nador: NOT_CONFIGURED")
        ttk.Label(self._paired_frame, textvariable=self._accounts_var).pack(anchor="w")

    def _clear_pairing_code(self) -> None:
        self._pairing_code_var.set("")
        self._pairing_code_entry.delete(0, "end")

    def _on_associate_clicked(self) -> None:
        pairing_code = self._pairing_code_var.get().strip()
        self._associate_button.state(["disabled"])
        try:
            self._controller.submit_pairing(pairing_code)
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
        self._status_var.set(status.text)
        if status.state in (ControllerState.PAIRING_IDLE, ControllerState.PAIRING_IN_PROGRESS):
            self._paired_frame.pack_forget()
            self._pairing_frame.pack(padx=16, pady=8, fill="x")
            self._associate_button.state(["!disabled"] if status.state == ControllerState.PAIRING_IDLE else ["disabled"])
        else:
            self._pairing_frame.pack_forget()
            self._paired_frame.pack(padx=16, pady=8, fill="x")

    def on_close(self) -> None:
        self._controller.shutdown(timeout=5.0)
        self._root.destroy()

    def run(self) -> None:
        # controller.on_status is called from worker threads; forward to the
        # queue only (never touch Tk state off the UI thread).
        self._root.after(_POLL_INTERVAL_MS, self._poll_queue)
        self._controller.start()
        self._root.mainloop()
```

Implementer note: `RunnerApp.__init__` builds the controller's `on_status`
callback as `self._enqueue_status` — wire this explicitly in `app.py` (Task
9) when constructing `RunnerController(..., on_status=app._enqueue_status)`,
after `RunnerApp` is constructed but before `controller.start()` is called
(which `run()` does) — order matters: build `RunnerApp` first, then the
`RunnerController` with `on_status=app._enqueue_status`, then call
`app.run()`.

- [ ] **Step 2: Smoke-check by hand during Task 10's manual verification** — no automated test for this file (see rationale above); `test_import_isolation.py` (Task 9) still proves this module imports cleanly.

---

### Task 9: Composition root, single instance, entrypoint, import isolation

**Files:**
- Create: `mcma/app/workstation_runner/app.py`
- Create: `mcma/app/workstation_runner/__main__.py`
- Test: `tests/app/workstation_runner/test_app_single_instance.py`
- Test: `tests/app/workstation_runner/test_import_isolation.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8; `mcma.core.mutex.{create_single_instance_mutex, MutexAcquisitionError}`.
- Produces: `app.SINGLE_INSTANCE_MUTEX_NAME = "MCMA_WorkstationRunner"`, `app.run(config: RunnerConfig | None = None) -> int` (return code: `0` normal exit, `1` if another instance already holds the mutex), `app.build_default_config_from_env() -> RunnerConfig | None` (reads a small on-disk config file the pairing GUI itself writes on first successful pairing — see below — or `None` if none exists yet, in which case `app.run` shows the pairing GUI with blank fields).

- [ ] **Step 1: Write the failing single-instance test**

```python
# tests/app/workstation_runner/test_app_single_instance.py
from mcma.app.workstation_runner.app import SINGLE_INSTANCE_MUTEX_NAME
from mcma.core.mutex import MutexAcquisitionError, create_single_instance_mutex


def test_second_instance_is_refused_while_first_holds_the_mutex():
    first = create_single_instance_mutex(SINGLE_INSTANCE_MUTEX_NAME, _test_only_portable_backend=True)
    first.acquire()
    try:
        second = create_single_instance_mutex(SINGLE_INSTANCE_MUTEX_NAME, _test_only_portable_backend=True)
        import pytest
        with pytest.raises(MutexAcquisitionError):
            second.acquire()
    finally:
        first.release()


def test_mutex_is_released_after_first_instance_releases():
    first = create_single_instance_mutex(SINGLE_INSTANCE_MUTEX_NAME, _test_only_portable_backend=True)
    first.acquire()
    first.release()
    second = create_single_instance_mutex(SINGLE_INSTANCE_MUTEX_NAME, _test_only_portable_backend=True)
    second.acquire()
    second.release()
```

- [ ] **Step 2: Write the failing import-isolation test**

```python
# tests/app/workstation_runner/test_import_isolation.py
"""Fresh-process import proof, following the pattern in
tests/contracts/test_import_boundaries.py: importing the package in a
brand-new interpreter must never pull in Playwright, SQLite, FastAPI,
mcma.portal, mcma.execution, or mcma.persistence."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

_FORBIDDEN_MODULE_PREFIXES = (
    "playwright", "sqlite3", "fastapi", "mcma.portal", "mcma.execution", "mcma.persistence",
)

_CHECK_SCRIPT = """
import sys
import mcma.app.workstation_runner
import mcma.app.workstation_runner.config
import mcma.app.workstation_runner.identity
import mcma.app.workstation_runner.http_client
import mcma.app.workstation_runner.heartbeat
import mcma.app.workstation_runner.controller
import mcma.app.workstation_runner.logging_setup
forbidden = {forbidden!r}
hit = [m for m in sys.modules if any(m == p or m.startswith(p + ".") for p in forbidden)]
if hit:
    print("FORBIDDEN_IMPORTED:" + ",".join(sorted(hit)))
    sys.exit(1)
print("OK")
""".replace("{forbidden!r}", repr(_FORBIDDEN_MODULE_PREFIXES))


def test_fresh_process_import_proof():
    proc = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK"
```

Note: `mcma.app.workstation_runner.gui` and `.app` are deliberately **not**
imported by this check on a non-Windows CI box, since `gui`'s module-level
`import tkinter` can fail in a headless container without a display backend
even though it never *opens* a window at import time, and `app.py` imports
`gui`. Add a second, `skipif(sys.platform != "win32")`-guarded check in the
same file that also imports `mcma.app.workstation_runner.app` and
`mcma.app.workstation_runner.gui`, for full coverage on this Windows
machine:

```python
import pytest

_FULL_CHECK_SCRIPT = _CHECK_SCRIPT.replace(
    "import mcma.app.workstation_runner.logging_setup\n",
    "import mcma.app.workstation_runner.logging_setup\nimport mcma.app.workstation_runner.gui\nimport mcma.app.workstation_runner.app\n",
)


@pytest.mark.skipif(sys.platform != "win32", reason="tkinter import checked only where a Windows desktop session is expected")
def test_fresh_process_import_proof_including_gui_and_app():
    proc = subprocess.run(
        [sys.executable, "-c", _FULL_CHECK_SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK"
```

- [ ] **Step 3: Run both new test files to verify failure** (module doesn't exist yet for the first; the second may already partially pass for the already-built modules — confirm the full-check variant fails until `app.py`/`gui.py` exist).

- [ ] **Step 4: Write `app.py`**

```python
"""mcma.app.workstation_runner.app -- composition root. Builds real
backends (DPAPI, httpx, Tkinter), acquires the single-instance mutex, and
runs the GUI. The only place in this package that constructs
DpapiCurrentUserBackend / RegistryHttpClient / RunnerApp together."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcma.app.workstation_runner.config import ConfigError, RunnerConfig, build_config
from mcma.app.workstation_runner.controller import RunnerController
from mcma.app.workstation_runner.gui import RunnerApp
from mcma.app.workstation_runner.heartbeat import HeartbeatLifecycle
from mcma.app.workstation_runner.http_client import RegistryHttpClient
from mcma.app.workstation_runner.identity import IdentityStore, default_identity_path, select_production_crypto_backend
from mcma.app.workstation_runner.logging_setup import configure_logging, log_event
from mcma.core.mutex import MutexAcquisitionError, create_single_instance_mutex

SINGLE_INSTANCE_MUTEX_NAME = "MCMA_WorkstationRunner"

_SINGLE_INSTANCE_MESSAGE = "Une autre instance du poste agent MCMA est déjà en cours d'exécution."


def _local_app_data_dir() -> Path:
    local_app_data = __import__("os").environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set")
    return Path(local_app_data) / "MCMA Runner"


def _config_path() -> Path:
    return _local_app_data_dir() / "config.json"


def build_default_config_from_env() -> RunnerConfig | None:
    """Non-secret pairing-form defaults (server origin, CA cert path,
    workstation label) saved on first successful pairing, so a restart does
    not require retyping them. Never contains a secret or pairing code."""
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
    __import__("os").replace(tmp, path)


def run(config: RunnerConfig | None = None) -> int:
    mutex = create_single_instance_mutex(SINGLE_INSTANCE_MUTEX_NAME)
    try:
        mutex.acquire()
    except MutexAcquisitionError:
        print(_SINGLE_INSTANCE_MESSAGE)
        return 1

    try:
        logger = configure_logging(_local_app_data_dir() / "logs")
        log_event(logger, "startup")

        resolved_config = config or build_default_config_from_env() or RunnerConfig(
            server_origin="", ca_cert_path=None, workstation_label="",
        )
        identity_store = IdentityStore(default_identity_path(), select_production_crypto_backend())

        def client_factory() -> RegistryHttpClient:
            return RegistryHttpClient(resolved_config.server_origin, ca_cert_path=resolved_config.ca_cert_path)

        def lifecycle_factory(client):
            return HeartbeatLifecycle(client, identity_store, controller._handle_lifecycle_event)

        gui_app = RunnerApp.__new__(RunnerApp)  # placeholder to satisfy forward reference; replaced below
        controller = RunnerController(resolved_config, identity_store, client_factory, lifecycle_factory, lambda status: gui_app._enqueue_status(status))
        gui_app.__init__(controller)
        gui_app.run()
        log_event(logger, "shutdown")
        return 0
    finally:
        mutex.release()


if __name__ == "__main__":  # pragma: no cover -- exercised via __main__.py
    sys.exit(run())
```

Implementer note on the forward-reference: constructing `controller` needs
`gui_app._enqueue_status`, but `RunnerApp.__init__` needs `controller`. Break
the cycle cleanly instead of the placeholder trick above — during
implementation, give `RunnerApp` a two-phase constructor: `RunnerApp()` takes
no controller, builds all widgets with a private `_status_queue`, and exposes
`.bind_controller(controller)` that just stores the reference (used only for
`on_close`/`_on_associate_clicked`); `run()` calls `controller.start()`
itself using the bound controller. Update Task 8's `gui.py` accordingly
before writing this file: `RunnerApp.__init__(self)` (no controller arg),
add `bind_controller(self, controller)`, and have `on_close`/
`_on_associate_clicked`/`run` use `self._controller` (set by
`bind_controller`, asserted non-`None`). This is a straightforward
same-task adjustment, not a redesign — call it out explicitly if the
Task 8 code above is implemented literally as written; fix it while
writing `app.py` in this task, and re-run Task 8's manual smoke check
after.

- [ ] **Step 5: Write `__main__.py`**

```python
"""python -m mcma.app.workstation_runner -- also the pythonw.exe entry
point (no console required, no stdout the user would ever see)."""

from __future__ import annotations

import sys

from mcma.app.workstation_runner.app import run

if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 6: Run to verify pass.** `python -m pytest tests/app/workstation_runner/ -v`.

---

### Task 10: Documentation

**Files:**
- Modify: `docs/architecture/CENTRAL_SERVER_DEPLOYMENT.md` (append a new section right after the existing "Workstation runner registry (Phase 1A)" section; make the one small precision edit called out below)

- [ ] **Step 1: Precision edit to the Phase 1A section's "Not built yet" line**

Change:
```
**Not built yet:** job claiming/dispatch, dossier locks, the Windows runner
program, local browsers, portal login, form filling.
```
to:
```
**Not built yet:** job claiming/dispatch, dossier locks, browsers, portal
login, form filling. The Windows runner *program* now exists as a pairing +
heartbeat client only (Phase 1B-A, below) — it reports every account as
NOT_CONFIGURED and executes nothing.
```

- [ ] **Step 2: Append the new section** (after the Phase 1A section's last paragraph, before the next top-level heading if any)

```markdown
## Windows workstation runner — client foundation (Phase 1B-A)

`mcma/app/workstation_runner/` is the actual Windows program an employee
runs: a French Tkinter GUI that pairs against the Phase 1A registry above
and then heartbeats. **Still not built:** browsers, MCMA/SinAuto login, OTP,
portal sessions, job dispatch, dossier downloads, form filling, installer,
Windows service, scheduled task, autostart. It reports both allowed accounts
as `NOT_CONFIGURED` and never claims `READY`.

### Trust boundary

- One interactive process per signed-in Windows user (an OS-level named
  mutex enforces this — a second launch shows a fixed message and exits).
  It is **not** a Windows service; a future visible Playwright browser runs
  in the same employee desktop session as this process, never a service
  session.
- The pairing code and runner secret are the only credentials this process
  ever holds; it never uses a platform employee session cookie or an admin
  credential, and the two are never mixed with each other.
- The identity envelope (`format_version`, `server_origin`, `runner_id`,
  `runner_secret`, `allowed_account_ids`) is encrypted at rest with Windows
  DPAPI, scope `CURRENT_USER` (`mcma.core.dpapi`) — only the same Windows
  account that paired can decrypt it. This is deliberately a **separate**
  store from the portal-session vault (`mcma.portal.vault`): runner identity
  and browser session cookies are different secrets with different
  lifetimes and different owners.
- A missing, corrupted, tampered, or wrong-account identity file fails
  closed: the app falls back to the pairing view, never to a weaker crypto
  scope, base64, or plaintext.

### Where things live

- Encrypted identity: `%LOCALAPPDATA%\MCMA Runner\identity.bin`
- Non-secret pairing-form defaults (server origin, CA cert path,
  workstation label — never a secret): `%LOCALAPPDATA%\MCMA Runner\config.json`
- Bounded rotating logs (fixed event names and safe fields only — never a
  secret, a response body, or raw exception text): `%LOCALAPPDATA%\MCMA Runner\logs\workstation_runner.log`

### Running it from source

```
python -m mcma.app.workstation_runner        # with a console, for development
pythonw -m mcma.app.workstation_runner       # no console — how an employee actually launches it
```

### Pairing against the VM (manual, by a human)

1. An administrator creates a pairing code for the target employee via
   `POST /admin/runner-enrollments` (or the `/administration/runners` page).
2. Launch the workstation runner; in the pairing form, enter the central
   server's `https://` origin, optionally a CA certificate file, a
   workstation label, and the one-time pairing code; click **"Associer ce
   poste"**.
3. On success the app switches to the paired-status view and starts
   heartbeating every `heartbeat_interval_seconds` (server-provided, default
   10 s in Phase 1A).

### What to expect

- Both `acct-mcma-oujda` and `acct-mcma-nador` show `NOT_CONFIGURED` for the
  lifetime of this phase — that is expected, not a bug, until the
  browser-session phase lands.
- No job is ever created, claimed, or executed by this process in this
  phase.
```

- [ ] **Step 3 (no commit):** leave the doc change unstaged, per this run's "do not commit" instruction.

---

### Task 11: Full verification

- [ ] **Step 1:** New focused tests — `python -m pytest tests/app/workstation_runner/ -v`
- [ ] **Step 2:** Existing runner-registry + central tests still green — `python -m pytest tests/app/api/test_runner_registry.py tests/app/api/test_runner_body_limit.py tests/central/test_central_runner_registry.py -v`
- [ ] **Step 3:** Full backend suite with the repo's normal local deselection — `python -m pytest -m "not egress_proof"`
- [ ] **Step 4:** Import boundaries — `lint-imports`
- [ ] **Step 5:** Whitespace/diff hygiene — `git diff --check`
- [ ] **Step 6:** Real DPAPI tests on this Windows machine — `python -m pytest tests/app/workstation_runner/test_identity_dpapi_windows.py -v` and confirm `tests/execution/jobs/test_inputs_dpapi_windows.py` (pre-existing) is still green on this box.
- [ ] **Step 7:** `git status --short` and confirm the three untouched files (`Lancer_MCMA.cmd`, `Lancer_MCMA_Silencieux.vbs`, `MCMA_Ubuntu_Server_State_and_Deployment_Readiness_Report.md`) are unmodified and unstaged, and nothing has been committed.
- [ ] **Step 8:** Report architecture/trust-boundary decisions, every file changed, exact test results (pass/fail counts, not just "passed"), any limitation or deferred work, and `git status --short` output, to the requester.

---

## Self-Review Notes

- **Spec coverage:** GUI (French, 5 required fields/button/status — Task 8), enroll (Task 4/7), DPAPI CURRENT_USER persist+restore (Task 2/3), heartbeat automatic (Task 5/7), NOT_CONFIGURED reporting (Task 4/7), connection-state display without secrets (Task 7/8), clean stop (Task 5/7/9), pythonw-safe entrypoint (Task 9), single instance (Task 9), no browsers/login/job-dispatch/installer (explicitly out of scope, none of Tasks 1–10 touch `mcma.portal`/`mcma.execution`) — all covered.
- **Placeholder scan:** no TBD/"add error handling"/"similar to Task N" left in any step; every step has literal code.
- **Type consistency:** `RunnerIdentity`, `EnrollResult`, `HeartbeatResult`, `ControllerState`, `StatusMessage`, `LifecycleEvent` field names are used identically across Tasks 2, 4, 5, 7 — cross-checked while writing this plan. The one known rough edge is the `RunnerApp` constructor shape noted inline in Task 9 Step 4 (two-phase `bind_controller`), flagged explicitly rather than silently inconsistent with Task 8's single-phase sketch.
- **Review Focus coverage:** all five items above have an owning task and an explicit test (`test_load_fails_closed_on_corrupt_ciphertext`/`test_load_fails_closed_on_wrong_user_backend` in Task 2; `test_unauthorized_event_returns_controller_to_pairing_idle` in Task 7; `test_shutdown_is_safe_during_pairing_in_progress` in Task 7 plus `HeartbeatWorker.stop`'s bounded join in Task 5; `test_second_instance_is_refused_while_first_holds_the_mutex` in Task 9).
