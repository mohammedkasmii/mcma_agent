"""
mcma.app.runners.dispatch -- durable workstation job-dispatch control
plane (Phase 1C-A): claim selection, lease renewal, release, and
server-time expiry recovery.

Scope boundary: this module performs NO Playwright work and NO form
filling -- it only durably records WHICH runner currently owns the right
to work a job, transports the already-verified typed_input to it once,
and lets that ownership be renewed, released, or reclaimed after expiry.
The next phase attaches the execution engine to this reviewed protocol;
nothing here calls mcma.portal, and this module never imports it (single-
owner import-linter contract: only mcma.portal may import playwright, and
mcma.app.runners has no reason to import mcma.portal at all).

Claim eligibility is derived ENTIRELY server-side, re-checked fresh inside
the claim transaction every time (never cached, never trusted from a
previous call):
  * the authenticated runner is ACTIVE and still eligible (registry.
    _ineligibility -- active user, jobs:execute, at least one MCMA
    account);
  * the runner's heartbeat is ONLINE by the SAME server-time rule the
    registry itself uses (registry.OFFLINE_AFTER_SECONDS);
  * the runner belongs to the SAME user as automation_jobs.
    requested_by_user_id -- a runner can never claim another employee's
    job;
  * the job's account is one of the two canonical MCMA accounts the
    runner is both permitted AND currently READY for (MAMDA is never
    reachable here -- registry._mcma_accounts_of() already excludes it);
  * the job has no active (CLAIMED) assignment, and the runner has no
    OTHER active assignment (first pilot: one job at a time per
    workstation);
  * the job is in an exact dispatchable (mode, status) pair: DRY_RUN+
    QUEUED or EXECUTE+PLANNED.

The oldest eligible job (by automation_jobs.created_at) is chosen, and the
whole selection-plus-claim-row-insert happens inside ONE BEGIN IMMEDIATE
transaction (mcma.app.auth.users.write_transaction) -- SQLite's own
exclusive write lock is what makes "two simultaneous claims can never
return the same job" a database guarantee, not a race two callers could
lose. A high-entropy opaque claim token is generated per claim; only its
SHA-256 digest is ever stored (compared in constant time), exactly the
same discipline as runner_enrollments.code_digest / runners.
credential_digest (0005).

typed_input is retrieved and verified through the EXISTING
retrieve_and_verify_job_input path (content-hash checked before anything
is parsed as JSON), and is never returned unless that verification
succeeds. If it does not, the job is failed closed via the EXISTING
fail_closed_on_runner_exception() path (never a new, ad-hoc failure
mechanism) and nothing is ever dispatched from a guess.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from mcma.app.auth.users import UserInputError, write_transaction
from mcma.app.runners.registry import (
    OFFLINE_AFTER_SECONDS, RunnerPrincipal, _ineligibility, _mcma_accounts_of, _validated_versions,
)
from mcma.execution.inputs import InputEncryptor, JobInputUnavailable, retrieve_and_verify_job_input
from mcma.execution.jobs import fail_closed_on_runner_exception

CLAIM_TOKEN_PREFIX = "mcma_ct_"
MAX_CLAIM_TOKEN_LENGTH = 200
DEFAULT_LEASE_TTL_SECONDS = 120

# The authoritative bounds for a claim response -- mirrored (as duplicated
# literals, never imported: mcma.app.workstation_runner must stay isolated
# from server code) in mcma.app.workstation_runner.protocol, and checked
# against them by tests/app/workstation_runner/test_protocol_drift.py.
# Enforced HERE, before a dispatch row is ever inserted (P1 correction):
# a validly decrypted but oversized/deep input must never become CLAIMED
# only to be rejected by the Windows client's own matching bounds and sit
# stuck until lease expiry -- it fails the job closed instead, exactly like
# an unverifiable input already does.
MAX_CLAIM_RESPONSE_BYTES = 262_144  # 256 KiB
MAX_TYPED_INPUT_DEPTH = 16

# The exact (mode, status) pairs a job may be claimed from -- nothing else,
# regardless of any future status this table's own CHECK constraint might
# one day accept on automation_jobs.
_DISPATCHABLE_MODE_STATUS = frozenset({("DRY_RUN", "QUEUED"), ("EXECUTE", "PLANNED")})

_RELEASE_REASONS = frozenset({"CANCELLED_BEFORE_EXECUTION", "RUNNER_SHUTDOWN", "EXECUTION_NOT_AVAILABLE"})

_CLAIM_NOT_FOUND = ("CLAIM_NOT_FOUND", "Jeton de réclamation invalide, expiré ou déjà utilisé.", 404)


def _err(code: str, message: str, status: int = 400) -> UserInputError:
    return UserInputError(code, message, status)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse(text: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(text) if text else None


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _digests_equal(stored: str, computed: str) -> bool:
    return hmac.compare_digest(stored, computed)


def new_claim_token() -> str:
    return CLAIM_TOKEN_PREFIX + secrets.token_urlsafe(32)


def _valid_claim_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(CLAIM_TOKEN_PREFIX)
        and len(CLAIM_TOKEN_PREFIX) < len(value) <= MAX_CLAIM_TOKEN_LENGTH
    )


def _valid_generation(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _json_depth(value: object, *, _current: int = 0) -> int:
    """Mirrors mcma.app.workstation_runner.http_client's own _json_depth
    EXACTLY (duplicated, not imported -- that package must stay isolated
    from server code): returns early once _current exceeds
    MAX_TYPED_INPUT_DEPTH, so this is recursion-safe even against an
    adversarially deep (but already-parsed, so already bounded by Python's
    own recursion limit) structure."""
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


def _valid_typed_input_shape(value: object) -> bool:
    return isinstance(value, dict) and _json_depth(value) <= MAX_TYPED_INPUT_DEPTH


@dataclass(frozen=True)
class JobEnvelope:
    """The immutable, server-owned claim result. Contains ONLY server-
    owned values -- nothing here is echoed from, or influenced by, the
    claim request body (which carries only protocol/app version).
    claim_token and typed_input are excluded from repr()/str() (never
    logged, never appear in a traceback) via field(repr=False); the actual
    HTTP response still carries them once, in the JSON body only, over TLS
    with Cache-Control: no-store -- see to_response_dict()."""

    job_id: str
    mode: str
    account_id: str
    workflow_name: str
    input_hash: str
    generation: int
    lease_expires_at: str
    claim_token: str = field(repr=False)
    typed_input: dict = field(repr=False)

    def to_response_dict(self) -> dict:
        return {
            "job_id": self.job_id, "mode": self.mode, "account_id": self.account_id,
            "workflow_name": self.workflow_name, "input_hash": self.input_hash,
            "generation": self.generation, "claim_token": self.claim_token,
            "lease_expires_at": self.lease_expires_at, "typed_input": self.typed_input,
        }


def _runner_online(row, now: datetime) -> bool:
    """The SAME server-time rule registry._connection_status() uses --
    duplicated here (a fresh literal, not an import of a private helper
    tied to the registry's own view-row shape) so this module's own
    eligibility check never silently drifts from a refactor over there
    without a visible diff here too."""
    seen = _parse(row["last_seen_at"])
    return seen is not None and (now - seen).total_seconds() <= OFFLINE_AFTER_SECONDS


def _ready_accounts(conn, runner_id: str) -> set:
    rows = conn.execute(
        "SELECT account_id FROM runner_account_capabilities WHERE runner_id = ? AND session_state = 'READY'",
        (runner_id,),
    ).fetchall()
    return {r["account_id"] for r in rows}


def _next_generation(conn, job_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(generation), 0) AS g FROM workstation_job_dispatch WHERE job_id = ?", (job_id,)
    ).fetchone()
    return int(row["g"]) + 1


# --------------------------------------------------------------------- #
# expiry recovery
# --------------------------------------------------------------------- #


def expire_stale_assignments(conn, *, now: Optional[datetime] = None) -> int:
    """Server-time lease recovery: every CLAIMED assignment whose lease has
    passed becomes EXPIRED, permanently fencing its token/generation (an
    EXPIRED row can never again match renew_job's or release_job's own
    `status = 'CLAIMED'` predicate). automation_jobs.status is left
    completely untouched -- dispatch never mutates it -- so a job becomes
    claimable again ONLY if its existing status is still one of the exact
    dispatchable pairs claim_job() itself selects from; a job already
    moved into a writing/verifying/human-review state by a future
    execution engine is never silently requeued from here.

    A lease is expired at `lease_expires_at <= now` (not `<`): a lease
    valid THROUGH a moment in time expires exactly AT that moment, never
    one tick after it -- so `renew_job`/`release_job` calling this first
    and then requiring `status = 'CLAIMED'` correctly refuse a request that
    lands exactly on the deadline, not just one that lands after it."""
    now = now or utcnow()
    stamp = _iso(now)
    with write_transaction(conn):
        expired = conn.execute(
            "SELECT assignment_id FROM workstation_job_dispatch WHERE status = 'CLAIMED' AND lease_expires_at <= ?",
            (stamp,),
        ).fetchall()
        for row in expired:
            conn.execute(
                "UPDATE workstation_job_dispatch SET status = 'EXPIRED', outcome_code = 'LEASE_EXPIRED', "
                "finished_at = ? WHERE assignment_id = ? AND status = 'CLAIMED'",
                (stamp, row["assignment_id"]),
            )
    return len(expired)


# --------------------------------------------------------------------- #
# claim
# --------------------------------------------------------------------- #


def claim_job(
    conn, principal: RunnerPrincipal, *, protocol_version: object, app_version: object,
    encryptor: InputEncryptor, now: Optional[datetime] = None,
) -> Optional[JobEnvelope]:
    """Returns the claimed job's immutable envelope, or None when no
    eligible work exists (the caller maps None to HTTP 204)."""
    now = now or utcnow()
    _validated_versions(protocol_version, app_version)
    expire_stale_assignments(conn, now=now)  # opportunistic recovery, own transaction -- see docstring above

    envelope: Optional[JobEnvelope] = None
    failed_job_id: Optional[str] = None
    failed_reason_code: Optional[str] = None

    with write_transaction(conn):
        runner_row = conn.execute("SELECT * FROM runners WHERE runner_id = ?", (principal.runner_id,)).fetchone()
        if runner_row is None or runner_row["status"] != "ACTIVE" or _ineligibility(conn, runner_row["user_id"]) is not None:
            raise _err("RUNNER_UNAUTHENTICATED", "Authentification du poste refusée.", 401)
        if not _runner_online(runner_row, now):
            return None  # offline -- no eligible work reported to it
        already_active = conn.execute(
            "SELECT 1 FROM workstation_job_dispatch WHERE runner_id = ? AND status = 'CLAIMED'",
            (principal.runner_id,),
        ).fetchone()
        if already_active is not None:
            return None  # first pilot: one active job per runner
        ready = _ready_accounts(conn, principal.runner_id)
        eligible_accounts = [a for a in _mcma_accounts_of(conn, runner_row["user_id"]) if a in ready]
        if not eligible_accounts:
            return None
        placeholders = ",".join("?" for _ in eligible_accounts)
        candidate = conn.execute(
            f"SELECT j.* FROM automation_jobs j "
            f"WHERE j.requested_by_user_id = ? AND j.account_id IN ({placeholders}) "
            f"AND ((j.mode = 'DRY_RUN' AND j.status = 'QUEUED') OR (j.mode = 'EXECUTE' AND j.status = 'PLANNED')) "
            f"AND NOT EXISTS (SELECT 1 FROM workstation_job_dispatch d WHERE d.job_id = j.job_id AND d.status = 'CLAIMED') "
            f"ORDER BY j.created_at ASC LIMIT 1",
            (runner_row["user_id"], *eligible_accounts),
        ).fetchone()
        if candidate is None:
            return None
        if (candidate["mode"], candidate["status"]) not in _DISPATCHABLE_MODE_STATUS:
            return None  # defensive; the SQL above already guarantees this

        try:
            plaintext = retrieve_and_verify_job_input(conn, candidate["job_id"], candidate["input_hash"], encryptor)
            typed_input = json.loads(plaintext)
            if not isinstance(typed_input, dict):
                raise ValueError("typed_input must be a JSON object")
        except JobInputUnavailable as exc:
            failed_job_id, failed_reason_code = candidate["job_id"], exc.reason_code
        # RecursionError (a RuntimeError, NOT a ValueError/TypeError): the
        # json module parses recursively, and an adversarially deep JSON
        # TEXT can exhaust Python's own recursion limit before it ever
        # becomes a dict this module could depth-check -- this must still
        # be a fixed, contained failure, never an uncaught 500.
        except (ValueError, TypeError, RecursionError):
            failed_job_id, failed_reason_code = candidate["job_id"], "INPUT_NOT_JSON"
        else:
            if not _valid_typed_input_shape(typed_input):
                # Verified (hash-matched, decrypted) but too deep to ever
                # be usable -- the Windows client enforces this SAME bound
                # (MAX_TYPED_INPUT_DEPTH) and would fail closed on receipt;
                # refusing here means it never becomes CLAIMED at all.
                failed_job_id, failed_reason_code = candidate["job_id"], "INPUT_TOO_DEEP"
            else:
                generation = _next_generation(conn, candidate["job_id"])
                claim_token = new_claim_token()
                lease_expires = now + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS)
                candidate_envelope = JobEnvelope(
                    job_id=candidate["job_id"], mode=candidate["mode"], account_id=candidate["account_id"],
                    workflow_name=candidate["workflow_name"], input_hash=candidate["input_hash"],
                    generation=generation, lease_expires_at=_iso(lease_expires),
                    claim_token=claim_token, typed_input=typed_input,
                )
                # The FULL response envelope, including overhead (field
                # names, claim token, quoting/escaping) -- not just
                # typed_input alone -- checked against the SAME
                # MAX_CLAIM_RESPONSE_BYTES bound the Windows client
                # enforces on receipt, BEFORE any row is inserted: nothing
                # generated here (the token, the generation number) is
                # persisted or returned unless this check passes.
                serialized = json.dumps(candidate_envelope.to_response_dict()).encode("utf-8")
                if len(serialized) > MAX_CLAIM_RESPONSE_BYTES:
                    failed_job_id, failed_reason_code = candidate["job_id"], "INPUT_TOO_LARGE"
                else:
                    conn.execute(
                        "INSERT INTO workstation_job_dispatch (assignment_id, job_id, runner_id, generation, "
                        "claim_token_digest, status, claimed_at, lease_expires_at) VALUES (?, ?, ?, ?, ?, 'CLAIMED', ?, ?)",
                        (uuid.uuid4().hex, candidate["job_id"], principal.runner_id, generation,
                         digest_token(claim_token), _iso(now), _iso(lease_expires)),
                    )
                    envelope = candidate_envelope

    if failed_job_id is not None:
        # Deliberately OUTSIDE the transaction above (which committed
        # nothing for this path): fail_closed_on_runner_exception() opens
        # its OWN BEGIN IMMEDIATE transaction, and SQLite does not support
        # nesting one inside another. Its own expected_from_statuses
        # re-check makes this race-safe even if a concurrent claim attempt
        # hits the exact same unavailable input at the same time -- see
        # this module's own docstring.
        fail_closed_on_runner_exception(conn, failed_job_id, failed_reason_code)
        return None
    return envelope


# --------------------------------------------------------------------- #
# renew / release
# --------------------------------------------------------------------- #


def _locate_claim_row(conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object):
    if not _valid_claim_token(claim_token):
        raise _err(*_CLAIM_NOT_FOUND)
    if not _valid_generation(generation):
        raise _err("BAD_REQUEST", "Génération invalide.")
    computed = digest_token(claim_token)
    row = conn.execute("SELECT * FROM workstation_job_dispatch WHERE claim_token_digest = ?", (computed,)).fetchone()
    if (
        row is None
        or not _digests_equal(row["claim_token_digest"], computed)
        or row["job_id"] != job_id
        or row["runner_id"] != principal.runner_id
        or row["generation"] != generation
        or row["status"] != "CLAIMED"
    ):
        raise _err(*_CLAIM_NOT_FOUND)  # one answer for every refusal -- wrong token, runner, generation, or already finished
    return row


def _account_still_authorized(conn, runner_user_id: str, job_row) -> bool:
    """True only if the claimed job STILL belongs to the runner's own
    employee AND that employee still has access to the job's exact
    account. Recomputed fresh every call (never cached, never trusted from
    claim time) -- an admin narrowing account access, or (defensively)
    anything that could otherwise disassociate a job from its employee,
    takes effect on the very next renewal."""
    return (
        job_row is not None
        and job_row["requested_by_user_id"] == runner_user_id
        and job_row["account_id"] in _mcma_accounts_of(conn, runner_user_id)
    )


def renew_job(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object,
    now: Optional[datetime] = None,
) -> dict:
    """Extends the lease using SERVER time. Never revives an expired
    assignment: expire_stale_assignments() runs FIRST, in its own
    transaction (SQLite does not support nesting one BEGIN IMMEDIATE inside
    another), fencing anything whose lease has already reached or passed
    `now`; an EXPIRED row's status is no longer 'CLAIMED', so
    _locate_claim_row() then refuses it through the same generic path as a
    wrong/stale token. Revoking the runner, or removing its account/user
    permission -- INCLUDING narrowing it to no longer cover the specific
    account this job belongs to -- is re-checked FRESH here (inside the
    transaction), never relying solely on the bearer-auth check that
    already ran moments earlier at the API layer, exactly like
    registry.heartbeat()'s own re-check. Every refusal in this function
    raises the SAME fixed CLAIM_NOT_FOUND/401 codes _locate_claim_row
    itself uses -- a caller can never distinguish "wrong token" from "your
    account access changed" from "this job is no longer yours"."""
    now = now or utcnow()
    expire_stale_assignments(conn, now=now)  # own transaction -- see docstring above
    with write_transaction(conn):
        row = _locate_claim_row(conn, principal, job_id=job_id, claim_token=claim_token, generation=generation)
        runner_row = conn.execute("SELECT * FROM runners WHERE runner_id = ?", (principal.runner_id,)).fetchone()
        if runner_row is None or runner_row["status"] != "ACTIVE" or _ineligibility(conn, runner_row["user_id"]) is not None:
            raise _err("RUNNER_UNAUTHENTICATED", "Authentification du poste refusée.", 401)
        job_row = conn.execute(
            "SELECT account_id, requested_by_user_id FROM automation_jobs WHERE job_id = ?", (row["job_id"],)
        ).fetchone()
        if not _account_still_authorized(conn, runner_row["user_id"], job_row):
            raise _err(*_CLAIM_NOT_FOUND)  # generic: never reveals job/account/token/permission as the cause
        lease_expires = now + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS)
        conn.execute(
            "UPDATE workstation_job_dispatch SET lease_expires_at = ?, last_renewed_at = ? "
            "WHERE assignment_id = ? AND status = 'CLAIMED'",
            (_iso(lease_expires), _iso(now), row["assignment_id"]),
        )
    return {"lease_expires_at": _iso(lease_expires), "server_time": _iso(now)}


def release_job(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object, reason_code: object,
    now: Optional[datetime] = None,
) -> dict:
    """Valid only pre-execution -- this phase performs no execution at
    all, so every CLAIMED assignment is, by construction, still
    pre-execution. `reason_code` is one fixed closed value, never client
    free text. expire_stale_assignments() runs FIRST (own transaction, same
    reasoning as renew_job): an already-expired assignment can never be
    released either -- it is EXPIRED/LEASE_EXPIRED, not RELEASED, and
    _locate_claim_row() refuses it through the same generic path."""
    now = now or utcnow()
    if not isinstance(reason_code, str) or reason_code not in _RELEASE_REASONS:
        raise _err("BAD_REQUEST", "Motif de libération invalide.")
    expire_stale_assignments(conn, now=now)  # own transaction -- see docstring above
    with write_transaction(conn):
        row = _locate_claim_row(conn, principal, job_id=job_id, claim_token=claim_token, generation=generation)
        conn.execute(
            "UPDATE workstation_job_dispatch SET status = 'RELEASED', outcome_code = ?, finished_at = ? "
            "WHERE assignment_id = ? AND status = 'CLAIMED'",
            (reason_code, _iso(now), row["assignment_id"]),
        )
    return {"status": "RELEASED", "server_time": _iso(now)}
