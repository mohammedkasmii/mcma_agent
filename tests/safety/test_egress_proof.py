"""
INC-01 — egress lockdown proof tests.

Sentinel accuracy statement: connection failure to the sentinel targets
(192.0.2.1 / RFC 5737 TEST-NET-1, egress-sentinel.invalid / RFC 2606) is NOT,
by itself, proof of egress denial — a blackhole fails everywhere. The
authoritative evidence chain is: (1) enforced network-namespace isolation,
(2) the structural preflight confirming loopback-only networking, (3) the
subprocess and Chromium demonstrably inheriting that namespace, and (4) their
sentinel attempts failing inside that verified environment. The real MCMA
production hostname is never dialed, resolved, or referenced as a target.
"""

import socket
import subprocess
import sys
import threading

import pytest

from testsupport import egress_guard
from testsupport.egress_guard import EgressBlockedError

try:  # pytest-socket is a parallel defense-in-depth layer; either layer may fire first.
    from pytest_socket import SocketConnectBlockedError
except ImportError:  # pragma: no cover
    SocketConnectBlockedError = EgressBlockedError

SENTINEL_IP = "192.0.2.1"  # RFC 5737 TEST-NET-1 — never publicly routed
SENTINEL_PORT = 9


@pytest.mark.egress_proof
@pytest.mark.requires_egress_isolation
def test_egress_preflight_confirms_os_denial_without_emitting():
    """The structural preflight must positively confirm loopback-only isolation
    by inspection only (interfaces + all route tables + namespace identity +
    capabilities) — it never dials anything."""
    result = egress_guard.structural_preflight()
    assert result.confirmed, f"isolation not confirmed: {result.reason}"
    assert result.evidence, "preflight must record its structural evidence"


def test_socket_to_sentinel_host_is_blocked():
    """A direct dial of the sentinel is blocked in-process before any packet
    leaves (guard or pytest-socket layer — both are blocks)."""
    with pytest.raises((EgressBlockedError, SocketConnectBlockedError)):
        socket.create_connection((SENTINEL_IP, SENTINEL_PORT), timeout=2)


def test_non_loopback_socket_blocked_by_default():
    """Any non-loopback connect is blocked; loopback stays fully usable
    (a real ephemeral listener accepts a guarded connection)."""
    with pytest.raises((EgressBlockedError, SocketConnectBlockedError)):
        socket.create_connection(("198.51.100.1", 80), timeout=2)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    accepted = []

    def _accept():
        try:
            conn, _ = listener.accept()
            accepted.append(True)
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.close()
    t.join(timeout=5)
    listener.close()
    assert accepted, "loopback connection must be allowed and observable"


@pytest.mark.egress_proof
@pytest.mark.requires_egress_isolation
def test_subprocess_cannot_reach_sentinel_host():
    """A fresh, UNGUARDED child interpreter (no conftest, no plugin) must be
    unable to reach the sentinel — proving the OS-level namespace, not the
    in-process guard. Runs only after the structural preflight confirmed
    isolation (enforced at setup by the plugin)."""
    child_code = (
        "import socket, sys\n"
        "try:\n"
        f"    socket.create_connection(('{SENTINEL_IP}', {SENTINEL_PORT}), timeout=5)\n"
        "except OSError:\n"
        "    sys.exit(2)\n"
        "sys.exit(0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", child_code],
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 2, (
        "the unguarded subprocess reached (or did not cleanly fail to reach) "
        f"the sentinel: rc={proc.returncode} stderr={proc.stderr!r}"
    )


@pytest.mark.egress_proof
@pytest.mark.requires_egress_isolation
def test_headless_chromium_cannot_reach_sentinel_host():
    """Headless Chromium (normal sandbox, fresh context, no storage_state, no
    credentials) inherits the namespace and cannot reach the sentinel. Runs
    only after the structural preflight confirmed isolation."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, timeout=60_000)
        try:
            context = browser.new_context()
            page = context.new_page()
            with pytest.raises(PlaywrightError):
                page.goto(f"http://{SENTINEL_IP}:{SENTINEL_PORT}/", timeout=15_000)
        finally:
            browser.close()
