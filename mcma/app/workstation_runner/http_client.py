"""mcma.app.workstation_runner.http_client -- the ONLY place this package
speaks HTTP. Bearer secret only ever appears in the Authorization header of
/runner/heartbeat; pairing code only ever appears in the JSON body of
/runner/enroll. Never logs a request/response body, header, or raw
transport exception text -- callers get one of three typed, fixed-message
exceptions and decide what (fixed, French) text to show."""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

from mcma.app.workstation_runner.protocol import (
    APP_VERSION, CLAIM_TOKEN_PREFIX, FINISH_RESULTS, JOB_MODES, MAX_CLAIM_RESPONSE_BYTES, MAX_CLAIM_TOKEN_LENGTH,
    MAX_HEARTBEAT_INTERVAL_SECONDS, MAX_OFFLINE_AFTER_SECONDS, MAX_RUNNER_SECRET_LENGTH, MAX_TYPED_INPUT_DEPTH,
    MIN_HEARTBEAT_INTERVAL_SECONDS, MIN_OFFLINE_AFTER_SECONDS, PROTOCOL_VERSION, RELEASE_REASONS,
    RUNNER_ACCOUNT_IDS, RUNNER_SECRET_PREFIX, SESSION_STATES,
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


class RegistryAccountNotAllowed(RegistryProtocolError):
    """The server rejected a heartbeat's `sessions` with HTTP 400 and the
    fixed error code ACCOUNT_NOT_ALLOWED: an administrator removed one of
    the reported accounts before this runner learned about it. A stable,
    typed subtype of RegistryProtocolError so existing generic handling
    still catches it, but the caller (HeartbeatLifecycle) can also match
    it specifically to retry once with an empty sessions claim. Fixed
    message only -- the response body is inspected for exactly this ONE
    field and is never logged, retained, or otherwise exposed."""

    def __init__(self) -> None:
        super().__init__("account not allowed")


class RegistryClaimNotFound(RegistryProtocolError):
    """The server rejected a renew/release with HTTP 404 and the fixed
    error code CLAIM_NOT_FOUND: the claim token is stale, wrong, expired,
    already released, or belongs to a different assignment/generation. A
    stable, typed subtype of RegistryProtocolError -- existing generic
    handling still catches it, but a caller can also match it specifically
    to stop treating the job as owned. Fixed message only -- the response
    body is inspected for exactly this ONE field and is never logged,
    retained, or otherwise exposed."""

    def __init__(self) -> None:
        super().__init__("claim not found")


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


@dataclass(frozen=True)
class ClaimedJob:
    """A dispatched job envelope. `claim_token` and `typed_input` are
    `repr=False` so the dataclass-generated __repr__ (and therefore str())
    never includes them -- logging, printing, or exception-formatting this
    object cannot leak the credential or the (possibly PII-bearing)
    verified job input."""

    job_id: str
    mode: str
    account_id: str
    workflow_name: str
    input_hash: str
    generation: int
    lease_expires_at: str
    claim_token: str = field(repr=False)
    typed_input: dict = field(repr=False)


@dataclass(frozen=True)
class RenewResult:
    lease_expires_at: str
    server_time: str


@dataclass(frozen=True)
class ReleaseResult:
    status: str
    server_time: str


@dataclass(frozen=True)
class StartedJob:
    """Phase 1C-B: the result of /runner/jobs/{job_id}/start. Two shapes
    only -- `status="NEEDS_REVIEW"` (the read-only gate never needs to run;
    plan_hash/lease_expires_at are both None, and a caller must not launch
    a browser) or `status="RUNNING"` (plan_hash/lease_expires_at are both
    present -- the caller cross-checks plan_hash against its OWN local
    rebuild BEFORE ever launching a browser, per the executor's own
    contract)."""

    status: str
    job_status: str
    plan_hash: Optional[str]
    lease_expires_at: Optional[str]


@dataclass(frozen=True)
class FinishResult:
    status: str
    job_status: str
    server_time: str


# Bounds for validating a claim response -- MAX_CLAIM_RESPONSE_BYTES and
# MAX_TYPED_INPUT_DEPTH come from protocol.py (the server's own dispatch.py
# enforces the SAME two bounds before a claim row is ever inserted -- see
# its module-level comment; tests/app/workstation_runner/test_protocol_drift.py
# is the tripwire keeping them identical). The rest are this client's own,
# deliberately generous but finite bounds, never trusting the network to
# hand us an unbounded response.
_MAX_WORKFLOW_NAME_LENGTH = 200
_MAX_INPUT_HASH_LENGTH = 128
_MAX_JOB_ID_LENGTH = 200
_MAX_TIMESTAMP_LENGTH = 64  # generous bound for an ISO-8601 timestamp string
_MAX_PLAN_HASH_LENGTH = 128  # a sha256 hex digest is 64 chars; generous margin

# The exact, closed response shapes start_job()/finish_job() ever accept --
# never a caller-supplied job/account/mode influencing which one wins.
_START_NEEDS_REVIEW_FIELDS = frozenset({"status", "job_status"})
_START_RUNNING_FIELDS = frozenset({"status", "job_status", "plan_hash", "lease_expires_at"})
_FINISH_RESPONSE_FIELDS = frozenset({"status", "job_status", "server_time"})
_FINISH_DISPATCH_STATUSES = frozenset({"SUCCEEDED", "FAILED"})
_FINISH_JOB_STATUSES = frozenset({"DRY_RUN_VERIFIED", "IDENTITY_FAILED"})


def _json_depth(value: object, *, _current: int = 0) -> int:
    if _current > MAX_TYPED_INPUT_DEPTH:
        return _current
    if isinstance(value, dict):
        if not value:
            return _current + 1
        return max(_json_depth(v, _current=_current + 1) for v in value.values())
    if isinstance(value, list):
        if not value:
            return _current + 1
        return max(_json_depth(v, _current=_current + 1) for v in value)
    return _current


def _valid_typed_input(value: object) -> bool:
    return isinstance(value, dict) and _json_depth(value) <= MAX_TYPED_INPUT_DEPTH


def _valid_generation(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _valid_claim_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(CLAIM_TOKEN_PREFIX)
        and len(CLAIM_TOKEN_PREFIX) < len(value) <= MAX_CLAIM_TOKEN_LENGTH
    )


def _valid_bounded_str(value: object, max_length: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= max_length


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

    def _post(
        self, path: str, *, json_body: dict, headers: dict | None = None, allow_no_content: bool = False,
    ) -> dict | None:
        try:
            response = self._client.post(path, json=json_body, headers=headers or {})
        except httpx.HTTPError:
            raise RegistryConnectionError("unreachable") from None
        finally:
            self._client.cookies.clear()  # never let a Set-Cookie survive to the next call
        if len(response.content) > MAX_CLAIM_RESPONSE_BYTES:
            raise RegistryProtocolError("response too large")
        if response.status_code == 401:
            raise RegistryUnauthorized("credential rejected")
        if response.status_code == 400:
            # Detect ONLY this one fixed error field -- never inspect,
            # log, or otherwise expose anything else in the body. Any
            # other 400 shape falls straight through to the generic
            # protocol-error path below, unchanged.
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            if isinstance(error_body, dict) and error_body.get("error") == "ACCOUNT_NOT_ALLOWED":
                raise RegistryAccountNotAllowed()
        if response.status_code == 404:
            # Same fixed-field-only inspection discipline as the 400 branch
            # above, for the one endpoint family (renew/release) that can
            # return CLAIM_NOT_FOUND.
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            if isinstance(error_body, dict) and error_body.get("error") == "CLAIM_NOT_FOUND":
                raise RegistryClaimNotFound()
        if allow_no_content and response.status_code == 204:
            return None
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
        assert body is not None  # allow_no_content defaults to False: _post never returns None here
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
        assert body is not None  # allow_no_content defaults to False: _post never returns None here
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

    # ------------------------- job dispatch (1C-A) ------------------------ #
    # No polling worker or execution handler here -- this package only
    # speaks the wire protocol. Claiming, renewing, and releasing jobs is
    # driven by a caller in a later pass; this client never retries a claim
    # (a retried claim could duplicate one), and never retains a claim
    # token or typed_input beyond the ClaimedJob instance it returns.

    _CLAIM_RESPONSE_FIELDS = frozenset({
        "job_id", "mode", "account_id", "workflow_name", "input_hash",
        "generation", "lease_expires_at", "claim_token", "typed_input",
    })

    def claim_job(self, runner_secret: str) -> ClaimedJob | None:
        body = self._post(
            "/runner/jobs/claim",
            json_body={"protocol_version": PROTOCOL_VERSION, "app_version": APP_VERSION},
            headers={"Authorization": f"Bearer {runner_secret}"},
            allow_no_content=True,
        )
        if body is None:
            return None  # 204: no eligible work right now
        if set(body) != self._CLAIM_RESPONSE_FIELDS:
            raise RegistryProtocolError("claim response failed validation")
        if (
            not _valid_bounded_str(body.get("job_id"), _MAX_JOB_ID_LENGTH)
            or body.get("mode") not in JOB_MODES
            or body.get("account_id") not in RUNNER_ACCOUNT_IDS
            or not _valid_bounded_str(body.get("workflow_name"), _MAX_WORKFLOW_NAME_LENGTH)
            or not _valid_bounded_str(body.get("input_hash"), _MAX_INPUT_HASH_LENGTH)
            or not _valid_generation(body.get("generation"))
            or not _valid_bounded_str(body.get("lease_expires_at"), _MAX_TIMESTAMP_LENGTH)
            or not _valid_claim_token(body.get("claim_token"))
            or not _valid_typed_input(body.get("typed_input"))
        ):
            raise RegistryProtocolError("claim response failed validation")
        return ClaimedJob(
            job_id=body["job_id"], mode=body["mode"], account_id=body["account_id"],
            workflow_name=body["workflow_name"], input_hash=body["input_hash"],
            generation=body["generation"], lease_expires_at=body["lease_expires_at"],
            claim_token=body["claim_token"], typed_input=body["typed_input"],
        )

    def renew_job(self, runner_secret: str, *, job_id: str, claim_token: str, generation: int) -> RenewResult:
        body = self._post(
            f"/runner/jobs/{job_id}/renew",
            json_body={"claim_token": claim_token, "generation": generation},
            headers={"Authorization": f"Bearer {runner_secret}"},
        )
        assert body is not None  # allow_no_content defaults to False: _post never returns None here
        if (
            set(body) != {"lease_expires_at", "server_time"}
            or not _valid_bounded_str(body.get("lease_expires_at"), _MAX_TIMESTAMP_LENGTH)
            or not _valid_bounded_str(body.get("server_time"), _MAX_TIMESTAMP_LENGTH)
        ):
            raise RegistryProtocolError("renew response failed validation")
        return RenewResult(lease_expires_at=body["lease_expires_at"], server_time=body["server_time"])

    def release_job(
        self, runner_secret: str, *, job_id: str, claim_token: str, generation: int, reason_code: str,
    ) -> ReleaseResult:
        if reason_code not in RELEASE_REASONS:
            # Never sent to the server: this is a fixed, closed client-side
            # enum, not a caller-supplied free-text status/error field.
            raise ValueError("reason_code must be one of RELEASE_REASONS")
        body = self._post(
            f"/runner/jobs/{job_id}/release",
            json_body={"claim_token": claim_token, "generation": generation, "reason_code": reason_code},
            headers={"Authorization": f"Bearer {runner_secret}"},
        )
        assert body is not None  # allow_no_content defaults to False: _post never returns None here
        if (
            set(body) != {"status", "server_time"}
            or body.get("status") != "RELEASED"
            or not _valid_bounded_str(body.get("server_time"), _MAX_TIMESTAMP_LENGTH)
        ):
            raise RegistryProtocolError("release response failed validation")
        return ReleaseResult(status=body["status"], server_time=body["server_time"])

    def start_job(self, runner_secret: str, *, job_id: str, claim_token: str, generation: int) -> StartedJob:
        """Two closed response shapes only -- see StartedJob's own
        docstring. Anything else (a third status, extra/missing fields,
        malformed plan_hash) fails closed with RegistryProtocolError,
        never a guess at which shape was intended."""
        body = self._post(
            f"/runner/jobs/{job_id}/start",
            json_body={"claim_token": claim_token, "generation": generation},
            headers={"Authorization": f"Bearer {runner_secret}"},
        )
        assert body is not None  # allow_no_content defaults to False: _post never returns None here
        if set(body) == _START_NEEDS_REVIEW_FIELDS:
            if body.get("status") != "NEEDS_REVIEW" or body.get("job_status") != "NEEDS_REVIEW":
                raise RegistryProtocolError("start response failed validation")
            return StartedJob(status="NEEDS_REVIEW", job_status="NEEDS_REVIEW", plan_hash=None, lease_expires_at=None)
        if set(body) == _START_RUNNING_FIELDS:
            if (
                body.get("status") != "RUNNING"
                or body.get("job_status") != "READ_ONLY_IDENTITY_CHECK"
                or not _valid_bounded_str(body.get("plan_hash"), _MAX_PLAN_HASH_LENGTH)
                or not _valid_bounded_str(body.get("lease_expires_at"), _MAX_TIMESTAMP_LENGTH)
            ):
                raise RegistryProtocolError("start response failed validation")
            return StartedJob(
                status="RUNNING", job_status="READ_ONLY_IDENTITY_CHECK",
                plan_hash=body["plan_hash"], lease_expires_at=body["lease_expires_at"],
            )
        raise RegistryProtocolError("start response failed validation")

    def finish_job(self, runner_secret: str, *, job_id: str, claim_token: str, generation: int, result: str) -> FinishResult:
        if result not in FINISH_RESULTS:
            # Never sent to the server: this is a fixed, closed client-side
            # enum, not a caller-supplied free-text status/error field.
            raise ValueError("result must be one of FINISH_RESULTS")
        body = self._post(
            f"/runner/jobs/{job_id}/finish",
            json_body={"claim_token": claim_token, "generation": generation, "result": result},
            headers={"Authorization": f"Bearer {runner_secret}"},
        )
        assert body is not None  # allow_no_content defaults to False: _post never returns None here
        if (
            set(body) != _FINISH_RESPONSE_FIELDS
            or body.get("status") not in _FINISH_DISPATCH_STATUSES
            or body.get("job_status") not in _FINISH_JOB_STATUSES
            or not _valid_bounded_str(body.get("server_time"), _MAX_TIMESTAMP_LENGTH)
        ):
            raise RegistryProtocolError("finish response failed validation")
        return FinishResult(status=body["status"], job_status=body["job_status"], server_time=body["server_time"])
