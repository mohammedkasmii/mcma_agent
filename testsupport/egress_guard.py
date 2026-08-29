"""
INC-01 — pre-collection egress guard + structural preflight (pytest plugin).

Defense-in-depth layer: blocks non-loopback network operations inside the
test process (TCP/UDP connect and send, and DNS resolution — an external
hostname is blocked BEFORE the real resolver is invoked, so not even a DNS
packet leaves the process). The AUTHORITATIVE layer is the loopback-only
Linux network namespace the CI job runs the whole suite in (ci/no-egress.md);
an in-process guard cannot constrain raw `_socket` usage, C extensions, or
subprocesses — the namespace can and does.

Installation is idempotent: originals are captured exactly once, repeated
install() calls never wrap a wrapper, and there is deliberately NO public
uninstall/disable/restore function.
"""

import ipaddress
import json
import os
import subprocess
import sys
from dataclasses import dataclass

import socket as _socket_mod

_INSTALLED = False
_ORIGINALS = {}

_LOOPBACK_NAMES = {"localhost", ""}


class EgressBlockedError(RuntimeError):
    """Raised for any non-loopback network operation attempted under test."""


# --------------------------------------------------------------------------
# Address policy
# --------------------------------------------------------------------------

def _host_is_loopback(host):
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except Exception:
            return False
    if not isinstance(host, str):
        return False
    if host in _LOOPBACK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        # A non-loopback hostname is never resolved, let alone dialed.
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def check_address_allowed(address, family=None):
    """True only for loopback destinations and AF_UNIX operations.
    Unknown or malformed address forms fail closed (False)."""
    try:
        if (
            family is not None
            and hasattr(_socket_mod, "AF_UNIX")
            and family == _socket_mod.AF_UNIX
        ):
            return True
        if isinstance(address, tuple) and 2 <= len(address) <= 4:
            return _host_is_loopback(address[0])
        return False
    except Exception:
        return False


def _ensure_allowed(address, family=None):
    try:
        allowed = check_address_allowed(address, family)
    except Exception:
        allowed = False
    if not allowed:
        raise EgressBlockedError(
            "INC-01 egress guard: non-loopback network operation blocked "
            f"(target={address!r}). Tests may only use loopback; the "
            "authoritative isolation is the CI network namespace "
            "(ci/no-egress.md)."
        )


def _dns_host_allowed(host):
    if host is None:
        return True
    return _host_is_loopback(host)


# --------------------------------------------------------------------------
# Guarded wrappers (originals captured exactly once; guard errors never fall
# through to the original operation)
# --------------------------------------------------------------------------

def _make_connect(orig):
    def guarded_connect(self, address, *args, **kwargs):
        _ensure_allowed(address, getattr(self, "family", None))
        return orig(self, address, *args, **kwargs)

    return guarded_connect


def _make_sendto(orig):
    def guarded_sendto(self, *args, **kwargs):
        if not args:
            raise EgressBlockedError("INC-01 egress guard: sendto without address")
        _ensure_allowed(args[-1], getattr(self, "family", None))
        return orig(self, *args, **kwargs)

    return guarded_sendto


def _make_sendmsg(orig):
    def guarded_sendmsg(self, *args, **kwargs):
        address = args[3] if len(args) >= 4 else kwargs.get("address")
        if address is not None:
            _ensure_allowed(address, getattr(self, "family", None))
        return orig(self, *args, **kwargs)

    return guarded_sendmsg


def _make_create_connection(orig):
    def guarded_create_connection(address, *args, **kwargs):
        _ensure_allowed(address, _socket_mod.AF_INET)
        return orig(address, *args, **kwargs)

    return guarded_create_connection


def _make_getaddrinfo(orig):
    def guarded_getaddrinfo(host, port, *args, **kwargs):
        if not _dns_host_allowed(host):
            raise EgressBlockedError(
                f"INC-01 egress guard: DNS lookup of non-loopback host {host!r} "
                "blocked before the resolver was invoked."
            )
        return orig(host, port, *args, **kwargs)

    return guarded_getaddrinfo


def _make_hostname_resolver(orig, api_name):
    def guarded_resolver(host, *args, **kwargs):
        if not _dns_host_allowed(host):
            raise EgressBlockedError(
                f"INC-01 egress guard: {api_name}({host!r}) blocked before the "
                "resolver was invoked."
            )
        return orig(host, *args, **kwargs)

    return guarded_resolver


def install():
    """Idempotent. Captures originals exactly once; never wraps a wrapper."""
    global _INSTALLED
    if _INSTALLED:
        return

    _ORIGINALS["socket.connect"] = _socket_mod.socket.connect
    _ORIGINALS["socket.connect_ex"] = _socket_mod.socket.connect_ex
    _ORIGINALS["socket.sendto"] = _socket_mod.socket.sendto
    _ORIGINALS["create_connection"] = _socket_mod.create_connection
    _ORIGINALS["getaddrinfo"] = _socket_mod.getaddrinfo
    _ORIGINALS["gethostbyname"] = _socket_mod.gethostbyname
    _ORIGINALS["gethostbyname_ex"] = _socket_mod.gethostbyname_ex

    _socket_mod.socket.connect = _make_connect(_ORIGINALS["socket.connect"])
    _socket_mod.socket.connect_ex = _make_connect(_ORIGINALS["socket.connect_ex"])
    _socket_mod.socket.sendto = _make_sendto(_ORIGINALS["socket.sendto"])
    _socket_mod.create_connection = _make_create_connection(
        _ORIGINALS["create_connection"]
    )
    _socket_mod.getaddrinfo = _make_getaddrinfo(_ORIGINALS["getaddrinfo"])
    _socket_mod.gethostbyname = _make_hostname_resolver(
        _ORIGINALS["gethostbyname"], "gethostbyname"
    )
    _socket_mod.gethostbyname_ex = _make_hostname_resolver(
        _ORIGINALS["gethostbyname_ex"], "gethostbyname_ex"
    )

    if hasattr(_socket_mod.socket, "sendmsg"):
        _ORIGINALS["socket.sendmsg"] = _socket_mod.socket.sendmsg
        _socket_mod.socket.sendmsg = _make_sendmsg(_ORIGINALS["socket.sendmsg"])

    _INSTALLED = True


# --------------------------------------------------------------------------
# Structural preflight (read-only, no emission)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PreflightResult:
    confirmed: bool
    evidence: str
    reason: str


_PREFLIGHT_CACHE = None


def _run_ip(args):
    proc = subprocess.run(
        ["ip", "-j"] + args, capture_output=True, text=True, timeout=10
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ip {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "[]")


def _capabilities_all_zero():
    with open("/proc/self/status", "r", encoding="ascii", errors="replace") as f:
        for line in f:
            if line.startswith("CapEff:"):
                return int(line.split(":", 1)[1].strip(), 16) == 0
    return False


def _named_netns_verified():
    name = os.environ.get("MCMA_NETNS_NAME", "")
    if not name or "/" in name or ".." in name:
        return False, "MCMA_NETNS_NAME is not set to a valid namespace name"
    self_ino = os.stat("/proc/self/ns/net").st_ino
    for base in ("/run/netns", "/var/run/netns"):
        path = os.path.join(base, name)
        try:
            if os.stat(path).st_ino == self_ino:
                return True, f"named netns {name!r} inode matches /proc/self/ns/net"
        except OSError:
            continue
    return False, f"process is not inside the named netns {name!r}"


def structural_preflight():
    """Confirms loopback-only isolation by inspection only — never dials.

    Confirmed requires ALL of (Linux only):
      - euid != 0 and an all-zero effective capability set (cannot create
        interfaces, change routes, or escape the namespace);
      - the process runs inside the named netns (MCMA_NETNS_NAME inode match);
      - `lo` is the only interface present (extra DOWN interfaces rejected);
      - every IPv4 and IPv6 route across ALL route tables is bound to `lo`
        (absence of a default route alone is NOT sufficient).
    """
    global _PREFLIGHT_CACHE
    if _PREFLIGHT_CACHE is not None:
        return _PREFLIGHT_CACHE

    def fail(reason):
        return PreflightResult(False, "", reason)

    try:
        if sys.platform != "linux":
            result = fail(
                "this host is not a loopback-only isolated environment; the "
                "authoritative run is the CI network-namespace job"
            )
        elif os.geteuid() == 0:
            result = fail("running as root — tests must run unprivileged")
        elif not _capabilities_all_zero():
            result = fail(
                "process holds effective capabilities (could alter interfaces/"
                "routes or escape the namespace)"
            )
        else:
            ns_ok, ns_msg = _named_netns_verified()
            if not ns_ok:
                result = fail(ns_msg)
            else:
                links = _run_ip(["link", "show"])
                extra = [l.get("ifname") for l in links if l.get("ifname") != "lo"]
                if extra:
                    result = fail(f"non-loopback interfaces present: {extra}")
                else:
                    bad_routes = []
                    for fam in ("-4", "-6"):
                        for route in _run_ip([fam, "route", "show", "table", "all"]):
                            if route.get("dev") != "lo":
                                bad_routes.append(route)
                    if bad_routes:
                        result = fail(f"non-loopback routes present: {bad_routes}")
                    else:
                        result = PreflightResult(
                            True,
                            f"{ns_msg}; interfaces=[lo]; all v4/v6 route tables "
                            "loopback-only; euid!=0; CapEff=0",
                            "",
                        )
    except Exception as exc:
        result = fail(f"preflight inspection failed: {exc!r}")

    _PREFLIGHT_CACHE = result
    return result


# --------------------------------------------------------------------------
# pytest plugin hooks
# --------------------------------------------------------------------------

def pytest_configure(config):
    install()


def pytest_runtest_setup(item):
    if item.get_closest_marker("requires_egress_isolation"):
        result = structural_preflight()
        if not result.confirmed:
            import pytest

            pytest.fail(
                "requires_egress_isolation: refusing to run outside verified "
                f"loopback-only isolation — {result.reason}. See ci/no-egress.md. "
                'Local runs may deselect with: python -m pytest -m "not egress_proof"',
                pytrace=False,
            )


def pytest_report_header(config):
    result = structural_preflight()
    state = "CONFIRMED" if result.confirmed else f"not confirmed ({result.reason})"
    return [f"INC-01 egress guard: installed (loopback-only) | OS isolation: {state}"]
