"""mcma.app.workstation_runner.execute_executor -- Phase 1C-C, item 4.
Unit-level: the injected `perform_execute_write` is a plain async fake,
never a real Playwright/portal writer (see module docstring on the
lightweight-package import isolation this module must keep). No live MCMA
website is required anywhere in this file, and this file never imports or
calls mcma.portal.writer.VerifiedMissionWriter."""

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from mcma.app.workstation_runner.execute_executor import run_execute_check
from mcma.mapping.wexia import parse_wexia
from mcma.planning.registry import default_registry

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"
MAMDA_OUJDA = "acct-mamda-oujda"

VALID_WORKFLOW_NAME = "mission_normal"
VALID_TYPED_INPUT = {
    "dossier": {
        "id_sinistre": "699001", "mission_type": "normal",
        "incident_description": "MODE NORMAL", "is_reform": False,
    },
    "vehicule": {"license_plate": "77001-C-3"},
    "chiffrages": [{
        "id": "CH-NORMAL-1", "status": "approved", "is_final": True, "scenario_type": "repair",
        "total_cost": 10, "tax_amount": 2,
        "lignes_pieces": [{"item_type": "part", "item_name": "pare-choc avant", "part_type": "original", "subtotal": 10}],
    }],
}

REGISTRY = default_registry()
_VALID_PLAN = REGISTRY.get(VALID_WORKFLOW_NAME)(parse_wexia(VALID_TYPED_INPUT))
VALID_PLAN_HASH = _VALID_PLAN.provenance.plan_hash


def _input_hash(typed_input: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(typed_input, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FakeClaimedJob:
    job_id: str = "job-1"
    account_id: str = OUJDA
    workflow_name: str = VALID_WORKFLOW_NAME
    typed_input: dict = field(default_factory=lambda: dict(VALID_TYPED_INPUT))
    input_hash: str = field(default_factory=lambda: _input_hash(VALID_TYPED_INPUT))


class FakeSessionStore:
    def __init__(self, sessions: dict | None = None, *, raises: Exception | None = None):
        self._sessions = sessions or {}
        self._raises = raises
        self.load_calls: list = []

    def load(self, account_id: str):
        self.load_calls.append(account_id)
        if self._raises is not None:
            raise self._raises
        return self._sessions.get(account_id)


def _never_called(*args, **kwargs):
    raise AssertionError("perform_execute_write must never be called")


async def _ready_for_review(*args, **kwargs) -> str:
    return "READY_FOR_HUMAN_REVIEW"


async def _write_aborted(*args, **kwargs) -> str:
    return "WRITE_ABORTED"


def run_async(coro):
    return asyncio.run(coro)


class FakePermit:
    """A bare stand-in for mcma.app.workstation_runner.execution_permit.
    ExecutionPermit -- this module never calls a method on it (see
    test_permit_and_callbacks_are_threaded_through_opaquely), only threads
    it through to the write callable, so a real ExecutionPermit is not
    required for these unit tests."""

    def __init__(self, account_id: str = OUJDA) -> None:
        self.account_id = account_id


async def _never_ready_for_review():
    raise AssertionError("on_ready_for_review must never be called when the write callable never calls it")


def _never_phase(phase: str) -> None:
    raise AssertionError("on_phase must never be called when the write callable never calls it")


def _run(
    job=None,
    *,
    expected_plan_hash=VALID_PLAN_HASH,
    session_store=None,
    write=_ready_for_review,
    permit=None,
    on_ready_for_review=_never_ready_for_review,
    on_phase=_never_phase,
):
    return run_async(run_execute_check(
        job or FakeClaimedJob(),
        expected_plan_hash=expected_plan_hash,
        session_store=session_store or FakeSessionStore({OUJDA: {"cookies": [], "origins": []}}),
        workflow_registry=REGISTRY,
        perform_execute_write=write,
        permit=permit if permit is not None else FakePermit(),
        on_ready_for_review=on_ready_for_review,
        on_phase=on_phase,
    ))


def test_ready_for_human_review_when_the_write_callable_succeeds():
    assert _run(write=_ready_for_review) == "READY_FOR_HUMAN_REVIEW"


def test_write_aborted_is_passed_through_from_the_write_callable():
    assert _run(write=_write_aborted) == "WRITE_ABORTED"


def test_plan_hash_mismatch_never_invokes_the_write_callable():
    result = _run(expected_plan_hash="tampered-" + VALID_PLAN_HASH, write=_never_called)
    assert result == "INPUT_OR_PLAN_MISMATCH"


def test_input_hash_mismatch_never_invokes_the_write_callable():
    job = FakeClaimedJob(input_hash="tampered-hash")
    assert _run(job, write=_never_called) == "INPUT_OR_PLAN_MISMATCH"


def test_tampered_typed_input_never_invokes_the_write_callable():
    """input_hash is recomputed from the RECEIVED typed_input -- if both
    were tampered consistently, plan-building itself still fails closed
    (an unknown workflow / malformed payload), never silently accepted."""
    tampered = {**VALID_TYPED_INPUT, "dossier": {**VALID_TYPED_INPUT["dossier"], "is_reform": True}}
    job = FakeClaimedJob(typed_input=tampered, input_hash=_input_hash(tampered))
    assert _run(job, write=_never_called) == "INPUT_OR_PLAN_MISMATCH"


def test_unknown_workflow_name_never_invokes_the_write_callable():
    job = FakeClaimedJob(workflow_name="not_a_real_workflow")
    assert _run(job, write=_never_called) == "INPUT_OR_PLAN_MISMATCH"


def test_missing_session_never_invokes_the_write_callable():
    store = FakeSessionStore({})  # no session saved for any account
    assert _run(session_store=store, write=_never_called) == "SESSION_NOT_READY"


def test_unreadable_or_corrupt_session_never_invokes_the_write_callable():
    store = FakeSessionStore(raises=RuntimeError("decrypt failed"))
    assert _run(session_store=store, write=_never_called) == "SESSION_NOT_READY"


def test_mamda_account_is_structurally_refused_before_any_session_load_or_write():
    """Item 4: this module refuses a non-MCMA account itself, defense in
    depth, before ever touching the session store or the write callable --
    never relying solely on the server's own dispatch never routing MAMDA
    here in the first place."""
    store = FakeSessionStore({MAMDA_OUJDA: {"cookies": [], "origins": []}})
    job = FakeClaimedJob(account_id=MAMDA_OUJDA)
    assert _run(job, session_store=store, write=_never_called) == "INPUT_OR_PLAN_MISMATCH"
    assert store.load_calls == []


def test_oujda_and_nador_are_both_supported():
    for account_id in (OUJDA, NADOR):
        job = FakeClaimedJob(account_id=account_id)
        store = FakeSessionStore({account_id: {"cookies": [], "origins": []}})
        assert _run(job, session_store=store, write=_ready_for_review) == "READY_FOR_HUMAN_REVIEW"


def test_an_exception_from_the_write_callable_is_contained_as_internal_execution_error():
    """Once the write callable has been invoked, mutation may have begun --
    any exception from it (this module never inspects its type or text)
    converges on INTERNAL_EXECUTION_ERROR, never a pre-write outcome like
    INPUT_OR_PLAN_MISMATCH/SESSION_NOT_READY."""
    async def _boom(*args, **kwargs):
        raise RuntimeError("portal write crashed")

    assert _run(write=_boom) == "INTERNAL_EXECUTION_ERROR"


def test_cancellation_propagates_from_inside_the_write_callable():
    async def _cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _run(write=_cancel)


def test_the_write_callable_receives_the_real_rebuilt_plan_never_a_portal_type():
    """The injected callable's signature carries (account_id,
    storage_state, plan, permit, on_ready_for_review, on_phase) -- `plan`
    is never a mcma.portal type (this module must never import
    mcma.portal at all, and never construct or accept a
    VerifiedMissionWriter)."""
    from mcma.planning.plan import ProposedPlan

    seen = {}

    async def _capture(account_id, storage_state, plan, permit, on_ready_for_review, on_phase) -> str:
        seen["account_id"] = account_id
        seen["storage_state"] = storage_state
        seen["plan"] = plan
        return "READY_FOR_HUMAN_REVIEW"

    _run(write=_capture)
    assert seen["account_id"] == OUJDA
    assert isinstance(seen["plan"], ProposedPlan)
    assert seen["plan"].provenance.plan_hash == VALID_PLAN_HASH


def test_permit_and_callbacks_are_threaded_through_to_the_write_callable_unchanged():
    """Phase 1C-C Pass 2A: `permit`/`on_ready_for_review`/`on_phase` reach
    the write callable exactly as given -- this module never calls a
    method on the permit and never calls the callbacks itself (that is
    entirely the write callable's own responsibility)."""
    permit = FakePermit(account_id=OUJDA)

    async def _on_ready() -> None:
        return None

    def _on_phase(phase: str) -> None:
        return None

    seen = {}

    async def _capture(account_id, storage_state, plan, seen_permit, seen_on_ready, seen_on_phase) -> str:
        seen["permit"] = seen_permit
        seen["on_ready_for_review"] = seen_on_ready
        seen["on_phase"] = seen_on_phase
        return "READY_FOR_HUMAN_REVIEW"

    _run(write=_capture, permit=permit, on_ready_for_review=_on_ready, on_phase=_on_phase)
    assert seen["permit"] is permit
    assert seen["on_ready_for_review"] is _on_ready
    assert seen["on_phase"] is _on_phase


def test_on_ready_for_review_and_on_phase_are_never_invoked_when_the_write_callable_never_calls_them():
    """A pre-write verification failure (plan-hash mismatch here) never
    invokes the write callable at all -- so it can never reach
    on_ready_for_review/on_phase either. _run's own defaults
    (_never_ready_for_review/_never_phase) assert this for every OTHER
    test in this file; this test asserts it explicitly for a write
    callable that WOULD call them if ever invoked."""
    async def _would_call_back(account_id, storage_state, plan, permit, on_ready_for_review, on_phase) -> str:
        await on_ready_for_review()
        on_phase("WRITING")
        return "READY_FOR_HUMAN_REVIEW"

    result = _run(
        expected_plan_hash="tampered-" + VALID_PLAN_HASH, write=_would_call_back,
    )
    assert result == "INPUT_OR_PLAN_MISMATCH"


def test_the_session_store_is_never_touched_if_planning_already_failed():
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}})
    job = FakeClaimedJob(workflow_name="not_a_real_workflow")
    _run(job, session_store=store, write=_never_called)
    assert store.load_calls == []


# --------------------------------------------------------------------- #
# Correction (Phase 1C-C, finding 6): the injected write callable's
# return value is validated against a narrow, fixed subset -- it may
# never manufacture a worker-owned outcome.
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("allowed_result", ["READY_FOR_HUMAN_REVIEW", "IDENTITY_FAILED", "WRITE_ABORTED"])
def test_every_writer_allowed_result_passes_through_unchanged(allowed_result):
    async def _return_it(*args, **kwargs) -> str:
        return allowed_result

    assert _run(write=_return_it) == allowed_result


def test_an_arbitrary_unrecognized_string_from_the_writer_becomes_internal_execution_error():
    async def _made_up(*args, **kwargs) -> str:
        return "TOTALLY_MADE_UP_OUTCOME"

    assert _run(write=_made_up) == "INTERNAL_EXECUTION_ERROR"


def test_none_from_the_writer_becomes_internal_execution_error():
    async def _returns_none(*args, **kwargs):
        return None

    assert _run(write=_returns_none) == "INTERNAL_EXECUTION_ERROR"


def test_a_non_string_from_the_writer_becomes_internal_execution_error():
    async def _returns_a_dict(*args, **kwargs):
        return {"status": "READY_FOR_HUMAN_REVIEW"}  # never trusted, even if shaped like something plausible

    assert _run(write=_returns_a_dict) == "INTERNAL_EXECUTION_ERROR"


def test_an_unhashable_value_from_the_writer_never_raises_and_becomes_internal_execution_error():
    """A list/dict is unhashable -- `in a_frozenset` would raise TypeError
    if not guarded; this must fail closed, never crash the check."""
    async def _returns_a_list(*args, **kwargs):
        return ["READY_FOR_HUMAN_REVIEW"]

    assert _run(write=_returns_a_list) == "INTERNAL_EXECUTION_ERROR"


@pytest.mark.parametrize("worker_owned_result", ["INPUT_OR_PLAN_MISMATCH", "RUNNER_CANCELLED", "LEASE_LOST"])
def test_writer_cannot_manufacture_a_worker_owned_outcome(worker_owned_result):
    """INPUT_OR_PLAN_MISMATCH/SESSION_NOT_READY are this module's OWN
    pre-write verification outcomes; RUNNER_CANCELLED/LEASE_LOST are the
    worker's own cancellation bookkeeping -- the injected write callable
    has no way to honestly report any of these about itself, so all are
    treated exactly like an unrecognized string: INTERNAL_EXECUTION_ERROR,
    never passed through as if the writer had legitimately produced them."""
    async def _claims_a_worker_outcome(*args, **kwargs) -> str:
        return worker_owned_result

    assert _run(write=_claims_a_worker_outcome) == "INTERNAL_EXECUTION_ERROR"


def test_session_not_ready_is_also_never_accepted_from_the_writer():
    """SESSION_NOT_READY is this module's OWN pre-write outcome (reported
    before the write callable is ever invoked, see
    test_missing_session_never_invokes_the_write_callable) -- the write
    callable itself can never legitimately produce it either."""
    async def _claims_session_not_ready(*args, **kwargs) -> str:
        return "SESSION_NOT_READY"

    assert _run(write=_claims_session_not_ready) == "INTERNAL_EXECUTION_ERROR"


def test_do_not_import_the_real_portal_writer():
    """No attribute of this module was imported FROM mcma.portal (an actual
    `from mcma.portal.x import y` would bind `y` here with __module__
    starting with "mcma.portal") -- see tests/app/workstation_runner/
    test_import_isolation.py for the definitive fresh-process proof that
    this holds across the whole package."""
    import mcma.app.workstation_runner.execute_executor as module

    for value in vars(module).values():
        module_name = getattr(value, "__module__", "")
        assert not module_name.startswith("mcma.portal")
