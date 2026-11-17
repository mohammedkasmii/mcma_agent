"""Supervised Mode Normal golden canary -- the central dispatcher's share.

The server-owned opt-in (`mode_normal_canary_enabled`, threaded from
Settings.mode_normal_golden_canary_enabled by mcma.app.central_server only)
admits EXECUTE ONLY for mission_normal plans that are writeable, review-free
and fully TVA-profiled, one active canary globally. With it off, nothing
changes. Unit-level: dispatch.py called directly, server time injected."""

import dataclasses

import pytest

from dispatch_test_support import (  # noqa: F401
    MAMDA_OUJDA, NADOR, NEEDS_REVIEW_TYPED_INPUT, OUJDA, VALID_TYPED_INPUT, VALID_WORKFLOW_NAME, conn, create_job,
    create_runner, create_user, db_path, encryptor, grant_access, principal, real_plan_hash, set_ready,
)
from datetime import datetime, timezone

from mcma.app.auth.users import UserInputError
from mcma.app.runners import dispatch
from mcma.domain.values import RubriqueId
from mcma.mapping.wexia import parse_wexia
from mcma.planning.canary import EXECUTION_PROFILE_MODE_NORMAL_GOLDEN_CANARY
from mcma.planning.registry import WorkflowRegistry, default_registry

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
REGISTRY = default_registry()


def _world(conn, *, account=OUJDA):
    user = create_user(conn)
    grant_access(conn, user, account)
    runner = create_runner(conn, user, status="ACTIVE", last_seen_at="2026-01-01T00:00:00+00:00")
    set_ready(conn, runner, account)
    return user, runner


def _seed(conn, encryptor, *, user, job_id="execute-1", parent_id="parent-1", account_id=OUJDA,
          workflow_name=VALID_WORKFLOW_NAME, typed_input=None, plan_hash=None):
    typed_input = typed_input if typed_input is not None else VALID_TYPED_INPUT
    plan_hash = plan_hash if plan_hash is not None else real_plan_hash(typed_input)
    create_job(conn, parent_id, account_id=account_id, user_id=user, mode="DRY_RUN", status="DRY_RUN_VERIFIED",
               workflow_name=workflow_name, typed_input=typed_input, encryptor=encryptor,
               created_at="2026-01-01T00:00:00+00:00")
    create_job(conn, job_id, account_id=account_id, user_id=user, mode="EXECUTE", status="PLANNED",
               workflow_name=workflow_name, typed_input=typed_input, encryptor=encryptor,
               created_at="2026-01-01T00:01:00+00:00", parent_job_id=parent_id, plan_hash=plan_hash)
    return job_id


def _claim(conn, encryptor, runner, *, canary=True):
    return dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        mode_normal_canary_enabled=canary,
    )


def _start(conn, runner, envelope, encryptor, *, registry=REGISTRY, canary=True):
    return dispatch.start_job(
        conn, principal(conn, runner), job_id=envelope.job_id, claim_token=envelope.claim_token,
        generation=envelope.generation, workflow_registry=registry, encryptor=encryptor, now=T0,
        mode_normal_canary_enabled=canary,
    )


def _finish(conn, runner, envelope, result, *, canary=True):
    return dispatch.finish_job(
        conn, principal(conn, runner), job_id=envelope.job_id, claim_token=envelope.claim_token,
        generation=envelope.generation, result=result, now=T0, mode_normal_canary_enabled=canary,
    )


# --------------------------------------------------------------------- #
# Disabled (the default): nothing changes
# --------------------------------------------------------------------- #


def test_canary_disabled_execute_is_never_claimed(conn, encryptor):
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user)
    assert _claim(conn, encryptor, runner, canary=False) is None
    assert dispatch.EXECUTE_DISPATCH_ENABLED is False


def test_canary_disabled_execute_can_never_be_started_or_finished(conn, encryptor):
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user)
    envelope = _claim(conn, encryptor, runner, canary=True)
    with pytest.raises(UserInputError) as exc:
        _start(conn, runner, envelope, encryptor, canary=False)
    assert exc.value.code == "JOB_NOT_STARTABLE"


# --------------------------------------------------------------------- #
# Enabled: claim
# --------------------------------------------------------------------- #


def test_canary_claims_a_mode_normal_execute_with_the_profile_on_the_wire(conn, encryptor):
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user)
    envelope = _claim(conn, encryptor, runner)
    assert envelope.mode == "EXECUTE"
    assert envelope.execution_profile == EXECUTION_PROFILE_MODE_NORMAL_GOLDEN_CANARY
    assert envelope.to_response_dict()["execution_profile"] == EXECUTION_PROFILE_MODE_NORMAL_GOLDEN_CANARY


def test_dry_run_envelopes_stay_byte_identical_with_the_canary_on(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "dry-1", account_id=OUJDA, user_id=user, mode="DRY_RUN", status="QUEUED",
               workflow_name=VALID_WORKFLOW_NAME, typed_input=VALID_TYPED_INPUT, encryptor=encryptor,
               created_at="2026-01-01T00:00:00+00:00")
    envelope = _claim(conn, encryptor, runner)
    assert envelope.mode == "DRY_RUN" and envelope.execution_profile is None
    assert "execution_profile" not in envelope.to_response_dict()


def test_canary_never_claims_pec(conn, encryptor):
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user, workflow_name="garage_conventionne")
    assert _claim(conn, encryptor, runner) is None


def test_canary_never_claims_mamda(conn, encryptor):
    user, runner = _world(conn)
    grant_access(conn, user, MAMDA_OUJDA)
    _seed(conn, encryptor, user=user, account_id=MAMDA_OUJDA)
    assert _claim(conn, encryptor, runner) is None


def test_canary_never_claims_for_an_account_that_is_not_ready(conn, encryptor):
    user = create_user(conn)
    grant_access(conn, user, OUJDA)
    runner = create_runner(conn, user, status="ACTIVE", last_seen_at="2026-01-01T00:00:00+00:00")
    _seed(conn, encryptor, user=user)  # session never reported READY
    assert _claim(conn, encryptor, runner) is None


def test_canary_never_claims_another_employees_job(conn, encryptor):
    owner, _owner_runner = _world(conn)
    _other, other_runner = _world(conn)
    _seed(conn, encryptor, user=owner)
    assert _claim(conn, encryptor, other_runner) is None


def test_only_one_canary_is_active_globally(conn, encryptor):
    first_user, first_runner = _world(conn, account=OUJDA)
    second_user, second_runner = _world(conn, account=NADOR)
    _seed(conn, encryptor, user=first_user, job_id="execute-1", parent_id="parent-1", account_id=OUJDA)
    _seed(conn, encryptor, user=second_user, job_id="execute-2", parent_id="parent-2", account_id=NADOR)

    first = _claim(conn, encryptor, first_runner)
    assert first.job_id == "execute-1"
    assert _claim(conn, encryptor, second_runner) is None          # while CLAIMED
    _start(conn, first_runner, first, encryptor)
    assert _claim(conn, encryptor, second_runner) is None          # while RUNNING
    _finish(conn, first_runner, first, "READY_FOR_HUMAN_REVIEW")
    second = _claim(conn, encryptor, second_runner)                # slot released
    assert second.job_id == "execute-2"


# --------------------------------------------------------------------- #
# Enabled: start re-derives eligibility and fails closed
# --------------------------------------------------------------------- #


def test_canary_start_admits_an_eligible_plan(conn, encryptor):
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user)
    envelope = _claim(conn, encryptor, runner)
    result = _start(conn, runner, envelope, encryptor)
    assert result["status"] == "RUNNING" and result["job_status"] == "IDENTITY_VERIFYING"


def _assert_failed_closed(conn, job_id):
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (job_id,)).fetchone()
    assert job["status"] == "ERROR"
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (job_id,)).fetchone()
    assert row["status"] == "FAILED"


def test_canary_start_refuses_a_plan_that_needs_review(conn, encryptor):
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user, typed_input=NEEDS_REVIEW_TYPED_INPUT,
          plan_hash=real_plan_hash(NEEDS_REVIEW_TYPED_INPUT))
    envelope = _claim(conn, encryptor, runner)
    with pytest.raises(UserInputError):
        _start(conn, runner, envelope, encryptor)
    _assert_failed_closed(conn, envelope.job_id)


def test_canary_start_refuses_a_rubrique_outside_the_tva_profile(conn, encryptor):
    """Defense in depth: the planner already turns an unprofiled rubrique
    into NeedsReview, so a builder is forced to emit one anyway -- the
    dispatcher must still refuse it."""
    real_builder = default_registry().get(VALID_WORKFLOW_NAME)

    def poisoned_builder(typed_input):
        plan = real_builder(typed_input)
        steps = tuple(dataclasses.replace(s, rubrique_id=RubriqueId("22")) for s in plan.steps)
        return dataclasses.replace(plan, steps=steps)

    registry = WorkflowRegistry()
    registry.register(VALID_WORKFLOW_NAME, poisoned_builder)
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user)
    envelope = _claim(conn, encryptor, runner)
    with pytest.raises(UserInputError):
        _start(conn, runner, envelope, encryptor, registry=registry)
    _assert_failed_closed(conn, envelope.job_id)


def test_canary_start_refuses_when_another_canary_is_already_active(conn, encryptor):
    """The claim-time global check is authoritative; start re-checks it
    against a directly-inserted competing assignment."""
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user)
    envelope = _claim(conn, encryptor, runner)
    other_user, other_runner = _world(conn, account=NADOR)
    _seed(conn, encryptor, user=other_user, job_id="execute-9", parent_id="parent-9", account_id=NADOR)
    conn.execute(
        "INSERT INTO workstation_job_dispatch (assignment_id, job_id, runner_id, generation, claim_token_digest, "
        "status, claimed_at, started_at, lease_expires_at) VALUES ('a9', 'execute-9', ?, 1, ?, 'RUNNING', ?, ?, ?)",
        (other_runner, "d" * 64, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
         "2026-01-01T01:00:00+00:00"),
    )
    with pytest.raises(UserInputError):
        _start(conn, runner, envelope, encryptor)
    _assert_failed_closed(conn, envelope.job_id)


# --------------------------------------------------------------------- #
# Enabled: finish
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("result,expected", [
    ("READY_FOR_HUMAN_REVIEW", "READY_FOR_HUMAN_REVIEW"),
    ("WRITE_ABORTED", "WRITE_ABORTED"),
    ("IDENTITY_FAILED", "IDENTITY_FAILED"),
    ("LEASE_LOST", "WRITE_ABORTED"),
])
def test_canary_finish_maps_execute_outcomes(conn, encryptor, result, expected):
    user, runner = _world(conn)
    _seed(conn, encryptor, user=user)
    envelope = _claim(conn, encryptor, runner)
    _start(conn, runner, envelope, encryptor)
    assert _finish(conn, runner, envelope, result)["job_status"] == expected


def test_canary_plan_eligibility_rule_itself():
    from mcma.planning.canary import (
        REFUSAL_NEEDS_REVIEW, REFUSAL_UNPROFILED_RUBRIQUE, REFUSAL_WRONG_WORKFLOW, mode_normal_canary_refusal,
    )
    from mcma.planning.plan import build_garage_conventionne_plan

    plan = default_registry().get(VALID_WORKFLOW_NAME)(parse_wexia(VALID_TYPED_INPUT))
    assert mode_normal_canary_refusal(plan) is None
    review = default_registry().get(VALID_WORKFLOW_NAME)(parse_wexia(NEEDS_REVIEW_TYPED_INPUT))
    assert mode_normal_canary_refusal(review) == REFUSAL_NEEDS_REVIEW
    steps = tuple(dataclasses.replace(s, rubrique_id=RubriqueId("17")) for s in plan.steps)
    assert mode_normal_canary_refusal(dataclasses.replace(plan, steps=steps)) == REFUSAL_UNPROFILED_RUBRIQUE
    pec_input = {**VALID_TYPED_INPUT, "dossier": {**VALID_TYPED_INPUT["dossier"],
                                                 "mission_type": "garage conventionne",
                                                 "incident_description": "PEC"}}
    pec = build_garage_conventionne_plan(parse_wexia(pec_input))
    assert mode_normal_canary_refusal(pec) == REFUSAL_WRONG_WORKFLOW
