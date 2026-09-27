"""mcma.app.workstation_runner.http_client -- the ONLY place this package
speaks HTTP. Bearer secret only ever appears in the Authorization header of
/runner/heartbeat; pairing code only ever appears in the JSON body of
/runner/enroll. Never logs a request/response body, header, or raw
transport exception text -- callers get one of three typed, fixed-message
exceptions and decide what (fixed, French) text to show."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from mcma.app.workstation_runner.protocol import (
    APP_VERSION, MAX_HEARTBEAT_INTERVAL_SECONDS, MAX_OFFLINE_AFTER_SECONDS,
    MAX_RUNNER_SECRET_LENGTH, MIN_HEARTBEAT_INTERVAL_SECONDS, MIN_OFFLINE_AFTER_SECONDS,
    PROTOCOL_VERSION, RUNNER_ACCOUNT_IDS, RUNNER_SECRET_PREFIX, SESSION_STATES,
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
    try:
        # .hostname and .port are lazy properties that raise ValueError for
        # a malformed netloc (e.g. a non-numeric or out-of-range port) --
        # both accessed inside this try so that raises our own fixed
        # message instead of leaking urllib's raw one.
        parts = urlsplit(server_origin)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("server_origin must be a bare https:// origin") from None
    if parts.scheme != "https" or not hostname or parts.username or parts.password:
        raise ValueError("server_origin must be a bare https:// origin")
    if parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("server_origin must be a bare https:// origin")
    netloc = hostname + (f":{port}" if port else "")
    return f"https://{netloc}"


def _valid_runner_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == _RUNNER_ID_LEN and all(c in "0123456789abcdef" for c in value)


def _valid_secret(value: object) -> bool:
    # Consistent with identity._valid_runner_secret (strictly greater-than,
    # not >=): a secret that is exactly the bare prefix with no random
    # suffix must never validate here, because it would then fail
    # identity.py's stricter check on every future load -- an enroll
    # response the client accepts but can never reload after a restart.
    return (
        isinstance(value, str)
        and value.startswith(RUNNER_SECRET_PREFIX)
        and len(RUNNER_SECRET_PREFIX) < len(value) <= MAX_RUNNER_SECRET_LENGTH
    )


def _valid_account_ids(value: object) -> tuple | None:
    # Entry TYPES are checked before uniqueness: set(value) raises a raw
    # TypeError for an unhashable entry (a dict or a list, both valid JSON
    # values a server response could contain), which used to escape this
    # function uncaught. Every entry is confirmed to be a hashable string
    # first; only then is it safe to call set() on the list at all.
    if not isinstance(value, list) or len(value) > len(RUNNER_ACCOUNT_IDS):
        return None
    if not all(isinstance(a, str) and a in RUNNER_ACCOUNT_IDS for a in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(value)


def _valid_bounded_int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _build_ssl_context(ca_cert_path: Path | None) -> ssl.SSLContext:
    """The ONLY place this package builds TLS trust. Never httpx's
    verify=True: that builds ssl.create_default_context(cafile=certifi.where())
    -- certifi's bundled CA list, which never sees anything imported into
    the Windows CurrentUser/LocalMachine certificate store. Never
    verify=<str> either (deprecated in httpx, and equivalent to the branch
    below anyway).

    With no CA file: ssl.create_default_context() (no cafile/capath/cadata)
    calls SSLContext.load_default_certs(), which on Windows enumerates the
    OS's own CA and ROOT certificate stores -- this is what actually
    "loads the operating-system trust configuration".

    With a CA file: that file is the ONLY trust anchor loaded (matching the
    previous verify=<str> behavior) -- it does not also load the OS store.

    Either way, hostname verification and CERT_REQUIRED are
    ssl.create_default_context()'s own defaults; nothing here weakens them,
    and there is no verify=False equivalent anywhere in this module."""
    try:
        if ca_cert_path is not None:
            return ssl.create_default_context(cafile=str(ca_cert_path))
        return ssl.create_default_context()
    except (ssl.SSLError, OSError, ValueError):
        # Never the original exception's text: it can quote the
        # certificate's path or its contents.
        raise ValueError("ca_cert_path is not a valid CA certificate") from None


class RegistryHttpClient:
    def __init__(self, server_origin: str, *, ca_cert_path: Path | None = None, transport: httpx.BaseTransport | None = None) -> None:
        origin = _validate_origin(server_origin)
        if ca_cert_path is not None and not Path(ca_cert_path).is_file():
            raise ValueError("ca_cert_path does not exist")
        ssl_context = _build_ssl_context(ca_cert_path)
        self._client = httpx.Client(
            base_url=origin,
            verify=ssl_context,
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
            body = response.json()
        except ValueError:
            raise RegistryProtocolError("response was not valid JSON") from None
        if not isinstance(body, dict):
            raise RegistryProtocolError("response body was not a JSON object")
        return body

    def enroll(self, pairing_code: str, *, workstation_label: str) -> EnrollResult:
        body = self._post("/runner/enroll", json_body={
            "pairing_code": pairing_code,
            "runner_label": workstation_label,
            "protocol_version": PROTOCOL_VERSION,
            "app_version": APP_VERSION,
        })
        accounts = _valid_account_ids(body.get("allowed_account_ids"))
        if (
            not _valid_runner_id(body.get("runner_id"))
            or not _valid_secret(body.get("runner_secret"))
            or not isinstance(body.get("runner_label"), str)
            or accounts is None
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

    def heartbeat(self, runner_secret: str, *, sessions: tuple = ()) -> HeartbeatResult:
        """RELEASE BLOCKER 3: `sessions` is real, currently-configured
        browser-session state ({"account_id": ..., "state": ...} dicts) --
        never a resend of `allowed_account_ids` from a previous response.
        Phase 1B-A has no browser sessions at all, so every caller passes
        the default empty tuple. The server's own registry.heartbeat()
        rejects the WHOLE request with ACCOUNT_NOT_ALLOWED if `sessions`
        names an account the employee no longer has access to -- treating
        a stale, locally-remembered `allowed_account_ids` as if it were
        still an authorization claim caused exactly that: once an admin
        narrowed the employee's access, every further heartbeat would be
        rejected forever. An empty `sessions` list can never trigger that
        check, and the response's `allowed_account_ids` remains available
        as pure informational, server-owned data (see HeartbeatResult)."""
        for session in sessions:
            if (
                not isinstance(session, dict) or set(session) != {"account_id", "state"}
                or session["account_id"] not in RUNNER_ACCOUNT_IDS or session["state"] not in SESSION_STATES
            ):
                raise ValueError("sessions must be real {account_id, state} entries for allowed accounts")
        body = self._post(
            "/runner/heartbeat",
            json_body={"protocol_version": PROTOCOL_VERSION, "app_version": APP_VERSION, "sessions": list(sessions)},
            headers={"Authorization": f"Bearer {runner_secret}"},
        )
        accounts = _valid_account_ids(body.get("allowed_account_ids"))
        if (
            body.get("status") != "ACTIVE"
            or accounts is None
            or not _valid_bounded_int(body.get("heartbeat_interval_seconds"), MIN_HEARTBEAT_INTERVAL_SECONDS, MAX_HEARTBEAT_INTERVAL_SECONDS)
            or not _valid_bounded_int(body.get("offline_after_seconds"), MIN_OFFLINE_AFTER_SECONDS, MAX_OFFLINE_AFTER_SECONDS)
        ):
            raise RegistryProtocolError("heartbeat response failed validation")
        return HeartbeatResult(
            status="ACTIVE", heartbeat_interval_seconds=body["heartbeat_interval_seconds"],
            offline_after_seconds=body["offline_after_seconds"], allowed_account_ids=accounts,
        )
