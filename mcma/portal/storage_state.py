"""
mcma.portal.storage_state -- strict, bounded validation of a Playwright
storage_state uploaded by a workstation runner for a SERVER-OWNED
notification session.

Nothing here is trusted: the payload crosses a machine boundary. It is
parsed with a loader that refuses duplicate keys and non-finite numbers,
checked against the EXACT supported shape (unknown fields refused), and
bounded in count, string length and total serialized size before anything is
encrypted or stored. A rejection carries only a fixed reason code -- never
the payload, a field value or an exception message.
"""

from __future__ import annotations

import json
import math
from urllib.parse import urlsplit

MAX_PLAINTEXT_BYTES = 262_144       # serialized storage_state, before encryption
MAX_COOKIES = 200
MAX_ORIGINS = 50
MAX_LOCAL_STORAGE_PER_ORIGIN = 200
MAX_NAME_LENGTH = 256
MAX_VALUE_LENGTH = 8192
MAX_DOMAIN_LENGTH = 253
MAX_PATH_LENGTH = 1024
MAX_ORIGIN_LENGTH = 300

PRODUCTION_PORTAL_HOST = "sinauto.mamda-mcma.ma"
# Cookie domains beyond the exact portal host that real SinAuto cookies may
# carry. An explicit, reviewed table -- never a "hostname endswith" rule.
# The parent domain applies ONLY to the production portal host.
REVIEWED_PARENT_COOKIE_DOMAINS = {PRODUCTION_PORTAL_HOST: ("mamda-mcma.ma",)}
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class PortalPolicy:
    """What an uploaded storage_state may refer to, derived ONLY from the
    server's configured portal host -- never from the request."""

    def __init__(self, portal_host: str) -> None:
        host = (portal_host or "").strip().lower()
        if not host or "/" in host or "@" in host or ":" in host.replace("::1", ""):
            raise ValueError("portal_host must be a bare hostname")
        self.host = host
        self.loopback = host in _LOOPBACK_HOSTS
        names = {host}
        for parent in REVIEWED_PARENT_COOKIE_DOMAINS.get(host, ()):
            names.add(parent)
        self.cookie_domains = frozenset(names | {"." + n for n in names}) if not self.loopback else frozenset({host})

    def origin_allowed(self, origin: str) -> bool:
        parts = urlsplit(origin)
        try:
            port = parts.port                       # ValueError for a malformed port
        except ValueError:
            return False
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            return False
        if parts.path or parts.query or parts.fragment:
            return False
        if (parts.hostname or "").lower() != self.host:
            return False
        if self.loopback:
            return parts.scheme in ("http", "https")          # test mock portal only
        return parts.scheme == "https" and port is None

    def domain_allowed(self, domain: str) -> bool:
        return domain.lower() in self.cookie_domains


_SAME_SITE = frozenset({"Strict", "Lax", "None"})
_COOKIE_KEYS = frozenset({"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"})


class StorageStateRejected(Exception):
    """Carries a fixed reason code only."""

    def __init__(self, reason: str = "SESSION_REJECTED") -> None:
        super().__init__(reason)
        self.reason = reason


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise StorageStateRejected()
    return dict(pairs)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise StorageStateRejected()
    return value


def _refuse_constant(_name: str):
    raise StorageStateRejected()


MAX_DEPTH = 8


def _too_deep(value: object) -> bool:
    """Iterative (no recursion): True when nesting exceeds MAX_DEPTH."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (dict, list)):
            if depth > MAX_DEPTH:
                return True
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children)
    return False


def strict_loads(raw: bytes) -> object:
    """JSON from already-bounded bytes: no NaN/Infinity, no 1e999, no
    duplicate keys, bounded nesting (RecursionError is a rejection)."""
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text, object_pairs_hook=_no_duplicates, parse_float=_finite_float, parse_constant=_refuse_constant,
        )
        if _too_deep(value):
            raise StorageStateRejected()
        return value
    except StorageStateRejected:
        raise
    except (ValueError, RecursionError, TypeError):
        raise StorageStateRejected() from None


def _text(value: object, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not value and not allow_empty):
        raise StorageStateRejected()
    return value


def _exact(obj: object, allowed: frozenset, required: frozenset) -> dict:
    if not isinstance(obj, dict) or set(obj) - allowed or required - set(obj):
        raise StorageStateRejected()
    return obj


def _cookie(cookie: object, policy: PortalPolicy) -> dict:
    cookie = _exact(cookie, _COOKIE_KEYS, _COOKIE_KEYS)
    _text(cookie["name"], MAX_NAME_LENGTH)
    _text(cookie["value"], MAX_VALUE_LENGTH, allow_empty=True)
    if not policy.domain_allowed(_text(cookie["domain"], MAX_DOMAIN_LENGTH)):
        raise StorageStateRejected()
    _text(cookie["path"], MAX_PATH_LENGTH)
    expires = cookie["expires"]
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
        raise StorageStateRejected()
    if not isinstance(cookie["httpOnly"], bool) or not isinstance(cookie["secure"], bool):
        raise StorageStateRejected()
    if cookie["sameSite"] not in _SAME_SITE:
        raise StorageStateRejected()
    return cookie


def _origin(entry: object, policy: PortalPolicy) -> dict:
    entry = _exact(entry, frozenset({"origin", "localStorage"}), frozenset({"origin", "localStorage"}))
    if not policy.origin_allowed(_text(entry["origin"], MAX_ORIGIN_LENGTH)):
        raise StorageStateRejected()
    items = entry["localStorage"]
    if not isinstance(items, list) or len(items) > MAX_LOCAL_STORAGE_PER_ORIGIN:
        raise StorageStateRejected()
    for item in items:
        item = _exact(item, frozenset({"name", "value"}), frozenset({"name", "value"}))
        _text(item["name"], MAX_NAME_LENGTH)
        _text(item["value"], MAX_VALUE_LENGTH, allow_empty=True)
    return entry


def validate_storage_state(state: object, *, portal_host: str) -> dict:
    """Returns the same (now trusted-shape) dict, or raises StorageStateRejected."""
    policy = PortalPolicy(portal_host)
    state = _exact(state, frozenset({"cookies", "origins"}), frozenset({"cookies", "origins"}))
    cookies = state["cookies"]
    origins = state["origins"]
    if not isinstance(cookies, list) or len(cookies) > MAX_COOKIES:
        raise StorageStateRejected()
    if not isinstance(origins, list) or len(origins) > MAX_ORIGINS:
        raise StorageStateRejected()
    for cookie in cookies:
        _cookie(cookie, policy)
    for entry in origins:
        _origin(entry, policy)
    if len(json.dumps(state, separators=(",", ":")).encode("utf-8")) > MAX_PLAINTEXT_BYTES:
        raise StorageStateRejected()
    return state
