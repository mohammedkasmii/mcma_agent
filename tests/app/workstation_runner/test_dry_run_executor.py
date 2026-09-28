"""mcma.app.workstation_runner.dry_run_executor -- Phase 1C-B, item E.
Unit-level: the injected `check_identity_read_only` is a plain async fake,
never a real Playwright/portal object (see module docstring on the
lightweight-package import isolation this module must keep). No live MCMA
website is required anywhere in this file."""

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from mcma.app.workstation_runner.dry_run_executor import run_dry_run_check
from mcma.mapping.wexia import parse_wexia
from mcma.planning.registry import default_registry

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"

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
    raise AssertionError("check_identity_read_only must never be called")


async def _matches(*args, **kwargs) -> bool:
    return True


async def _does_not_match(*args, **kwargs) -> bool:
    return False


def run_async(coro):
    return asyncio.run(coro)


def _run(job=None, *, expected_plan_hash=VALID_PLAN_HASH, session_store=None, check=_matches):
    return run_async(run_dry_run_check(
        job or FakeClaimedJob(),
        expected_plan_hash=expected_plan_hash,
        session_store=session_store or FakeSessionStore({OUJDA: {"cookies": [], "origins": []}}),
        workflow_registry=REGISTRY,
        check_identity_read_only=check,
    ))


def test_identity_matched_when_the_portal_check_confirms_it():
    assert _run(check=_matches) == "IDENTITY_MATCHED"


def test_identity_not_matched_when_the_portal_check_does_not_confirm_it():
    assert _run(check=_does_not_match) == "IDENTITY_NOT_MATCHED"


def test_plan_hash_mismatch_never_launches_a_browser():
    result = _run(expected_plan_hash="tampered-" + VALID_PLAN_HASH, check=_never_called)
    assert result == "PORTAL_READ_FAILED"


def test_input_hash_mismatch_never_launches_a_browser():
    job = FakeClaimedJob(input_hash="tampered-hash")
    assert _run(job, check=_never_called) == "PORTAL_READ_FAILED"


def test_tampered_typed_input_never_launches_a_browser():
    """input_hash is recomputed from the RECEIVED typed_input -- if both
    were tampered consistently, plan-building itself still fails closed
    (an unknown workflow / malformed payload), never silently accepted."""
    tampered = {**VALID_TYPED_INPUT, "dossier": {**VALID_TYPED_INPUT["dossier"], "is_reform": True}}
    job = FakeClaimedJob(typed_input=tampered, input_hash=_input_hash(tampered))
    assert _run(job, check=_never_called) == "PORTAL_READ_FAILED"


def test_unknown_workflow_name_never_launches_a_browser():
    job = FakeClaimedJob(workflow_name="not_a_real_workflow")
    assert _run(job, check=_never_called) == "PORTAL_READ_FAILED"


def test_missing_session_never_launches_a_browser():
    store = FakeSessionStore({})  # no session saved for any account
    assert _run(session_store=store, check=_never_called) == "SESSION_UNAVAILABLE"


def test_unreadable_or_corrupt_session_never_launches_a_browser():
    store = FakeSessionStore(raises=RuntimeError("decrypt failed"))
    assert _run(session_store=store, check=_never_called) == "SESSION_UNAVAILABLE"


def test_mamda_account_is_structurally_refused_before_any_browser_launch():
    """The executor itself has no MAMDA-specific check -- this is the
    session store's own account allowlist (WorkstationSessionStore/
    RUNNER_ACCOUNT_IDS) refusing an account outside {Oujda, Nador}, which
    this test exercises via a fake that mirrors that exact refusal."""
    class _MamdaRefusingStore(FakeSessionStore):
        def load(self, account_id: str):
            if account_id not in (OUJDA, NADOR):
                raise ValueError("account_id is not one of the allowed workstation MCMA accounts")
            return super().load(account_id)

    job = FakeClaimedJob(account_id="acct-mamda-oujda")
    assert _run(job, session_store=_MamdaRefusingStore({}), check=_never_called) == "SESSION_UNAVAILABLE"


def test_oujda_and_nador_are_both_supported():
    for account_id in (OUJDA, NADOR):
        job = FakeClaimedJob(account_id=account_id)
        store = FakeSessionStore({account_id: {"cookies": [], "origins": []}})
        assert _run(job, session_store=store, check=_matches) == "IDENTITY_MATCHED"


def test_an_operational_failure_from_the_portal_check_is_contained():
    async def _boom(*args, **kwargs):
        raise RuntimeError("browser crashed")

    assert _run(check=_boom) == "PORTAL_READ_FAILED"


def test_cancellation_propagates_from_inside_the_portal_check():
    async def _cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _run(check=_cancel)


def test_the_portal_check_receives_a_planning_expected_identity_never_a_portal_type():
    """The injected callable's signature carries only primitives and
    mcma.planning.plan.ExpectedIdentity -- never a mcma.portal type (this
    module must never import mcma.portal at all)."""
    from mcma.planning.plan import ExpectedIdentity as PlanExpectedIdentity

    seen = {}

    async def _capture(account_id, storage_state, expected_identity, matricule):
        seen["account_id"] = account_id
        seen["expected_identity"] = expected_identity
        seen["matricule"] = matricule
        return True

    _run(check=_capture)
    assert seen["account_id"] == OUJDA
    assert isinstance(seen["expected_identity"], PlanExpectedIdentity)
    assert seen["matricule"] == "77001-C-3"


def test_the_session_store_is_never_touched_if_planning_already_failed():
    store = FakeSessionStore({OUJDA: {"cookies": [], "origins": []}})
    job = FakeClaimedJob(workflow_name="not_a_real_workflow")
    _run(job, session_store=store, check=_never_called)
    assert store.load_calls == []
