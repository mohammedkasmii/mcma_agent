"""mcma.app.workstation_runner.dry_run_executor -- the narrow workstation
DRY_RUN execution adapter (Phase 1C-B, item E).

Lightweight-package rule (tests/app/workstation_runner/
test_import_isolation.py): this module imports NO Playwright, NO
mcma.portal, NO SQLite/FastAPI, and NO mcma.execution/mcma.persistence.
The actual read-only portal operation
(mcma.portal.workstation_sessions.perform_dry_run_identity_check) is
accepted as a single injected async callable -- this module never
constructs, and never even knows the concrete type of, a ReadCapability, a
Playwright Browser, or any portal exception. mcma.planning and
mcma.mapping ARE imported directly: neither is on that forbidden list, and
both are exactly the same pure, deterministic modules
mcma.execution.runner (the central composition's real job runner) already
uses for the identical purpose.

Everything server-verifiable is re-verified HERE, on the workstation, one
more time, before a browser is ever launched:
  * input_hash is recomputed from the RECEIVED typed_input (the same
    canonical-JSON SHA-256 hashing mcma.execution.inputs.
    compute_content_hash uses -- reimplemented as one line rather than
    imported, since mcma.execution is off-limits to this package) and
    compared against the claim envelope's own input_hash;
  * typed_input is parsed through the EXISTING Wexia parser
    (mcma.mapping.wexia.parse_wexia);
  * the workflow is resolved through the EXISTING workflow registry
    (mcma.planning.registry), never a caller-supplied builder;
  * the ProposedPlan is rebuilt LOCALLY, and its plan_hash is compared
    against the server-authorized `expected_plan_hash` (start_job's own
    response) -- any mismatch fails closed, no browser is ever launched.

Only after all of that succeeds is the account's saved session loaded (and
its own presence checked -- session-state/READY-ness itself is the
caller's job, checked before this function is ever invoked) and the
injected read-only portal operation invoked. Every expected failure mode
converts to one of the fixed FINISH_RESULTS values (never a raised
exception up to the caller, except asyncio.CancelledError, which always
propagates on every exit path).

`check_identity_read_only`'s signature carries only primitives and
mcma.planning.plan.ExpectedIdentity -- never a mcma.portal.identity.
ExpectedIdentity or a mcma.portal.capabilities.SearchIdentifiers. The
composition root (mcma.app.workstation_runner.app, the ONE module in this
package allowed to import mcma.portal) is responsible for wrapping the
real mcma.portal.workstation_sessions.perform_dry_run_identity_check
behind a closure matching this exact signature -- mirroring
mcma.execution.runner's own _to_portal_expected_identity/
_search_identifiers_for conversion, just performed in app.py instead."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Awaitable, Callable, Optional, Protocol

from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import ExpectedIdentity, ProposedPlan
from mcma.planning.registry import WorkflowRegistry

FINISH_RESULTS = frozenset(
    {"IDENTITY_MATCHED", "IDENTITY_NOT_MATCHED", "SESSION_UNAVAILABLE", "PORTAL_READ_FAILED", "RUNNER_CANCELLED"}
)


class SessionStoreProtocol(Protocol):
    """Structural -- satisfied by
    mcma.app.workstation_runner.session_store.WorkstationSessionStore
    without this module importing it (it needs none of that module's DPAPI
    internals, only this one read)."""

    def load(self, account_id: str) -> Optional[dict]: ...


class ClaimedJobProtocol(Protocol):
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


# (account_id, storage_state, expected_identity, matricule) -> matched.
# See the module docstring for exactly why this signature -- never a
# mcma.portal type -- and who is responsible for wrapping the real portal
# function behind it.
CheckIdentityReadOnly = Callable[[str, dict, ExpectedIdentity, str], Awaitable[bool]]


def _recompute_input_hash(typed_input: dict) -> str:
    """The same canonical-JSON SHA-256 hashing
    mcma.execution.inputs.compute_content_hash uses on the server, over
    the SAME canonical encoding mcma.execution.jobs' own enqueue path
    hashes typed_input with (json.dumps(..., sort_keys=True)) -- kept as
    one inlined line rather than an import: mcma.execution is off-limits
    to this lightweight package."""
    payload = json.dumps(typed_input, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _matricule_for(plan: ProposedPlan) -> str:
    return plan.expected_identity.registration.raw


async def run_dry_run_check(
    claimed_job: ClaimedJobProtocol,
    *,
    expected_plan_hash: str,
    session_store: SessionStoreProtocol,
    workflow_registry: WorkflowRegistry,
    check_identity_read_only: CheckIdentityReadOnly,
) -> str:
    """Returns one of FINISH_RESULTS -- the exact value the worker reports
    to POST /runner/jobs/{job_id}/finish. Never raises, except
    asyncio.CancelledError (a BaseException, never caught here as an
    ordinary Exception, and propagated on every exit path -- including
    from inside the injected portal call). Never launches a browser (never
    even calls `check_identity_read_only`) unless every local
    verification step above it has already succeeded."""
    try:
        if _recompute_input_hash(claimed_job.typed_input) != claimed_job.input_hash:
            return "PORTAL_READ_FAILED"
        typed_input = parse_wexia(claimed_job.typed_input)
        plan = workflow_registry.get(claimed_job.workflow_name)(typed_input)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Malformed/tampered typed_input, an unknown workflow_name, or a
        # PlanBuildError -- a verification failure, never a guess at what
        # was intended. No browser is ever launched for this outcome.
        return "PORTAL_READ_FAILED"

    if plan.provenance.plan_hash != expected_plan_hash:
        # The server's own authorized plan_hash (from start_job()) does
        # not match what this workstation independently rebuilt from the
        # SAME typed_input -- fails closed before any browser launch.
        return "PORTAL_READ_FAILED"

    try:
        storage_state = session_store.load(claimed_job.account_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        return "SESSION_UNAVAILABLE"
    if storage_state is None:
        # Missing or corrupt/undecryptable (session_store.load() already
        # treats both identically) -- never a guess, never a browser
        # launch with no session to apply.
        return "SESSION_UNAVAILABLE"

    try:
        matched = await check_identity_read_only(
            claimed_job.account_id, storage_state, plan.expected_identity, _matricule_for(plan),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Every operational failure from the injected portal call
        # (session could not be applied, the search/open/observe read
        # itself failed) converges here -- this module never inspects the
        # exception's type or text (it does not even import the portal
        # exception type that failure might actually be).
        return "PORTAL_READ_FAILED"
    return "IDENTITY_MATCHED" if matched else "IDENTITY_NOT_MATCHED"
