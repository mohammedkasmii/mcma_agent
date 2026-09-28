"""mcma.app.workstation_runner.execute_executor -- the narrow workstation
EXECUTE pre-write-verification adapter (Phase 1C-C, item 4).

Lightweight-package rule (tests/app/workstation_runner/
test_import_isolation.py): this module imports NO Playwright, NO
mcma.portal, NO SQLite/FastAPI, and NO mcma.execution/mcma.persistence.
Exactly mirrors mcma.app.workstation_runner.dry_run_executor's own
discipline: mcma.planning and mcma.mapping ARE imported directly (neither
is on the forbidden list, and both are the same pure, deterministic
modules the server itself uses for the identical purpose). The actual
write operation is accepted as a single injected async callable -- this
module never constructs, and never even knows the concrete type of, a
VerifiedMissionWriter, a Playwright Browser, or any portal exception.

Do not import or call the real portal writer here or from anywhere this
module can reach: this pass injects only fakes (tests) and a fail-closed
placeholder (the composition root, mcma.app.workstation_runner.app --
until a Pass 2 increment wires the reviewed, post-G5 VerifiedMissionWriter
behind the SAME PerformExecuteWrite shape).

Everything server-verifiable is re-verified HERE, on the workstation, one
more time, before the injected write callable is ever invoked -- never
trusting that start_job()'s own server-side admission alone is enough:
  * the claimed account is refused outright unless it is one of the two
    canonical MCMA runner accounts (mirrors
    mcma.app.workstation_runner.protocol.RUNNER_ACCOUNT_IDS) -- MAMDA and
    any other account structurally cannot reach the write callable, even
    if every other check somehow passed;
  * input_hash is recomputed from the RECEIVED typed_input and compared
    against the claim envelope's own input_hash (same reasoning and same
    canonical-JSON SHA-256 hashing as dry_run_executor's own
    _recompute_input_hash);
  * typed_input is parsed through the EXISTING Wexia parser
    (mcma.mapping.wexia.parse_wexia);
  * the workflow is resolved through the EXISTING workflow registry
    (mcma.planning.registry), never a caller-supplied builder;
  * the ProposedPlan is rebuilt LOCALLY, and its plan_hash is compared
    against the server-authorized `expected_plan_hash` (start_job's own
    response) -- any mismatch fails closed, no write callable is ever
    invoked.

Only after ALL of that succeeds is the account's saved session loaded (its
own presence checked -- session-state/READY-ness itself is the caller's
job, checked before this function is ever invoked) and the injected write
callable invoked. Every expected failure mode converts to one of the fixed
EXECUTE_FINISH_RESULTS values (never a raised exception up to the caller,
except asyncio.CancelledError, which always propagates on every exit
path)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Awaitable, Callable, Optional, Protocol

from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import ProposedPlan
from mcma.planning.registry import WorkflowRegistry

# mirrors mcma.app.workstation_runner.protocol.RUNNER_ACCOUNT_IDS -- kept a
# separate literal (never imported) for the same reason dry_run_executor.py
# never imports mcma.app.runners.registry: this package stays isolated from
# server code (tests/app/workstation_runner/test_protocol_drift.py checks
# it byte-for-byte identical).
_MCMA_RUNNER_ACCOUNT_IDS = ("acct-mcma-oujda", "acct-mcma-nador")

EXECUTE_FINISH_RESULTS = frozenset(
    {
        "READY_FOR_HUMAN_REVIEW", "IDENTITY_FAILED", "WRITE_ABORTED", "RUNNER_CANCELLED",
        "SESSION_NOT_READY", "INPUT_OR_PLAN_MISMATCH", "INTERNAL_EXECUTION_ERROR", "LEASE_LOST",
    }
)

# Correction (Phase 1C-C, finding 6): the NARROW subset of EXECUTE_FINISH_
# RESULTS the injected `perform_execute_write` callable is itself allowed
# to return -- genuine outcomes of ITS OWN write attempt only. Every other
# member of EXECUTE_FINISH_RESULTS is owned by an OUTER layer this module
# (or the worker above it) is exclusively responsible for:
#   * INPUT_OR_PLAN_MISMATCH/SESSION_NOT_READY -- this module's own
#     pre-write verification, above, which never even reaches the write
#     callable when either applies;
#   * RUNNER_CANCELLED/LEASE_LOST -- mcma.app.workstation_runner.job_
#     worker's own cancellation bookkeeping (an operator shutdown or a
#     lost renewal), which the write callable has no way to observe or
#     honestly report on its own.
# A future real writer that tried to claim "the runner cancelled me" or
# "the input didn't match" would be lying about WHY it stopped, never a
# truthful report of its own write outcome -- so any such value, any
# unrecognized string, or any non-string value at all is treated
# identically: INTERNAL_EXECUTION_ERROR, exactly like an exception.
WRITER_ALLOWED_RESULTS = frozenset({"READY_FOR_HUMAN_REVIEW", "IDENTITY_FAILED", "WRITE_ABORTED"})


class SessionStoreProtocol(Protocol):
    """Structural -- satisfied by
    mcma.app.workstation_runner.session_store.WorkstationSessionStore
    without this module importing it (it needs none of that module's DPAPI
    internals, only this one read)."""

    def load(self, account_id: str) -> Optional[dict]: ...


class ClaimedExecuteJobProtocol(Protocol):
    """Structural -- satisfied by
    mcma.app.workstation_runner.http_client.ClaimedJob without a hard
    import dependency on that dataclass's exact identity (both live in
    this same lightweight package, so importing it directly would also be
    safe; this keeps the two modules decoupled regardless)."""

    job_id: str
    account_id: str
    workflow_name: str
    input_hash: str
    typed_input: dict


# (account_id, storage_state, plan) -> one of EXECUTE_FINISH_RESULTS'
# post-write-attempt members (READY_FOR_HUMAN_REVIEW, WRITE_ABORTED, or
# INTERNAL_EXECUTION_ERROR for any exception -- see run_execute_check's own
# exception handling, which never lets a raw exception escape THIS
# module). This pass injects only fakes/a fail-closed placeholder; a
# future increment's composition root wraps the reviewed
# VerifiedMissionWriter behind this exact shape.
PerformExecuteWrite = Callable[[str, dict, ProposedPlan], Awaitable[str]]


def _recompute_input_hash(typed_input: dict) -> str:
    """The same canonical-JSON SHA-256 hashing
    mcma.execution.inputs.compute_content_hash uses on the server -- kept
    as one inlined line rather than an import: mcma.execution is off-limits
    to this lightweight package. Identical to dry_run_executor's own
    _recompute_input_hash (duplicated rather than imported, for the same
    package-isolation reason as everything else here)."""
    payload = json.dumps(typed_input, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def run_execute_check(
    claimed_job: ClaimedExecuteJobProtocol,
    *,
    expected_plan_hash: str,
    session_store: SessionStoreProtocol,
    workflow_registry: WorkflowRegistry,
    perform_execute_write: PerformExecuteWrite,
) -> str:
    """Returns one of EXECUTE_FINISH_RESULTS -- the exact value the worker
    reports to POST /runner/jobs/{job_id}/finish. Never raises, except
    asyncio.CancelledError (a BaseException, never caught here as an
    ordinary Exception, and propagated on every exit path -- including
    from inside the injected write callable). Never invokes
    `perform_execute_write` (never begins a write) unless every local
    verification step above it has already succeeded."""
    try:
        if claimed_job.account_id not in _MCMA_RUNNER_ACCOUNT_IDS:
            # Structural refusal, defense-in-depth: the server's own claim/
            # start admission already never dispatches a non-MCMA account
            # (MAMDA is excluded server-side), but this module never
            # trusts that alone -- see the module docstring.
            return "INPUT_OR_PLAN_MISMATCH"
        if _recompute_input_hash(claimed_job.typed_input) != claimed_job.input_hash:
            return "INPUT_OR_PLAN_MISMATCH"
        typed_input = parse_wexia(claimed_job.typed_input)
        plan = workflow_registry.get(claimed_job.workflow_name)(typed_input)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Malformed/tampered typed_input, an unknown workflow_name, or a
        # PlanBuildError -- a verification failure, never a guess at what
        # was intended. No write callable is ever invoked for this outcome.
        return "INPUT_OR_PLAN_MISMATCH"

    if plan.provenance.plan_hash != expected_plan_hash:
        # The server's own authorized plan_hash (from start_job()) does
        # not match what this workstation independently rebuilt from the
        # SAME typed_input -- fails closed before the write callable is
        # ever invoked.
        return "INPUT_OR_PLAN_MISMATCH"

    try:
        storage_state = session_store.load(claimed_job.account_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        return "SESSION_NOT_READY"
    if storage_state is None:
        # Missing or corrupt/undecryptable (session_store.load() already
        # treats both identically) -- never a guess, never a write attempt
        # with no session to apply.
        return "SESSION_NOT_READY"

    try:
        written = await perform_execute_write(claimed_job.account_id, storage_state, plan)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Any exception escaping the injected write callable -- this
        # module never inspects its type or text (it does not even import
        # the portal exception type that failure might actually be) --
        # converges here, NEVER back to a pre-write outcome: the callable
        # may already have begun mutating the portal.
        return "INTERNAL_EXECUTION_ERROR"

    # Correction (Phase 1C-C, finding 6): the injected callable's return
    # value is NEVER trusted verbatim -- only a narrow, fixed subset of
    # outcomes it could truthfully own is accepted (see WRITER_ALLOWED_
    # RESULTS's own docstring). Any other string (including a worker-owned
    # value like RUNNER_CANCELLED/LEASE_LOST/INPUT_OR_PLAN_MISMATCH the
    # callable has no business manufacturing), any non-string, or None
    # converges on the SAME fail-closed outcome an exception would --
    # mutation may already have begun, so this is never a pre-write
    # outcome either.
    if not isinstance(written, str) or written not in WRITER_ALLOWED_RESULTS:
        return "INTERNAL_EXECUTION_ERROR"
    return written
