"""Shared helpers for tests/central/*: a valid central Settings object on
tmp_path, and fake browser launchers (no Playwright, no network)."""

import os
from pathlib import Path

from mcma.core.config import RuntimeMode, Settings

KEY_A = bytes(range(32))
KEY_B = bytes(range(100, 132))


def write_key(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    if os.name == "posix":
        os.chmod(path, 0o600)
    return path


def central_settings(tmp_path: Path, **overrides) -> Settings:
    """Valid central settings. Directories and key files are real; the TLS
    files are only paths (composition does not open them -- run_central_
    server validates them before serving)."""
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "secrets").mkdir(exist_ok=True)
    if os.name == "posix":
        os.chmod(tmp_path / "vault", 0o700)
    write_key(tmp_path / "secrets" / "server.key", b"-----TLS PRIVATE KEY PLACEHOLDER-----")
    values = dict(
        runtime_mode=RuntimeMode.CENTRAL_SERVER,
        api_host="10.0.0.5",
        api_port=8443,
        db_path=tmp_path / "data" / "mcma.sqlite3",
        vault_dir=tmp_path / "vault",
        tls_cert_path=tmp_path / "secrets" / "server.crt",
        tls_key_path=tmp_path / "secrets" / "server.key",
        session_vault_key_path=write_key(tmp_path / "secrets" / "session.key", KEY_A),
        job_input_key_path=write_key(tmp_path / "secrets" / "inputs.key", KEY_B),
        instance_lock_path=tmp_path / "data" / "mcma.lock",
        headless_browser=True,
        allowed_host="sinauto.mamda-mcma.ma",
        mutex_name=f"mcma-central-test-{tmp_path.name}",
        poll_interval_seconds=0.01,
    )
    values.update(overrides)
    return Settings(**values)


class FakeBrowser:
    def __init__(self, headless):
        self.headless = headless
        self.closed = False
        self.connected = True

    def is_connected(self):
        return self.connected

    def disconnect(self):
        """Simulates Chromium dying after a successful launch."""
        self.connected = False


class FakeLauncher:
    """Stands in for launch_browser(headless=...). Records every launch."""

    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.launches = []
        self.closed_contexts = 0

    def __call__(self, *, headless=False):
        launcher = self

        class _Context:
            browser = None

            async def __aenter__(self_inner):
                if launcher.fail_times > 0:
                    launcher.fail_times -= 1
                    raise RuntimeError("chromium missing (fake)")
                browser = FakeBrowser(headless)
                self_inner.browser = browser
                launcher.launches.append(browser)
                return browser

            async def __aexit__(self_inner, *exc):
                self_inner.browser.closed = True
                launcher.closed_contexts += 1

        return _Context()
