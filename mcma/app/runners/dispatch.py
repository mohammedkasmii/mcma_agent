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
from mcma.execution.jobs import (
    JobAuthorizationError, JobPreconditionMismatch, fail_closed_on_runner_exception, transition,
    transition_on_browser_closed,
)
from mcma.mapping.wexia import parse_wexia
from mcma.planning.registry import WorkflowRegistry

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

# Every (mode, status) pair this table's schema and wire protocol
# recognize -- independent of which are currently ENABLED for dispatch
# (see EXECUTE_DISPATCH_ENABLED below). This is what
# tests/app/workstation_runner/test_protocol_drift.py checks
# protocol.JOB_MODES against: the envelope's `mode` field can structurally
# be either value, even while only one is ever actually dispatched today.
_ALL_KNOWN_MODE_STATUS_PAIRS = frozenset({("DRY_RUN", "QUEUED"), ("EXECUTE", "PLANNED")})

# Phase 1C-B, item C: the explicit, server-owned capability gate. Phase
# 1C-A's schema and claim_job's own (mode, status) matching already
# understand EXECUTE envelopes, but the workstation worker/executor built
# in this phase performs ONLY the read-only DRY_RUN identity check -- there
# is no form-filling, no writer, nothing that could safely consume an
# EXECUTE dispatch yet. With this False (the only value used anywhere in
# this codebase today -- flipping it is a future increment's decision, not
# a runtime config knob), _DISPATCHABLE_MODE_STATUS below excludes EXECUTE
# entirely, so claim_job can never select one, REGARDLESS of a job's own
# state. A client cannot request EXECUTE either way: claim_job's request
# body carries only protocol_version/app_version, never a mode choice.
EXECUTE_DISPATCH_ENABLED = False

# The exact (mode, status) pairs a job may ACTUALLY be claimed from right
# now -- nothing else, regardless of any future status this table's own
# CHECK constraint might one day accept on automation_jobs. A function of
# the gate, not a module-level constant, ONLY so a test can construct an
# explicitly-enabled call without flipping the production module constant
# (see claim_job's/start_job's own `execute_dispatch_enabled` parameter --
# never a hidden env var, never client-settable): every production call
# site omits the parameter and gets EXECUTE_DISPATCH_ENABLED (False) here,
# unchanged from before this was a function.
def _dispatchable_mode_status(execute_dispatch_enabled: bool) -> frozenset:
    return frozenset(
        {("DRY_RUN", "QUEUED")} | ({("EXECUTE", "PLANNED")} if execute_dispatch_enabled else set())
    )


# The SQL fragment mirroring _dispatchable_mode_status exactly -- built
# from the SAME gate, so the candidate-selection query and the defensive
# Python re-check below can never drift apart from each other.
def _mode_status_sql(execute_dispatch_enabled: bool) -> str:
    sql = "(j.mode = 'DRY_RUN' AND j.status = 'QUEUED')"
    if execute_dispatch_enabled:
        sql += " OR (j.mode = 'EXECUTE' AND j.status = 'PLANNED')"
    return sql

_RELEASE_REASONS = frozenset({"CANCELLED_BEFORE_EXECUTION", "RUNNER_SHUTDOWN", "EXECUTION_NOT_AVAILABLE"})

# Phase 1C-B, item B/E: the fixed, closed result enum the workstation may
# report to /runner/jobs/{job_id}/finish -- never arbitrary status/error
# text. Maps 1:1 to a dispatch outcome_code (mcma.persistence.migrations.
# 0007_workstation_job_dispatch_lifecycle.sql's CHECK constraint uses the
# SAME literal set) and, in turn, to a fixed automation_jobs status/
# reason_code below (see _FINISH_RESULT_TO_JOB_STATUS).
FINISH_RESULTS = frozenset(
    {"IDENTITY_MATCHED", "IDENTITY_NOT_MATCHED", "SESSION_UNAVAILABLE", "PORTAL_READ_FAILED", "RUNNER_CANCELLED"}
)

# result -> (new automation_jobs status, job reason_code). Only
# IDENTITY_MATCHED is a success; every other fixed result is a truthful,
# distinct reason the read-only identity gate did not confirm identity --
# all land on the SAME IDENTITY_FAILED status run_dry_run_identity_check
# itself already uses for a "did not match" outcome, exactly like that
# function's own single boolean covers every non-match reason.
_FINISH_RESULT_TO_JOB_STATUS = {
    "IDENTITY_MATCHED": ("DRY_RUN_VERIFIED", None),
    "IDENTITY_NOT_MATCHED": ("IDENTITY_FAILED", "IDENTITY_NOT_MATCHED"),
    "SESSION_UNAVAILABLE": ("IDENTITY_FAILED", "SESSION_UNAVAILABLE"),
    "PORTAL_READ_FAILED": ("IDENTITY_FAILED", "PORTAL_READ_FAILED"),
    "RUNNER_CANCELLED": ("IDENTITY_FAILED", "RUNNER_CANCELLED"),
}

# Phase 1C-C: the fixed, closed result enum a claimed EXECUTE job may
# report to the SAME /runner/jobs/{job_id}/finish endpoint -- the server
# tells the two enums apart by the claimed assignment's own automation_
# jobs.mode, never by anything the request itself chooses. Mirrors
# mcma.app.workstation_runner.protocol.EXECUTE_FINISH_RESULTS exactly (see
# tests/app/workstation_runner/test_protocol_drift.py).
EXECUTE_FINISH_RESULTS = frozenset(
    {
        "READY_FOR_HUMAN_REVIEW", "IDENTITY_FAILED", "WRITE_ABORTED", "RUNNER_CANCELLED",
        "SESSION_NOT_READY", "INPUT_OR_PLAN_MISMATCH", "INTERNAL_EXECUTION_ERROR", "LEASE_LOST",
    }
)

# result -> (final automation_jobs status, job reason_code). Two families:
#   * IDENTITY_FAILED/SESSION_NOT_READY/INPUT_OR_PLAN_MISMATCH are all
#     PRE-WRITE verification failures (no mutation could have begun -- the
#     workstation's own executor never calls the injected write callable
#     until every one of these checks has already passed) -- one hop from
#     IDENTITY_VERIFYING to IDENTITY_FAILED, exactly like the EXECUTE
#     mermaid chart's own IDENTITY_VERIFYING -> IDENTITY_FAILED edge.
#   * READY_FOR_HUMAN_REVIEW/WRITE_ABORTED/RUNNER_CANCELLED/
#     INTERNAL_EXECUTION_ERROR/LEASE_LOST all mean the write callable was
#     actually invoked -- mutation MAY have begun -- so these chain through
#     IDENTITY_VERIFIED -> WRITING first (see _finish_execute_transitions):
#     never IDENTITY_FAILED, and never back to PLANNED/QUEUED, once that
#     line has been crossed. LEASE_LOST (Phase 1C-C correction, finding 4)
#     is the worker's own self-reported "a renewal failed and I stopped
#     mutating" outcome -- distinct from RUNNER_CANCELLED (an operator-
#     driven shutdown) even though both land on the SAME WRITE_ABORTED job
#     status; a finish() carrying either can also simply be REFUSED
#     (CLAIM_NOT_FOUND) if the lease had already genuinely expired server-
#     side by the time it arrives -- expire_stale_assignments' own fail-
#     closed path (INTERRUPTED_NEEDS_HUMAN_REVIEW) remains authoritative
#     in that case, and this table is never consulted for it.
_EXECUTE_FINISH_RESULT_TO_JOB_STATUS = {
    "READY_FOR_HUMAN_REVIEW": ("READY_FOR_HUMAN_REVIEW", None),
    "IDENTITY_FAILED": ("IDENTITY_FAILED", None),
    "SESSION_NOT_READY": ("IDENTITY_FAILED", "SESSION_NOT_READY"),
    "INPUT_OR_PLAN_MISMATCH": ("IDENTITY_FAILED", "INPUT_OR_PLAN_MISMATCH"),
    "WRITE_ABORTED": ("WRITE_ABORTED", None),
    "RUNNER_CANCELLED": ("WRITE_ABORTED", "RUNNER_CANCELLED"),
    "INTERNAL_EXECUTION_ERROR": ("WRITE_ABORTED", "INTERNAL_EXECUTION_ERROR"),
    "LEASE_LOST": ("WRITE_ABORTED", "LEASE_LOST"),
}

_CLAIM_NOT_FOUND = ("CLAIM_NOT_FOUND", "Jeton de réclamation invalide, expiré ou déjà utilisé.", 404)
_JOB_NOT_STARTABLE = ("JOB_NOT_STARTABLE", "Ce travail n'est plus disponible pour démarrage.", 409)


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
    """Server-time lease recovery: every active (CLAIMED or RUNNING)
    assignment whose lease has passed becomes EXPIRED, permanently fencing
    its token/generation (an EXPIRED row can never again match
    renew_job's/release_job's/finish_job's own active-status predicate).

    A CLAIMED assignment that expires before ever starting leaves the job
    completely untouched (still QUEUED, safely re-claimable -- 1C-A's own
    guarantee, unchanged): no portal work had begun, so there is nothing to
    interrupt. Every CLAIMED expiry is batched into ONE transaction, since
    none of them touch automation_jobs at all.

    Release-blocker correction: a RUNNING assignment's dispatch-row EXPIRED
    write and its automation_jobs fail-closed transition (via the EXISTING
    fail_closed_on_runner_exception(), never a new ad-hoc mechanism) now
    commit TOGETHER, in ONE transaction PER assignment -- never the dispatch
    row alone. A RUNNING assignment's job is, by start_job()'s own
    contract, durably at READ_ONLY_IDENTITY_CHECK; fail_closed_on_runner_
    exception already lands that status on INTERRUPTED_NEEDS_HUMAN_REVIEW
    (never back to QUEUED for a silent replay) -- exactly the "existing
    truthful interrupted/fail-closed job state" this must land in, and
    atomically so: a crash between the two writes can no longer leave
    dispatch=EXPIRED paired with a job still sitting at READ_ONLY_IDENTITY_
    CHECK that no future scan could ever repair (the assignment is no
    longer active, so it would never be selected again).

    Each RUNNING assignment gets its OWN transaction (never nested,
    fail_closed_on_runner_exception is called with in_transaction=True
    INSIDE it) -- a crash between two DIFFERENT assignments' own
    transactions can only ever leave the NOT-yet-committed one untouched
    (still RUNNING, picked up again by the very next scan), never a
    half-committed pair for the SAME assignment. Idempotent: a row already
    expired by an earlier or concurrent call (rowcount 0 on the conditional
    UPDATE) is skipped without touching automation_jobs a second time.

    A lease is expired at `lease_expires_at <= now` (not `<`): a lease
    valid THROUGH a moment in time expires exactly AT that moment, never
    one tick after it -- so `renew_job`/`release_job`/`finish_job` calling
    this first and then requiring an active status correctly refuse a
    request that lands exactly on the deadline, not just one after it."""
    now = now or utcnow()
    stamp = _iso(now)

    with write_transaction(conn):
        claimed_expired = conn.execute(
            "SELECT assignment_id FROM workstation_job_dispatch WHERE status = 'CLAIMED' AND lease_expires_at <= ?",
            (stamp,),
        ).fetchall()
        for row in claimed_expired:
            conn.execute(
                "UPDATE workstation_job_dispatch SET status = 'EXPIRED', outcome_code = 'LEASE_EXPIRED', "
                "finished_at = ? WHERE assignment_id = ? AND status = 'CLAIMED'",
                (stamp, row["assignment_id"]),
            )

    running_expired = conn.execute(
        "SELECT assignment_id, job_id FROM workstation_job_dispatch WHERE status = 'RUNNING' AND lease_expires_at <= ?",
        (stamp,),
    ).fetchall()
    running_count = 0
    for row in running_expired:
        with write_transaction(conn):
            # The lease-expiry re-check (`lease_expires_at <= ?`) is
            # repeated HERE, inside the very transaction that admits the
            # expiry -- not just in the SELECT above. That SELECT ran
            # outside any transaction; a concurrent renew_job() can commit
            # between it and this UPDATE, extending lease_expires_at into
            # the future while status stays 'RUNNING'. Without re-checking
            # the lease here, this UPDATE would still match on status alone
            # and wrongly expire a lease that was just renewed. rowcount==0
            # now means "renewed, finished, or otherwise fenced since the
            # scan" -- exactly like the pre-existing idempotent-replay case
            # below -- and automation_jobs is correctly left untouched.
            updated = conn.execute(
                "UPDATE workstation_job_dispatch SET status = 'EXPIRED', outcome_code = 'LEASE_EXPIRED', "
                "finished_at = ? WHERE assignment_id = ? AND status = 'RUNNING' AND lease_expires_at <= ?",
                (stamp, row["assignment_id"], stamp),
            )
            if updated.rowcount == 0:
                continue  # renewed, finished, or already expired concurrently -- nothing left to do, commits as a no-op
            fail_closed_on_runner_exception(conn, row["job_id"], "LEASE_EXPIRED", in_transaction=True)
            running_count += 1
    return len(claimed_expired) + running_count


# --------------------------------------------------------------------- #
# claim
# --------------------------------------------------------------------- #


def claim_job(
    conn, principal: RunnerPrincipal, *, protocol_version: object, app_version: object,
    encryptor: InputEncryptor, now: Optional[datetime] = None,
    execute_dispatch_enabled: bool = EXECUTE_DISPATCH_ENABLED,
) -> Optional[JobEnvelope]:
    """Returns the claimed job's immutable envelope, or None when no
    eligible work exists (the caller maps None to HTTP 204).

    `execute_dispatch_enabled` (Phase 1C-C): every production call site
    (mcma.app.api.runners) omits this and gets EXECUTE_DISPATCH_ENABLED
    (False) -- a plain Python default, never an environment variable and
    never a value the request body can influence. Tests construct an
    explicitly-enabled call by passing True directly."""
    now = now or utcnow()
    dispatchable_mode_status = _dispatchable_mode_status(execute_dispatch_enabled)
    mode_status_sql = _mode_status_sql(execute_dispatch_enabled)
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
            "SELECT 1 FROM workstation_job_dispatch WHERE runner_id = ? AND status IN ('CLAIMED', 'RUNNING')",
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
            f"AND ({mode_status_sql}) "
            f"AND NOT EXISTS (SELECT 1 FROM workstation_job_dispatch d WHERE d.job_id = j.job_id AND d.status IN ('CLAIMED', 'RUNNING')) "
            f"ORDER BY j.created_at ASC LIMIT 1",
            (runner_row["user_id"], *eligible_accounts),
        ).fetchone()
        if candidate is None:
            return None
        if (candidate["mode"], candidate["status"]) not in dispatchable_mode_status:
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


_ACTIVE_STATUSES = frozenset({"CLAIMED", "RUNNING"})


def _locate_claim_row(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object,
    expected_statuses: frozenset = frozenset({"CLAIMED"}),
):
    """`expected_statuses` narrows which lifecycle phase(s) this call may
    match -- renew_job accepts CLAIMED or RUNNING (a lease is renewed in
    either phase), release_job accepts only CLAIMED (RUNNING can never be
    released back to the queue), start_job accepts only CLAIMED, and
    finish_job accepts only RUNNING. Every caller gets the SAME one fixed
    refusal for every reason (wrong token, wrong runner/job/generation, or
    a status outside what THIS call accepts) -- never distinguishable."""
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
        or row["status"] not in expected_statuses
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
        row = _locate_claim_row(
            conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
            expected_statuses=_ACTIVE_STATUSES,  # CLAIMED or RUNNING -- a lease renews in either phase
        )
        runner_row = conn.execute("SELECT * FROM runners WHERE runner_id = ?", (principal.runner_id,)).fetchone()
        if runner_row is None or runner_row["status"] != "ACTIVE" or _ineligibility(conn, runner_row["user_id"]) is not None:
            raise _err("RUNNER_UNAUTHENTICATED", "Authentification du poste refusée.", 401)
        job_row = conn.execute(
            "SELECT account_id, requested_by_user_id FROM automation_jobs WHERE job_id = ?", (row["job_id"],)
        ).fetchone()
        if not _account_still_authorized(conn, runner_row["user_id"], job_row):
            raise _err(*_CLAIM_NOT_FOUND)  # generic: never reveals job/account/token/permission as the cause
        # Correction (Phase 1C-C, finding 1): the job's EXACT account must
        # also still be reported READY by this runner -- a session that
        # dropped to LOGIN_REQUIRED/ERROR (or whose capability row
        # disappeared entirely) must stop renewing immediately, never
        # extending the lease, so a RUNNING EXECUTE assignment on it is
        # left to expire naturally and lands on INTERRUPTED_NEEDS_HUMAN_
        # REVIEW via expire_stale_assignments' EXISTING fail-closed path --
        # never silently kept alive on a session that can no longer be
        # trusted. Same generic refusal as every other check above.
        if job_row["account_id"] not in _ready_accounts(conn, principal.runner_id):
            raise _err(*_CLAIM_NOT_FOUND)
        lease_expires = now + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS)
        conn.execute(
            "UPDATE workstation_job_dispatch SET lease_expires_at = ?, last_renewed_at = ? "
            "WHERE assignment_id = ? AND status IN ('CLAIMED', 'RUNNING')",
            (_iso(lease_expires), _iso(now), row["assignment_id"]),
        )
    return {"lease_expires_at": _iso(lease_expires), "server_time": _iso(now)}


def release_job(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object, reason_code: object,
    now: Optional[datetime] = None,
) -> dict:
    """Valid only PRE-EXECUTION: CLAIMED only, never RUNNING (Phase 1C-B --
    once start_job() has moved an assignment to RUNNING, portal work may
    already be underway, and release_job's own docstring on `reason_code`
    -- "CANCELLED_BEFORE_EXECUTION" -- would no longer be truthful). This is
    _locate_claim_row's DEFAULT expected_statuses ({"CLAIMED"}), but passed
    explicitly here so this file never silently changes that guarantee by
    changing the default alone. `reason_code` is one fixed closed value,
    never client free text. expire_stale_assignments() runs FIRST (own
    transaction, same reasoning as renew_job): an already-expired
    assignment can never be released either -- it is EXPIRED/LEASE_EXPIRED,
    not RELEASED, and _locate_claim_row() refuses it through the same
    generic path."""
    now = now or utcnow()
    if not isinstance(reason_code, str) or reason_code not in _RELEASE_REASONS:
        raise _err("BAD_REQUEST", "Motif de libération invalide.")
    expire_stale_assignments(conn, now=now)  # own transaction -- see docstring above
    with write_transaction(conn):
        row = _locate_claim_row(
            conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
            expected_statuses=frozenset({"CLAIMED"}),
        )
        conn.execute(
            "UPDATE workstation_job_dispatch SET status = 'RELEASED', outcome_code = ?, finished_at = ? "
            "WHERE assignment_id = ? AND status = 'CLAIMED'",
            (reason_code, _iso(now), row["assignment_id"]),
        )
    return {"status": "RELEASED", "server_time": _iso(now)}


# --------------------------------------------------------------------- #
# start / finish (Phase 1C-B: server-owned DRY_RUN lifecycle)
# --------------------------------------------------------------------- #


def _start_eligibility_checks(conn, principal: RunnerPrincipal, row, *, now: datetime) -> dict:
    """Read-only, no mutation. Raises the SAME generic CLAIM_NOT_FOUND (or
    401 for a runner-level problem) every other lifecycle call uses --
    never a distinguishable reason. Called BOTH before planning (fails
    fast/cheaply on an already-ineligible attempt, before spending any
    planning work) and again, authoritatively, inside start_job's own
    final atomic transaction: planning takes real (if brief) time, and
    nothing checked before it may be trusted stale."""
    runner_row = conn.execute("SELECT * FROM runners WHERE runner_id = ?", (principal.runner_id,)).fetchone()
    if runner_row is None or runner_row["status"] != "ACTIVE" or _ineligibility(conn, runner_row["user_id"]) is not None:
        raise _err("RUNNER_UNAUTHENTICATED", "Authentification du poste refusée.", 401)
    if not _runner_online(runner_row, now):
        raise _err(*_CLAIM_NOT_FOUND)  # offline is as good as unauthenticated here -- same generic refusal
    job_row = conn.execute("SELECT * FROM automation_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
    if not _account_still_authorized(conn, runner_row["user_id"], job_row):
        raise _err(*_CLAIM_NOT_FOUND)
    if job_row["account_id"] not in _ready_accounts(conn, principal.runner_id):
        raise _err(*_CLAIM_NOT_FOUND)  # session no longer READY -- same generic refusal, same reasoning
    return job_row


def _job_snapshot(job_row) -> tuple:
    """The exact fields a plan is built from -- compared before/after
    planning (release-blocker correction) to prove nothing relevant
    changed in the gap. mode/input_hash/workflow_name never legitimately
    change on an existing row anywhere in this codebase, but this is
    re-verified as defense in depth, not assumed."""
    return (job_row["mode"], job_row["status"], job_row["input_hash"], job_row["workflow_name"])


def _require_execute_parent(conn, job_row) -> None:
    """Phase 1C-C, start_job's own EXECUTE branch: re-verifies the parent
    DRY_RUN relationship and its DRY_RUN_VERIFIED status FRESH, right
    before admission -- mcma.app.api.app's create_execution already
    checked this once at EXECUTE-job creation time (mcma.execution.jobs.
    run_execute_planning re-checks it again too), but nothing checked
    before this moment may be trusted stale: the parent could have been
    re-planned, superseded, or otherwise mutated in the time since this
    EXECUTE job was created and claimed. Raises the SAME generic
    _JOB_NOT_STARTABLE any other genuine state problem in this function
    uses -- never a token-forgery-shaped refusal."""
    parent_id = job_row["parent_job_id"]
    parent = conn.execute(
        "SELECT mode, status, account_id, workflow_name FROM automation_jobs WHERE job_id = ?", (parent_id,)
    ).fetchone() if parent_id else None
    if (
        parent is None
        or parent["mode"] != "DRY_RUN"
        or parent["status"] != "DRY_RUN_VERIFIED"
        or parent["account_id"] != job_row["account_id"]
        or parent["workflow_name"] != job_row["workflow_name"]
    ):
        raise _err(*_JOB_NOT_STARTABLE)


def start_job(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object,
    workflow_registry: WorkflowRegistry, encryptor: InputEncryptor, now: Optional[datetime] = None,
    execute_dispatch_enabled: bool = EXECUTE_DISPATCH_ENABLED,
) -> dict:
    """CLAIMED -> RUNNING (browser work about to begin), or straight to a
    terminal SUCCEEDED/NEEDS_REVIEW_NO_BROWSER when planning alone already
    resolves the job -- driven by re-running the SAME deterministic
    server-side planning every job-creation path uses, rebuilding the plan
    from the job's OWN retained, hash-verified input. NEVER trusts a
    client-supplied plan or plan_hash -- the claim request/response
    (mcma.app.runners.dispatch.claim_job) carries no such field at all.

    Release-blocker correction: the plan is rebuilt FIRST, PURELY (no
    mutation of either table -- retrieve_and_verify_job_input/parse_wexia/
    the workflow builder are all read-only/pure). Every mutation --
    QUEUED->PLANNING->{NEEDS_REVIEW|PLANNED[->READ_ONLY_IDENTITY_CHECK]}
    AND the matching CLAIMED->{SUCCEEDED|RUNNING} dispatch transition --
    then happens inside ONE BEGIN IMMEDIATE transaction, guarded by a
    FRESH re-check of everything (claim liveness/lease, runner ACTIVE/
    online, exact employee/account/READY, and the job's own mode/status/
    input_hash/workflow_name still matching what the plan was built from).
    If ANY of those fail, the transaction raises before touching either
    table, write_transaction() rolls back, and the job is left EXACTLY as
    it was (still QUEUED if nothing had mutated it) -- never a committed
    PLANNING/PLANNED with no matching dispatch admission, and never a
    stranded CLAIMED expiry that leaves automation_jobs untouched (1C-A's
    own guarantee) landing on a job that is no longer QUEUED.

    automation_jobs becomes non-dispatchable the moment PLANNING commits
    (inside that same transaction): a DRY_RUN job at PLANNING/PLANNED/
    NEEDS_REVIEW matches neither of claim_job's exact dispatchable (mode,
    status) pairs.

    Server time after planning: `now` is used, unchanged, for every check
    and timestamp UP TO the start of planning -- but planning itself takes
    real (if brief) wall-clock time, and a lease that was valid when this
    function was entered can legitimately expire while the plan is being
    built. `now_was_injected` records whether the CALLER supplied an
    explicit `now` (every test in this module does, for full determinism);
    when it did not (the only case in production), a genuinely FRESH
    `utcnow()` is taken right after planning completes and used for
    everything from that point on -- the second fencing pass, the final
    lease re-check, the eligibility re-check, and every timestamp this call
    persists. A test that wants to exercise this production behavior
    deterministically monkeypatches `dispatch.utcnow` itself and calls with
    `now=None`, rather than injecting `now` directly."""
    now_was_injected = now is not None
    now = now or utcnow()
    expire_stale_assignments(conn, now=now)  # own transaction -- opportunistic, before spending any planning work

    row = _locate_claim_row(
        conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
        expected_statuses=frozenset({"CLAIMED"}),
    )
    job_row = _start_eligibility_checks(conn, principal, row, now=now)
    mode = job_row["mode"]
    # A genuine, attributable state problem -- not a token-forgery boundary
    # -- so this is the one lifecycle refusal in this function that is NOT
    # folded into the generic CLAIM_NOT_FOUND. Phase 1C-C: EXECUTE is only
    # ever startable while explicitly enabled (see this function's own
    # `execute_dispatch_enabled` parameter) AND from PLANNED -- the exact
    # status enqueue_execute()/run_execute_planning() land a newly-created
    # EXECUTE job on.
    if mode == "DRY_RUN":
        if job_row["status"] != "QUEUED":
            raise _err(*_JOB_NOT_STARTABLE)
    elif mode == "EXECUTE" and execute_dispatch_enabled:
        if job_row["status"] != "PLANNED":
            raise _err(*_JOB_NOT_STARTABLE)
        _require_execute_parent(conn, job_row)
    else:
        raise _err(*_JOB_NOT_STARTABLE)
    snapshot = _job_snapshot(job_row)

    try:
        # PURE -- no I/O beyond the read-only, already-hash-verified input
        # fetch, and no mutation of automation_jobs or workstation_job_
        # dispatch anywhere in this block. Nothing has been committed for
        # this job yet, so a failure here leaves it exactly as it was
        # (still QUEUED) -- the transaction below is what then truthfully
        # lands both halves on ERROR/FAILED together, never leaving it
        # stranded mid-plan.
        plaintext = retrieve_and_verify_job_input(conn, job_row["job_id"], job_row["input_hash"], encryptor)
        typed_input = parse_wexia(json.loads(plaintext))
        plan = workflow_registry.get(job_row["workflow_name"])(typed_input)
        if mode == "EXECUTE" and plan.provenance.plan_hash != job_row["plan_hash"]:
            # The job's OWN already-approved plan_hash (set by
            # run_execute_planning at creation, re-verified against its
            # DRY_RUN parent then) no longer matches what this function
            # just independently rebuilt from the SAME retained input --
            # never trusted, always re-derived. Never executed on a
            # mismatch; the except block below fails this closed exactly
            # like any other planning failure.
            raise ValueError("EXECUTE plan_hash no longer matches the job's own retained approval")
        if mode == "EXECUTE" and plan.needs_review:
            # An approved EXECUTE plan must never need review -- its DRY_RUN
            # parent already resolved that. Treated as a planning failure,
            # never silently admitted.
            raise ValueError("EXECUTE plan unexpectedly needs review")
    except Exception as exc:
        reason_code = f"RUNNER_EXCEPTION_{type(exc).__name__}"
        with write_transaction(conn):
            # Land the job failure and the CLAIMED->FAILED assignment
            # TOGETHER, atomically -- a plan-build failure must never leave
            # automation_jobs at ERROR while workstation_job_dispatch is
            # still CLAIMED (that would strand the assignment, blocking the
            # runner from claiming other work, until natural lease expiry).
            # Re-locate the EXACT claim fresh, inside this transaction: if
            # it was concurrently released/expired/replaced by a newer
            # generation, this raises the same generic CLAIM_NOT_FOUND and
            # neither table is touched -- a stale generation can never
            # close a newer attempt.
            try:
                failure_row = _locate_claim_row(
                    conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
                    expected_statuses=frozenset({"CLAIMED"}),
                )
            except UserInputError:
                raise _err(*_CLAIM_NOT_FOUND) from None
            current_job = conn.execute(
                "SELECT status FROM automation_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            # The exact pre-planning status this job's OWN mode starts
            # planning from -- QUEUED for DRY_RUN, PLANNED for EXECUTE (see
            # this function's own admission check above). Phase 1C-C
            # correction: this used to hardcode "QUEUED", which wrongly
            # refused an EXECUTE plan-build failure with the generic
            # CLAIM_NOT_FOUND instead of truthfully landing it on ERROR/
            # PLANNING_FAILED below.
            expected_pre_planning_status = "QUEUED" if mode == "DRY_RUN" else "PLANNED"
            if current_job is None or current_job["status"] != expected_pre_planning_status:
                # Something else already moved the job (should be
                # unreachable if the claim above is still exactly CLAIMED,
                # but never assumed) -- refuse generically, touch nothing.
                raise _err(*_CLAIM_NOT_FOUND)
            fail_closed_on_runner_exception(conn, job_id, reason_code, in_transaction=True)
            conn.execute(
                "UPDATE workstation_job_dispatch SET status = 'FAILED', outcome_code = 'PLANNING_FAILED', "
                "finished_at = ? WHERE assignment_id = ? AND status = 'CLAIMED'",
                (_iso(now), failure_row["assignment_id"]),
            )
        raise _err(*_JOB_NOT_STARTABLE) from None

    # Server time taken AFTER planning: a genuinely fresh utcnow() call in
    # production (no `now` was injected), or the SAME injected value when a
    # test supplied one -- see the docstring above.
    admission_now = now if now_was_injected else utcnow()

    # Opportunistic second fencing pass, using that post-planning time: a
    # lease that expired during planning must be fenced BEFORE the final
    # transaction below ever re-locates the row -- never silently treated
    # as still CLAIMED just because it was valid when this function started.
    expire_stale_assignments(conn, now=admission_now)

    with write_transaction(conn):
        # Re-locate and re-verify EVERYTHING fresh, INSIDE the one
        # transaction that will also perform every mutation below: planning
        # took real time, and nothing checked before it may be trusted
        # here -- the runner could have been revoked, the claim renewed/
        # released/expired, or account access narrowed meanwhile.
        row = _locate_claim_row(
            conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
            expected_statuses=frozenset({"CLAIMED"}),
        )
        if _parse(row["lease_expires_at"]) <= admission_now:
            raise _err(*_CLAIM_NOT_FOUND)  # belt-and-suspenders; expire_stale_assignments above should already catch this
        fresh_job_row = _start_eligibility_checks(conn, principal, row, now=admission_now)
        if _job_snapshot(fresh_job_row) != snapshot:
            # The job itself changed underneath this attempt (should never
            # happen for mode/input_hash/workflow_name; status changing
            # away from QUEUED means a concurrent start/other mutation won
            # the race) -- refused generically, nothing committed.
            raise _err(*_JOB_NOT_STARTABLE)

        if mode == "EXECUTE":
            # Server-authoritative EXECUTE admission (Phase 1C-C): PLANNED
            # -> ACQUIRING_ACCOUNT_LOCK -> IDENTITY_VERIFYING, atomically
            # with the matching CLAIMED -> RUNNING dispatch transition --
            # both legal edges of the EXECUTE mermaid chart
            # (WORKFLOW_STATE_MODEL.md §4), admitted here as a single
            # atomic unit because this pass has no separate signal for
            # "account lock acquired" distinct from "admitted to run" (the
            # dispatch row's own CLAIMED/RUNNING generation+token fencing
            # -- not a separate mcma.persistence.leases.account_leases row
            # -- IS this pass's single-writer guarantee for a remote
            # EXECUTE job; see this increment's own scope notes). The
            # workstation's OWN independent pre-write verification (input_
            # hash/plan_hash/session-readiness) still runs entirely AFTER
            # this, before any write callable is ever invoked -- this
            # transition never claims that verification has happened.
            transition(
                conn, job_id, "ACQUIRING_ACCOUNT_LOCK", in_transaction=True,
                expected_from_statuses=frozenset({"PLANNED"}),
            )
            transition(
                conn, job_id, "IDENTITY_VERIFYING", in_transaction=True,
                expected_from_statuses=frozenset({"ACQUIRING_ACCOUNT_LOCK"}),
            )
            lease_expires = admission_now + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS)
            conn.execute(
                "UPDATE workstation_job_dispatch SET status = 'RUNNING', started_at = ?, lease_expires_at = ?, "
                "last_renewed_at = ? WHERE assignment_id = ? AND status = 'CLAIMED'",
                (_iso(admission_now), _iso(lease_expires), _iso(admission_now), row["assignment_id"]),
            )
            return {
                "status": "RUNNING", "job_status": "IDENTITY_VERIFYING",
                "plan_hash": plan.provenance.plan_hash, "lease_expires_at": _iso(lease_expires),
            }

        transition(conn, job_id, "PLANNING", in_transaction=True, expected_from_statuses=frozenset({"QUEUED"}))
        if plan.needs_review:
            transition(
                conn, job_id, "NEEDS_REVIEW", plan_hash=plan.provenance.plan_hash, in_transaction=True,
                expected_from_statuses=frozenset({"PLANNING"}),
            )
            conn.execute(
                "UPDATE workstation_job_dispatch SET status = 'SUCCEEDED', outcome_code = 'NEEDS_REVIEW_NO_BROWSER', "
                "finished_at = ? WHERE assignment_id = ? AND status = 'CLAIMED'",
                (_iso(admission_now), row["assignment_id"]),
            )
            return {"status": "NEEDS_REVIEW", "job_status": "NEEDS_REVIEW"}
        transition(
            conn, job_id, "PLANNED", plan_hash=plan.provenance.plan_hash, in_transaction=True,
            expected_from_statuses=frozenset({"PLANNING"}),
        )
        transition(
            conn, job_id, "READ_ONLY_IDENTITY_CHECK", in_transaction=True,
            expected_from_statuses=frozenset({"PLANNED"}),
        )
        lease_expires = admission_now + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS)
        conn.execute(
            "UPDATE workstation_job_dispatch SET status = 'RUNNING', started_at = ?, lease_expires_at = ?, "
            "last_renewed_at = ? WHERE assignment_id = ? AND status = 'CLAIMED'",
            (_iso(admission_now), _iso(lease_expires), _iso(admission_now), row["assignment_id"]),
        )
    return {
        "status": "RUNNING", "job_status": "READ_ONLY_IDENTITY_CHECK",
        "plan_hash": plan.provenance.plan_hash, "lease_expires_at": _iso(lease_expires),
    }


def _idempotent_finish_response(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object,
    result: str, now: datetime,
) -> Optional[dict]:
    """A duplicate finish() carrying the EXACT same token/generation/result
    as an already-recorded terminal outcome is answered identically (a
    network retry must never need special client-side handling); anything
    else -- a different result, a different generation, a row that never
    existed, or one still active -- returns None, so the caller raises the
    SAME generic refusal every other stale/wrong claim gets (conflicting or
    stale results fail generically, never distinguishably).

    Phase 1C-C: disambiguated by the row's OWN job's mode (never by the
    result string alone) -- FINISH_RESULTS and EXECUTE_FINISH_RESULTS
    deliberately share one member (RUNNER_CANCELLED) with DIFFERENT
    resulting job_status per mode, so guessing the mapping from the result
    string alone would silently answer an EXECUTE retry with a DRY_RUN
    mapping (or vice versa) whenever they collide."""
    if not _valid_claim_token(claim_token) or not _valid_generation(generation):
        return None
    computed = digest_token(claim_token)
    row = conn.execute("SELECT * FROM workstation_job_dispatch WHERE claim_token_digest = ?", (computed,)).fetchone()
    if (
        row is None
        or not _digests_equal(row["claim_token_digest"], computed)
        or row["job_id"] != job_id
        or row["runner_id"] != principal.runner_id
        or row["generation"] != generation
        or row["status"] not in ("SUCCEEDED", "FAILED")
        or row["outcome_code"] != result
    ):
        return None
    job_row = conn.execute("SELECT mode FROM automation_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
    mode = job_row["mode"] if job_row is not None else None
    if mode == "EXECUTE" and result in EXECUTE_FINISH_RESULTS:
        new_status, _reason_code = _EXECUTE_FINISH_RESULT_TO_JOB_STATUS[result]
    elif result in FINISH_RESULTS:
        new_status, _reason_code = _FINISH_RESULT_TO_JOB_STATUS[result]
    else:
        return None
    return {"status": row["status"], "job_status": new_status, "server_time": _iso(now)}


def _finish_execute_transitions(conn, job_id: str, result: str, *, now: datetime) -> tuple:
    """Chains the fixed, legal automation_jobs transitions from
    IDENTITY_VERIFYING (start_job's own EXECUTE admission status) to the
    terminal status _EXECUTE_FINISH_RESULT_TO_JOB_STATUS[result] names,
    entirely inside the caller's already-open transaction (in_
    transaction=True throughout -- see transition()'s own docstring on why
    that requires an already-active BEGIN IMMEDIATE, which finish_job's
    caller holds). Every hop is fenced with expected_from_statuses, so a
    job that is not truthfully exactly where this chain expects raises
    JobPreconditionMismatch immediately -- never silently skipped.

    Two families, matching the EXECUTE mermaid chart's own legal edges
    (WORKFLOW_STATE_MODEL.md §4):
      * IDENTITY_FAILED (with SESSION_NOT_READY/INPUT_OR_PLAN_MISMATCH as
        its own distinct reason_code) is ONE hop, IDENTITY_VERIFYING ->
        IDENTITY_FAILED -- the workstation's own executor never calls the
        injected write callable until every pre-write check has already
        passed, so none of these three outcomes can mean mutation began.
      * READY_FOR_HUMAN_REVIEW/WRITE_ABORTED (RUNNER_CANCELLED/
        INTERNAL_EXECUTION_ERROR both land on WRITE_ABORTED, as their own
        distinct reason_code) all mean the write callable WAS invoked --
        mutation MAY have begun -- so these chain through IDENTITY_VERIFIED
        -> WRITING first. Nothing in this function can ever land on
        NEEDS_REVIEW, PLANNED, or QUEUED: once IDENTITY_VERIFYING has been
        reached there is no legal edge back to any of those three, exactly
        the fail-closed guarantee this increment requires.

    Returns (final_job_status, terminal_dispatch_status)."""
    target_status, reason_code = _EXECUTE_FINISH_RESULT_TO_JOB_STATUS[result]
    stamp = _iso(now)
    if target_status == "IDENTITY_FAILED":
        transition(
            conn, job_id, "IDENTITY_FAILED", reason_code=reason_code, finished_at=stamp, in_transaction=True,
            expected_from_statuses=frozenset({"IDENTITY_VERIFYING"}),
        )
        return "IDENTITY_FAILED", "FAILED"
    transition(
        conn, job_id, "IDENTITY_VERIFIED", in_transaction=True,
        expected_from_statuses=frozenset({"IDENTITY_VERIFYING"}),
    )
    transition(conn, job_id, "WRITING", in_transaction=True, expected_from_statuses=frozenset({"IDENTITY_VERIFIED"}))
    if target_status == "READY_FOR_HUMAN_REVIEW":
        transition(conn, job_id, "VERIFYING", in_transaction=True, expected_from_statuses=frozenset({"WRITING"}))
        # F.8 (mcma.execution.jobs' own convention): finished_at is NOT set
        # here -- READY_FOR_HUMAN_REVIEW is not a terminal outcome, the
        # browser stays open for human review.
        transition(
            conn, job_id, "READY_FOR_HUMAN_REVIEW", in_transaction=True,
            expected_from_statuses=frozenset({"VERIFYING"}),
        )
        return "READY_FOR_HUMAN_REVIEW", "SUCCEEDED"
    transition(
        conn, job_id, "WRITE_ABORTED", reason_code=reason_code, finished_at=stamp, in_transaction=True,
        expected_from_statuses=frozenset({"WRITING"}),
    )
    return "WRITE_ABORTED", "FAILED"


def finish_job(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object,
    result: object, now: Optional[datetime] = None,
    execute_dispatch_enabled: bool = EXECUTE_DISPATCH_ENABLED,
) -> dict:
    """RUNNING -> a terminal SUCCEEDED/FAILED dispatch outcome, atomic with
    the corresponding automation_jobs transition -- ONE write_transaction
    commits both, via transition(..., in_transaction=True), so a crash
    between the two can never leave a terminal job with an active dispatch
    row, or a terminal dispatch row with a job still mid-check.

    Phase 1C-C: the SAME endpoint/function now serves BOTH job kinds --
    the client never chooses which enum applies; this function determines
    it from the claimed assignment's OWN automation_jobs.mode, looked up
    fresh inside the transaction, exactly like every other fact here.
    DRY_RUN uses `result` in FINISH_RESULTS -> _FINISH_RESULT_TO_JOB_STATUS
    (READ_ONLY_IDENTITY_CHECK -> DRY_RUN_VERIFIED/IDENTITY_FAILED, one
    hop). EXECUTE uses `result` in EXECUTE_FINISH_RESULTS ->
    _finish_execute_transitions (IDENTITY_VERIFYING -> ... -> READY_FOR_
    HUMAN_REVIEW/IDENTITY_FAILED/WRITE_ABORTED). Neither table is ever
    influenced by anything else in the request; `execute_dispatch_enabled`
    follows the same never-a-hidden-bypass discipline as claim_job's/
    start_job's own parameter of the same name.

    Release-blocker correction: before accepting a RUNNING result, this
    reuses the SAME _start_eligibility_checks() start_job() itself uses --
    runner ACTIVE/online, the job still belonging to this runner's exact
    employee, that employee still having access to the job's EXACT
    account (not merely at-least-one-MCMA-account -- the same Oujda-
    removed-while-Nador-remains gap renew_job's own account recheck
    already closes), and that exact runner_account_capabilities row still
    being READY. Every one of those failures raises the SAME generic
    CLAIM_NOT_FOUND/401 _locate_claim_row itself uses -- a caller can
    never distinguish "wrong token" from "your account access changed"
    from "this job is no longer yours".

    Idempotent ONLY for the exact same token/generation/result as an
    already-recorded terminal outcome (see _idempotent_finish_response);
    a conflicting or stale attempt fails with the same generic
    CLAIM_NOT_FOUND every other wrong/stale claim gets."""
    now = now or utcnow()
    if not isinstance(result, str) or (result not in FINISH_RESULTS and result not in EXECUTE_FINISH_RESULTS):
        raise _err("BAD_REQUEST", "Résultat invalide.")
    expire_stale_assignments(conn, now=now)  # own transaction -- see its own docstring

    with write_transaction(conn):
        try:
            row = _locate_claim_row(
                conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
                expected_statuses=frozenset({"RUNNING"}),
            )
        except UserInputError:
            idempotent = _idempotent_finish_response(
                conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
                result=result, now=now,
            )
            if idempotent is not None:
                return idempotent
            raise
        job_row = _start_eligibility_checks(conn, principal, row, now=now)
        mode = job_row["mode"]
        try:
            if mode == "EXECUTE" and execute_dispatch_enabled:
                if result not in EXECUTE_FINISH_RESULTS:
                    raise _err("BAD_REQUEST", "Résultat invalide.")
                new_status, terminal = _finish_execute_transitions(conn, job_id, result, now=now)
            else:
                if result not in FINISH_RESULTS:
                    raise _err("BAD_REQUEST", "Résultat invalide.")
                new_status, reason_code = _FINISH_RESULT_TO_JOB_STATUS[result]
                transition(
                    conn, job_id, new_status, reason_code=reason_code, finished_at=_iso(now), in_transaction=True,
                    expected_from_statuses=frozenset({"READ_ONLY_IDENTITY_CHECK"}),
                )
                terminal = "SUCCEEDED" if result == "IDENTITY_MATCHED" else "FAILED"
        except JobPreconditionMismatch:
            raise _err(*_CLAIM_NOT_FOUND) from None
        conn.execute(
            "UPDATE workstation_job_dispatch SET status = ?, outcome_code = ?, finished_at = ? "
            "WHERE assignment_id = ? AND status = 'RUNNING'",
            (terminal, result, _iso(now), row["assignment_id"]),
        )
    return {"status": terminal, "job_status": new_status, "server_time": _iso(now)}


# --------------------------------------------------------------------- #
# EXECUTE human-review handoff (Phase 1C-C, item 7)
# --------------------------------------------------------------------- #


def report_execute_review_browser_closed(
    conn, principal: RunnerPrincipal, *, job_id: str, claim_token: object, generation: object,
    now: Optional[datetime] = None,
) -> dict:
    """The narrow, authenticated "review browser closed" machine event.
    Fenced by the SAME claim_token+generation every other lifecycle call in
    this module uses -- only the exact assignment that itself finished this
    EXECUTE job with outcome_code=READY_FOR_HUMAN_REVIEW may ever report
    this; a stale, wrong, or someone-else's token/generation gets the SAME
    generic CLAIM_NOT_FOUND every other refusal in this module gives.

    This function's ONLY effect is automation_jobs' READY_FOR_HUMAN_REVIEW
    -> AWAITING_HUMAN_CONFIRMATION transition, via the EXISTING
    mcma.execution.jobs.transition_on_browser_closed -- never a new,
    ad-hoc transition, and never anything the workstation's own request
    could otherwise choose (the request carries only claim_token/
    generation, no status field at all). It never marks
    HUMAN_CONFIRMED_COMPLETE (only the existing employee-authenticated
    POST /jobs/{job_id}/review-completed can do that) and never mutates
    workstation_job_dispatch -- the assignment is already terminal
    (SUCCEEDED) by the time this can ever legally be called.

    Idempotent: called again (or called after an employee has already
    confirmed/reported a problem through the existing review-completion
    API) is answered with the job's current status rather than raising --
    transition_on_browser_closed() itself is only ever invoked from the
    one status it is legal from."""
    now = now or utcnow()
    row = _locate_claim_row(
        conn, principal, job_id=job_id, claim_token=claim_token, generation=generation,
        expected_statuses=frozenset({"SUCCEEDED"}),
    )
    if row["outcome_code"] != "READY_FOR_HUMAN_REVIEW":
        raise _err(*_CLAIM_NOT_FOUND)
    job_row = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
    if job_row is not None and job_row["status"] in (
        "AWAITING_HUMAN_CONFIRMATION", "HUMAN_CONFIRMED_COMPLETE",
        # Correction (Phase 1C-C, finding 5): an employee may report a
        # problem (mcma.execution.jobs.report_review_problem) while the
        # job is STILL READY_FOR_HUMAN_REVIEW -- that already-legal,
        # already-authenticated path moves it straight to INTERRUPTED_
        # NEEDS_HUMAN_REVIEW without ever passing through AWAITING_HUMAN_
        # CONFIRMATION. The browser then closes AFTER that has happened.
        # This is read-only recognition of a state the EMPLOYEE/recovery
        # path already produced -- this function never creates INTERRUPTED_
        # NEEDS_HUMAN_REVIEW itself (see transition_on_browser_closed,
        # which this function calls only when the job is NOT already one
        # of these three) -- so answering idempotently here can never be
        # confused with a NEW server-detected interruption.
        "INTERRUPTED_NEEDS_HUMAN_REVIEW",
    ):
        return {"status": job_row["status"], "server_time": _iso(now)}  # idempotent -- already advanced
    try:
        new_status = transition_on_browser_closed(conn, job_id)
    except JobAuthorizationError:
        raise _err(*_CLAIM_NOT_FOUND) from None
    return {"status": new_status, "server_time": _iso(now)}
