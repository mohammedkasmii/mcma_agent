"""
INC-01 — focused unit tests for the pre-collection Python egress guard
(defense-in-depth layer; the authoritative layer is the CI network
namespace — see ci/no-egress.md).
"""

import os
import socket
import threading

import pytest

from testsupport import egress_guard
from testsupport.egress_guard import EgressBlockedError

try:  # either in-process layer counts as a block for connect()
    from pytest_socket import SocketConnectBlockedError
except ImportError:  # pragma: no cover
    SocketConnectBlockedError = EgressBlockedError

BLOCKED = (EgressBlockedError, SocketConnectBlockedError)

EXTERNAL_V4 = "198.51.100.1"  # RFC 5737 TEST-NET-2
EXTERNAL_V6 = "2001:db8::1"  # RFC 3849 documentation prefix
EXTERNAL_NAME = "egress-sentinel.invalid"  # RFC 2606 reserved TLD


# --- TCP -------------------------------------------------------------------

def test_tcp_ipv4_connect_to_external_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        with pytest.raises(BLOCKED):
            s.connect((EXTERNAL_V4, 80))
    finally:
        s.close()


def test_tcp_connect_ex_to_external_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        with pytest.raises(BLOCKED):
            s.connect_ex((EXTERNAL_V4, 80))
    finally:
        s.close()


def test_tcp_ipv6_connect_to_external_blocked():
    if not socket.has_ipv6:
        pytest.skip("IPv6 unavailable")
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        with pytest.raises(BLOCKED):
            s.connect((EXTERNAL_V6, 80))
    finally:
        s.close()


def test_tcp_loopback_connect_allowed():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def _accept():
        try:
            conn, _ = listener.accept()
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    c.close()
    t.join(timeout=5)
    listener.close()


# --- UDP -------------------------------------------------------------------

def test_udp_sendto_external_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(EgressBlockedError):
            s.sendto(b"x", (EXTERNAL_V4, 53))
    finally:
        s.close()


def test_udp_sendto_loopback_allowed():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    port = receiver.getsockname()[1]
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sender.sendto(b"ping", ("127.0.0.1", port))
        receiver.settimeout(5)
        data, _ = receiver.recvfrom(16)
        assert data == b"ping"
    finally:
        sender.close()
        receiver.close()


# --- DNS (blocked BEFORE the real resolver is invoked) ---------------------

def test_dns_lookup_of_external_hostname_blocked_before_resolution():
    with pytest.raises(EgressBlockedError):
        socket.getaddrinfo(EXTERNAL_NAME, 80)
    with pytest.raises(EgressBlockedError):
        socket.gethostbyname(EXTERNAL_NAME)
    with pytest.raises(EgressBlockedError):
        socket.gethostbyname_ex(EXTERNAL_NAME)


def test_dns_loopback_names_allowed():
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo("127.0.0.1", 80)
    assert socket.gethostbyname("localhost")


# --- address-form rules ----------------------------------------------------

def test_ipv4_mapped_loopback_allowed_and_mapped_external_blocked():
    assert egress_guard.check_address_allowed(("::ffff:127.0.0.1", 80)) is True
    assert egress_guard.check_address_allowed((f"::ffff:{EXTERNAL_V4}", 80)) is False


def test_af_unix_or_socketpair_allowed(tmp_path):
    a, b = socket.socketpair()
    a.send(b"ok")
    assert b.recv(2) == b"ok"
    a.close()
    b.close()

    if hasattr(socket, "AF_UNIX") and os.name != "nt":
        path = str(tmp_path / "guard.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(1)
        cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cli.connect(path)  # must NOT be blocked
        cli.close()
        srv.close()


def test_malformed_or_unknown_address_forms_fail_closed():
    assert egress_guard.check_address_allowed(("not-localhost.example", 80)) is False
    assert egress_guard.check_address_allowed(12345) is False
    assert egress_guard.check_address_allowed(("", "not-a-port", "x", "y", "z")) is False
    assert egress_guard.check_address_allowed(None) is False


# --- installation invariants (amendment 5) ---------------------------------

def test_install_is_idempotent_and_never_wraps_wrapper():
    refs = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.socket.sendto,
        socket.create_connection,
        socket.getaddrinfo,
        socket.gethostbyname,
        socket.gethostbyname_ex,
    )
    egress_guard.install()
    egress_guard.install()
    egress_guard.install()
    assert refs == (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.socket.sendto,
        socket.create_connection,
        socket.getaddrinfo,
        socket.gethostbyname,
        socket.gethostbyname_ex,
    ), "repeated install() must never re-wrap the guarded functions"

    # blocking still active, loopback still allowed
    with pytest.raises(EgressBlockedError):
        socket.getaddrinfo(EXTERNAL_NAME, 80)
    assert socket.getaddrinfo("127.0.0.1", 80)


def test_no_public_disable_or_restore_function():
    for name in ("uninstall", "disable", "restore", "deactivate", "teardown", "reset"):
        assert not hasattr(egress_guard, name), (
            f"the guard must not expose a public {name}() escape hatch"
        )


def test_blocking_remains_active_after_pytest_configuration():
    """Post-configuration proof: with all plugins loaded and hooks run,
    non-loopback TCP, UDP, and DNS remain blocked."""
    with pytest.raises(BLOCKED):
        socket.create_connection((EXTERNAL_V4, 80), timeout=2)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(EgressBlockedError):
            s.sendto(b"x", (EXTERNAL_V4, 53))
    finally:
        s.close()
    with pytest.raises(EgressBlockedError):
        socket.getaddrinfo(EXTERNAL_NAME, 80)
