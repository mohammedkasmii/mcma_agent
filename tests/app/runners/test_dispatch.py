"""mcma.app.runners.dispatch -- durable workstation job-dispatch control
plane (Phase 1C-A). Unit-level: calls dispatch.py directly (no HTTP layer,
no Playwright, no execution engine -- see dispatch.py's own module
docstring). Server time is always injected via `now=`; no real sleeps."""

import json
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from dispatch_test_support import (  # noqa: F401
    MAMDA_OUJDA, NADOR, NEEDS_REVIEW_TYPED_INPUT, OUJDA, VALID_TYPED_INPUT, VALID_WORKFLOW_NAME, conn, create_job,
    create_runner, create_user, db_path, encryptor, grant_access, principal, revoke_access, set_ready,
)
from mcma.app.auth.users import UserInputError
from mcma.app.runners import dispatch
from mcma.execution.inputs import TestOnlyPlaintextEncryptor
from mcma.mapping.wexia import parse_wexia
from mcma.planning.registry import default_registry

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _world(conn, *, ready=(OUJDA,), runner_status="ACTIVE", last_seen_at="2026-01-01T00:00:00+00:00"):
    user = create_user(conn)
    grant_access(conn, user, OUJDA)
    runner = create_runner(conn, user, status=runner_status, last_seen_at=last_seen_at)
    for account in ready:
        set_ready(conn, runner, account)
    return user, runner


# --------------------------------------------------------------------- #
# eligibility / selection
# --------------------------------------------------------------------- #


def test_oldest_eligible_job_is_claimed_first(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-new", account_id=OUJDA, user_id=user, created_at="2026-01-01T00:05:00+00:00", encryptor=encryptor)
    create_job(conn, "job-old", account_id=OUJDA, user_id=user, created_at="2026-01-01T00:00:00+00:00", encryptor=encryptor)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )
    assert envelope is not None
    assert envelope.job_id == "job-old"


def test_a_runner_can_only_claim_its_own_employees_job(conn, encryptor):
    user, runner = _world(conn)
    other_user = create_user(conn)
    grant_access(conn, other_user, OUJDA)
    create_job(conn, "job-1", account_id=OUJDA, user_id=other_user, encryptor=encryptor)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )
    assert envelope is None


def test_mamda_jobs_are_never_dispatched(conn, encryptor):
    user, runner = _world(conn)
    grant_access(conn, user, MAMDA_OUJDA)
    create_job(conn, "job-mamda", account_id=MAMDA_OUJDA, user_id=user, encryptor=encryptor)
    # A runner cannot even report readiness for MAMDA -- database CHECK-constrained.
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        set_ready(conn, runner, MAMDA_OUJDA)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )
    assert envelope is None


def test_a_job_for_an_account_the_runner_has_not_reported_ready_is_not_claimed(conn, encryptor):
    user, runner = _world(conn, ready=())  # NOT_CONFIGURED by default -- never marked READY
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )
    assert envelope is None


def test_an_offline_runner_receives_no_job(conn, encryptor):
    user, runner = _world(conn, last_seen_at="2026-01-01T00:00:00+00:00")
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    far_future = T0 + timedelta(hours=1)  # well past OFFLINE_AFTER_SECONDS
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=far_future,
    )
    assert envelope is None


def test_a_revoked_runner_is_rejected_not_silently_skipped(conn, encryptor):
    user, runner = _world(conn, runner_status="REVOKED")
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.claim_job(
            conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        )
    assert exc_info.value.status == 401


def test_an_employee_who_lost_execute_permission_yields_no_job(conn, encryptor):
    user, runner = _world(conn)
    conn.execute("UPDATE users SET role = 'viewer' WHERE user_id = ?", (user,))
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    with pytest.raises(UserInputError):
        dispatch.claim_job(
            conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        )


@pytest.mark.parametrize("mode,status,should_claim", [
    ("DRY_RUN", "QUEUED", True),
    # EXECUTE-PLANNED is a structurally dispatchable (mode, status) pair,
    # but Phase 1C-B's EXECUTE_DISPATCH_ENABLED gate (item C) refuses it
    # regardless -- see test_execute_is_never_claimed_while_the_gate_is_off
    # below for the dedicated, explicit proof of that gate.
    ("EXECUTE", "PLANNED", False),
    ("DRY_RUN", "PLANNED", False),
    ("EXECUTE", "QUEUED", False),
    ("DRY_RUN", "PLANNING", False),
    ("EXECUTE", "WRITING", False),
    ("DRY_RUN", "ERROR", False),
    ("EXECUTE", "AWAITING_HUMAN_CONFIRMATION", False),
])
def test_only_the_exact_dispatchable_mode_status_pairs_are_claimed(conn, encryptor, mode, status, should_claim):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, mode=mode, status=status, encryptor=encryptor)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )
    assert (envelope is not None) is should_claim


def test_execute_is_never_claimed_while_the_gate_is_off(conn, encryptor):
    """Phase 1C-B item C: an explicit, server-owned capability gate --
    EXECUTE_DISPATCH_ENABLED is False everywhere in this codebase today,
    and the client cannot override it (the claim request carries only
    protocol_version/app_version -- no mode field exists to request)."""
    assert dispatch.EXECUTE_DISPATCH_ENABLED is False
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, mode="EXECUTE", status="PLANNED", encryptor=encryptor)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )
    assert envelope is None


def test_a_runner_already_holding_an_active_job_gets_no_second_one(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, created_at="2026-01-01T00:00:00+00:00", encryptor=encryptor)
    create_job(conn, "job-2", account_id=OUJDA, user_id=user, created_at="2026-01-01T00:01:00+00:00", encryptor=encryptor)
    p = principal(conn, runner)
    first = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert first.job_id == "job-1"
    second = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert second is None


def test_a_job_already_claimed_by_another_runner_is_not_claimed_again(conn, encryptor):
    # Only one ACTIVE runner may exist per employee (registry-level, DB
    # constrained) -- so "already claimed by ANOTHER runner" is modeled by
    # seeding a foreign runner's CLAIMED row directly (as if a second
    # pilot's runner somehow held it), and proving the job's OWN eligible
    # runner still cannot claim it out from under that active assignment.
    user, runner = _world(conn)
    other_user = create_user(conn)
    foreign_runner = create_runner(conn, other_user)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    conn.execute(
        "INSERT INTO workstation_job_dispatch (assignment_id, job_id, runner_id, generation, claim_token_digest, "
        "status, claimed_at, lease_expires_at) VALUES ('a-foreign', 'job-1', ?, 1, ?, 'CLAIMED', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T01:00:00+00:00')",
        (foreign_runner, "f" * 64),
    )
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )
    assert envelope is None


def test_two_simultaneous_claims_for_the_same_job_never_both_succeed(conn, encryptor):
    """Claim selection-plus-insert happens inside one BEGIN IMMEDIATE
    transaction, so two overlapping claim attempts by the same runner (a
    duplicated/retried request racing the original) are fully serialized by
    SQLite's exclusive write lock: whichever commits second re-evaluates
    its own NOT EXISTS/already-active checks against the first's already-
    committed row and gets None, never a second CLAIMED row for job-1."""
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)

    results = {}

    def _claim(name):
        results[name] = dispatch.claim_job(
            conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        )

    t1 = threading.Thread(target=_claim, args=("a",))
    t2 = threading.Thread(target=_claim, args=("b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    winners = [v for v in results.values() if v is not None]
    assert len(winners) == 1
    assert winners[0].job_id == "job-1"
    claimed_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM workstation_job_dispatch WHERE job_id = 'job-1' AND status = 'CLAIMED'"
    ).fetchone()["n"]
    assert claimed_rows == 1


# --------------------------------------------------------------------- #
# input verification / fail-closed
# --------------------------------------------------------------------- #


def test_the_verified_typed_input_is_returned_in_the_envelope(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, typed_input={"claim_id": "C-42"}, encryptor=encryptor)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope.typed_input == {"claim_id": "C-42"}


def test_a_job_with_no_input_row_is_never_dispatched_and_fails_closed(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, typed_input=False, encryptor=encryptor)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is None
    row = conn.execute("SELECT status FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert row["status"] == "ERROR"


def test_a_job_whose_input_no_longer_matches_its_recorded_hash_is_never_dispatched(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    # Tamper the JOB's recorded input_hash (what retrieve_and_verify_job_input
    # actually compares the decrypted plaintext's hash against) so it no
    # longer matches the untouched, correctly-encrypted job_inputs row.
    conn.execute("UPDATE automation_jobs SET input_hash = 'tampered' || input_hash WHERE job_id = 'job-1'")
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is None
    row = conn.execute("SELECT status FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert row["status"] == "ERROR"


def test_an_expired_input_is_never_dispatched(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    conn.execute("UPDATE job_inputs SET expires_at = '2020-01-01T00:00:00+00:00' WHERE job_id = 'job-1'")
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is None


def test_an_undecryptable_input_is_never_dispatched(conn):
    class _AlwaysFailsEncryptor:
        def encrypt(self, plaintext: bytes) -> bytes:
            return plaintext

        def decrypt(self, ciphertext: bytes) -> bytes:
            raise ValueError("boom")

    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=TestOnlyPlaintextEncryptor())
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=_AlwaysFailsEncryptor(), now=T0,
    )
    assert envelope is None
    row = conn.execute("SELECT status FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert row["status"] == "ERROR"


# --------------------------------------------------------------------- #
# claim-token storage / secrecy
# --------------------------------------------------------------------- #


def test_only_the_claim_tokens_digest_is_stored_never_the_plaintext(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    row = conn.execute("SELECT claim_token_digest FROM workstation_job_dispatch WHERE job_id = 'job-1'").fetchone()
    assert row["claim_token_digest"] == dispatch.digest_token(envelope.claim_token)
    assert envelope.claim_token not in row["claim_token_digest"]


def test_envelope_repr_never_reveals_the_claim_token_or_typed_input(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, typed_input={"secret_field": "SENSITIVE-VALUE"}, encryptor=encryptor)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    text = repr(envelope)
    assert envelope.claim_token not in text
    assert "SENSITIVE-VALUE" not in text


# --------------------------------------------------------------------- #
# renew
# --------------------------------------------------------------------- #


def test_renewing_with_the_correct_token_extends_the_lease(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    later = T0 + timedelta(seconds=30)
    result = dispatch.renew_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=later,
    )
    assert result["lease_expires_at"] > envelope.lease_expires_at


def test_renewing_with_a_wrong_token_is_rejected(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token="mcma_ct_wrong-token-value", generation=envelope.generation, now=T0)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_renewing_with_a_stale_generation_is_rejected(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation + 1, now=T0)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_a_runner_cannot_renew_another_runners_claim(conn, encryptor):
    user, runner = _world(conn)
    other_user = create_user(conn)
    other_runner = create_runner(conn, other_user)  # a different employee's own runner
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(
            conn, principal(conn, other_runner), job_id=envelope.job_id, claim_token=envelope.claim_token,
            generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_renewal_is_refused_immediately_once_the_runner_is_revoked(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    conn.execute("UPDATE runners SET status = 'REVOKED', revoked_at = ? WHERE runner_id = ?", (dispatch._iso(T0), runner))
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0)
    assert exc_info.value.status == 401


def test_renewal_is_refused_immediately_once_account_access_is_removed(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    conn.execute("DELETE FROM user_account_access WHERE user_id = ?", (user,))
    with pytest.raises(UserInputError):
        dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0)


def test_an_expired_assignment_can_never_be_revived_by_renewing(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    way_later = T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS + 1)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=way_later)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


# --------------------------------------------------------------------- #
# expiry recovery
# --------------------------------------------------------------------- #


def test_expiry_recovery_frees_the_job_for_a_fresh_claim_with_a_new_generation(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    first = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    way_later = T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS + 1)
    # The runner keeps heartbeating independently of its lease -- simulate
    # a recent heartbeat so this claim isn't ALSO refused for being offline.
    conn.execute(
        "UPDATE runners SET last_seen_at = ? WHERE runner_id = ?",
        (dispatch._iso(way_later - timedelta(seconds=5)), runner),
    )
    second = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=way_later)
    assert second is not None
    assert second.job_id == first.job_id
    assert second.generation == first.generation + 1
    # the first token is permanently fenced -- it can never renew the new assignment
    with pytest.raises(UserInputError):
        dispatch.renew_job(conn, p, job_id=first.job_id, claim_token=first.claim_token, generation=first.generation, now=way_later)


def test_expiry_never_touches_automation_jobs_status(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    way_later = T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS + 1)
    dispatch.expire_stale_assignments(conn, now=way_later)
    row = conn.execute("SELECT status FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert row["status"] == "QUEUED"  # untouched by dispatch -- only workstation_job_dispatch changed


def test_a_job_moved_past_dispatchable_status_is_never_silently_requeued_after_expiry(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    conn.execute("UPDATE automation_jobs SET status = 'WRITING' WHERE job_id = 'job-1'")
    way_later = T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS + 1)
    conn.execute(
        "UPDATE runners SET last_seen_at = ? WHERE runner_id = ?",
        (dispatch._iso(way_later - timedelta(seconds=5)), runner),
    )
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=way_later)
    assert envelope is None


# --------------------------------------------------------------------- #
# release
# --------------------------------------------------------------------- #


def test_release_frees_the_job_for_a_new_claim(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    result = dispatch.release_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        reason_code="RUNNER_SHUTDOWN", now=T0,
    )
    assert result["status"] == "RELEASED"
    again = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert again is not None
    assert again.generation == envelope.generation + 1


def test_release_rejects_a_reason_code_outside_the_fixed_set(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    with pytest.raises(UserInputError):
        dispatch.release_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
            reason_code="I_FEEL_LIKE_IT", now=T0,
        )


def test_release_history_row_is_retained_not_deleted(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    dispatch.release_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        reason_code="CANCELLED_BEFORE_EXECUTION", now=T0,
    )
    row = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = 'job-1'").fetchone()
    assert row["status"] == "RELEASED"
    assert row["outcome_code"] == "CANCELLED_BEFORE_EXECUTION"


# --------------------------------------------------------------------- #
# P1 correction 1 -- renewal must recheck access to the CLAIMED account
# --------------------------------------------------------------------- #


def test_renewal_is_refused_once_access_to_the_claimed_jobs_account_is_removed(conn, encryptor):
    """Oujda and Nador both granted; the claim is on Oujda; ONLY Oujda
    access is removed (Nador remains) -- _ineligibility() alone would still
    say the employee is eligible (Nador keeps them >= 1 MCMA account), so
    renewal must recheck the CLAIMED job's own account_id specifically."""
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    revoke_access(conn, user, OUJDA)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    # generic refusal -- never reveals the token, the account, or the cause
    message = str(exc_info.value)
    assert envelope.claim_token not in message
    assert OUJDA not in message


def test_removing_unrelated_account_access_does_not_invalidate_a_legitimate_claim(conn, encryptor):
    """Oujda and Nador both granted; the claim is on Oujda; Nador access
    (unrelated to this claim) is removed -- renewal must still succeed."""
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    revoke_access(conn, user, NADOR)
    later = T0 + timedelta(seconds=10)
    result = dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=later)
    assert result["lease_expires_at"] > envelope.lease_expires_at


# --------------------------------------------------------------------- #
# P1 correction 2 -- expiry fencing (<=) applies to renew AND release
# --------------------------------------------------------------------- #


def test_one_microsecond_before_expiry_renewal_still_succeeds(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    lease_deadline = dispatch._parse(envelope.lease_expires_at)
    just_before = lease_deadline - timedelta(microseconds=1)
    result = dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=just_before)
    assert result["lease_expires_at"] > envelope.lease_expires_at


def test_exactly_at_expiry_renewal_is_refused_and_the_row_becomes_expired(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    lease_deadline = dispatch._parse(envelope.lease_expires_at)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=lease_deadline)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    row = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = 'job-1'").fetchone()
    assert row["status"] == "EXPIRED"
    assert row["outcome_code"] == "LEASE_EXPIRED"


def test_exactly_at_expiry_release_is_refused_and_the_row_becomes_expired(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    lease_deadline = dispatch._parse(envelope.lease_expires_at)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.release_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
            reason_code="RUNNER_SHUTDOWN", now=lease_deadline,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    row = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = 'job-1'").fetchone()
    assert row["status"] == "EXPIRED"
    assert row["outcome_code"] == "LEASE_EXPIRED"


def test_an_expired_token_affects_neither_renew_nor_release_of_the_next_generation(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    first = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    lease_deadline = dispatch._parse(first.lease_expires_at)
    conn.execute(
        "UPDATE runners SET last_seen_at = ? WHERE runner_id = ?",
        (dispatch._iso(lease_deadline), runner),
    )
    second = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=lease_deadline)
    assert second is not None and second.generation == first.generation + 1

    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(conn, p, job_id=first.job_id, claim_token=first.claim_token, generation=first.generation, now=lease_deadline)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    with pytest.raises(UserInputError) as exc_info:
        dispatch.release_job(
            conn, p, job_id=first.job_id, claim_token=first.claim_token, generation=first.generation,
            reason_code="RUNNER_SHUTDOWN", now=lease_deadline,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    # the SECOND (current) generation is entirely unaffected
    a_moment_later = lease_deadline + timedelta(seconds=1)
    still_good = dispatch.renew_job(conn, p, job_id=second.job_id, claim_token=second.claim_token, generation=second.generation, now=a_moment_later)
    assert still_good["lease_expires_at"] > second.lease_expires_at


# --------------------------------------------------------------------- #
# P1 correction 3 -- server preflights the same bounds as the Windows client
# --------------------------------------------------------------------- #


def test_oversized_verified_input_creates_no_dispatch_row_and_fails_closed(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor,
               typed_input={"pad": "x" * dispatch.MAX_CLAIM_RESPONSE_BYTES})
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is None
    assert conn.execute("SELECT COUNT(*) AS n FROM workstation_job_dispatch WHERE job_id = 'job-1'").fetchone()["n"] == 0
    job = conn.execute("SELECT status, reason_code FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert job["status"] == "ERROR"
    assert job["reason_code"] == "INPUT_TOO_LARGE"


def test_excessive_depth_creates_no_dispatch_row_and_fails_closed(conn, encryptor):
    nested = {}
    cursor = nested
    for _ in range(dispatch.MAX_TYPED_INPUT_DEPTH + 5):
        cursor["next"] = {}
        cursor = cursor["next"]
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor, typed_input=nested)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is None
    assert conn.execute("SELECT COUNT(*) AS n FROM workstation_job_dispatch WHERE job_id = 'job-1'").fetchone()["n"] == 0
    job = conn.execute("SELECT status, reason_code FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert job["status"] == "ERROR"
    assert job["reason_code"] == "INPUT_TOO_DEEP"


def test_deeply_recursive_json_text_is_contained_not_a_crash(conn, encryptor):
    """The stored plaintext is malformed-but-decryptable raw JSON TEXT so
    deeply nested that json.loads() itself would exhaust Python's own
    recursion limit -- this must be a fixed, contained failure (never an
    uncaught RecursionError escaping claim_job)."""
    user, runner = _world(conn)
    raw = (b'{"a":' * 100_000) + b"1" + (b"}" * 100_000)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor, raw_payload=raw)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is None
    assert conn.execute("SELECT COUNT(*) AS n FROM workstation_job_dispatch WHERE job_id = 'job-1'").fetchone()["n"] == 0
    job = conn.execute("SELECT status, reason_code FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert job["status"] == "ERROR"
    assert job["reason_code"] == "INPUT_NOT_JSON"


def test_boundary_valid_depth_still_claims(conn, encryptor):
    nested = {}
    cursor = nested
    for _ in range(dispatch.MAX_TYPED_INPUT_DEPTH - 1):
        cursor["next"] = {}
        cursor = cursor["next"]
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor, typed_input=nested)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is not None
    assert envelope.typed_input == nested


def test_boundary_valid_size_at_exactly_the_byte_limit_still_claims(conn, encryptor, monkeypatch):
    """A full response envelope -- job_id, mode, account_id, workflow_name,
    input_hash, generation, claim_token, lease_expires_at, typed_input, and
    all JSON overhead -- landing EXACTLY on MAX_CLAIM_RESPONSE_BYTES must
    still dispatch (only STRICTLY over the limit refuses)."""
    fixed_token = dispatch.CLAIM_TOKEN_PREFIX + "x" * 43
    monkeypatch.setattr(dispatch, "new_claim_token", lambda: fixed_token)
    lease_expires_at = dispatch._iso(T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS))
    probe = dispatch.JobEnvelope(
        job_id="job-1", mode="DRY_RUN", account_id=OUJDA, workflow_name="RENOUVELLEMENT_CONTRAT",
        input_hash="h" * 64, generation=1, lease_expires_at=lease_expires_at,
        claim_token=fixed_token, typed_input={"pad": ""},
    )
    baseline_size = len(json.dumps(probe.to_response_dict()).encode("utf-8"))
    pad_needed = dispatch.MAX_CLAIM_RESPONSE_BYTES - baseline_size
    assert pad_needed > 0

    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor, typed_input={"pad": "x" * pad_needed})
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is not None
    actual_size = len(json.dumps(envelope.to_response_dict()).encode("utf-8"))
    assert actual_size == dispatch.MAX_CLAIM_RESPONSE_BYTES


def test_no_sensitive_marker_appears_in_the_fail_closed_job_row_on_oversized_input(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor,
               typed_input={"pad": "SENSITIVE-MARKER-" + "x" * dispatch.MAX_CLAIM_RESPONSE_BYTES})
    dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    job = conn.execute("SELECT * FROM automation_jobs WHERE job_id = 'job-1'").fetchone()
    assert "SENSITIVE-MARKER" not in " ".join(str(v) for v in tuple(job))


def test_a_real_server_produced_envelope_is_accepted_by_the_windows_client(conn, encryptor):
    """Cross-boundary integration check (test-only -- production code stays
    isolated per tests/app/workstation_runner/test_import_isolation.py): a
    server-produced JobEnvelope, serialized exactly as the API layer does,
    must be accepted by RegistryHttpClient.claim_job(), proving the two
    sides' shapes and bounds genuinely agree end-to-end."""
    from mcma.app.workstation_runner.http_client import RegistryHttpClient

    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, typed_input={"claim_id": "C-1"}, encryptor=encryptor)
    envelope = dispatch.claim_job(conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope is not None
    body = envelope.to_response_dict()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = RegistryHttpClient("https://central.example.local", transport=httpx.MockTransport(handler))
    result = client.claim_job("mcma_rs_" + "s" * 40)
    assert result.job_id == envelope.job_id
    assert result.claim_token == envelope.claim_token
    assert result.typed_input == envelope.typed_input


# --------------------------------------------------------------------- #
# Phase 1C-B -- server-owned DRY_RUN lifecycle: start_job / finish_job
# --------------------------------------------------------------------- #

REGISTRY = default_registry()


def _claim_valid(conn, encryptor, *, user, runner, job_id="job-1", typed_input=None):
    create_job(
        conn, job_id, account_id=OUJDA, user_id=user, workflow_name=VALID_WORKFLOW_NAME,
        typed_input=typed_input if typed_input is not None else VALID_TYPED_INPUT, encryptor=encryptor,
    )
    return dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
    )


def _start(conn, p, envelope, encryptor, *, now=T0):
    return dispatch.start_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        workflow_registry=REGISTRY, encryptor=encryptor, now=now,
    )


def test_start_moves_a_planned_dry_run_to_running_and_read_only_identity_check(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    result = _start(conn, p, envelope, encryptor)
    assert result["status"] == "RUNNING"
    assert result["job_status"] == "READ_ONLY_IDENTITY_CHECK"
    assert "plan_hash" in result and result["plan_hash"]
    row = conn.execute("SELECT status, started_at FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "RUNNING"
    assert row["started_at"] is not None
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "READ_ONLY_IDENTITY_CHECK"


def test_start_returns_the_same_plan_hash_a_local_rebuild_would_produce(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    result = _start(conn, p, envelope, encryptor)
    local_plan = REGISTRY.get(VALID_WORKFLOW_NAME)(parse_wexia(VALID_TYPED_INPUT))
    assert result["plan_hash"] == local_plan.provenance.plan_hash


def test_start_lands_needs_review_without_moving_to_running(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner, typed_input=NEEDS_REVIEW_TYPED_INPUT)
    p = principal(conn, runner)
    result = _start(conn, p, envelope, encryptor)
    assert result["status"] == "NEEDS_REVIEW"
    assert "plan_hash" not in result
    row = conn.execute("SELECT status, outcome_code, started_at FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "SUCCEEDED"
    assert row["outcome_code"] == "NEEDS_REVIEW_NO_BROWSER"
    assert row["started_at"] is None
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "NEEDS_REVIEW"


def test_start_fences_the_job_from_further_claims_before_returning(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    _start(conn, p, envelope, encryptor)
    # The job is now READ_ONLY_IDENTITY_CHECK, not QUEUED -- claim_job's own
    # candidate query cannot select it, with or without an active dispatch row.
    again = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert again is None


def test_two_concurrent_starts_for_the_same_claim_never_both_succeed(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    results = {}

    def _do(name):
        try:
            results[name] = _start(conn, p, envelope, encryptor)
        except UserInputError as exc:
            results[name] = exc

    t1 = threading.Thread(target=_do, args=("a",))
    t2 = threading.Thread(target=_do, args=("b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    successes = [v for v in results.values() if isinstance(v, dict)]
    failures = [v for v in results.values() if isinstance(v, UserInputError)]
    assert len(successes) == 1
    assert len(failures) == 1
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "RUNNING"


def test_start_requires_a_claimed_assignment_not_already_running(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    _start(conn, p, envelope, encryptor)
    with pytest.raises(UserInputError) as exc_info:
        _start(conn, p, envelope, encryptor)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_start_rejects_a_job_that_is_not_dry_run_queued(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE automation_jobs SET status = 'PLANNING' WHERE job_id = ?", (envelope.job_id,))
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _start(conn, p, envelope, encryptor)
    assert exc_info.value.code == "JOB_NOT_STARTABLE"


def test_execute_can_never_be_started_even_with_a_direct_claimed_row(conn, encryptor):
    """Defense in depth: EXECUTE can never even be CLAIMED (the dispatch
    gate), but start_job's own mode check is exercised directly here by
    seeding a CLAIMED row for an EXECUTE job as if the gate had somehow
    been bypassed."""
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, mode="EXECUTE", status="PLANNED",
               workflow_name=VALID_WORKFLOW_NAME, typed_input=VALID_TYPED_INPUT, encryptor=encryptor)
    claim_token = dispatch.new_claim_token()
    conn.execute(
        "INSERT INTO workstation_job_dispatch (assignment_id, job_id, runner_id, generation, claim_token_digest, "
        "status, claimed_at, lease_expires_at) VALUES ('a1', 'job-1', ?, 1, ?, 'CLAIMED', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:02:00+00:00')",
        (runner, dispatch.digest_token(claim_token)),
    )
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.start_job(conn, p, job_id="job-1", claim_token=claim_token, generation=1,
                            workflow_registry=REGISTRY, encryptor=encryptor, now=T0)
    assert exc_info.value.code == "JOB_NOT_STARTABLE"


def test_start_is_refused_immediately_once_the_runner_is_revoked(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE runners SET status = 'REVOKED', revoked_at = ? WHERE runner_id = ?", (dispatch._iso(T0), runner))
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _start(conn, p, envelope, encryptor)
    assert exc_info.value.status == 401


def test_start_is_refused_once_access_to_the_exact_claimed_account_is_removed(conn, encryptor):
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    revoke_access(conn, user, OUJDA)
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _start(conn, p, envelope, encryptor)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_start_is_refused_once_the_session_is_no_longer_ready(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    set_ready(conn, runner, OUJDA, state="ERROR")
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _start(conn, p, envelope, encryptor)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_start_fails_closed_on_unverifiable_input(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE automation_jobs SET input_hash = 'tampered' || input_hash WHERE job_id = ?", (envelope.job_id,))
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _start(conn, p, envelope, encryptor)
    assert exc_info.value.code == "JOB_NOT_STARTABLE"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "ERROR"
    # Dispatch correction (issue 3): the CLAIMED row must land on FAILED/
    # PLANNING_FAILED in the SAME transaction as the job's ERROR -- never
    # left CLAIMED (which would strand the assignment until lease expiry).
    row = conn.execute(
        "SELECT status, outcome_code, finished_at FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "FAILED"
    assert row["outcome_code"] == "PLANNING_FAILED"
    assert row["finished_at"] is not None


# --------------------------------------------------------------------- #
# Dispatch correction: plan-build failure must never strand an active
# claim on a job already landed on ERROR -- the CLAIMED->FAILED assignment
# transition commits atomically with the job's ERROR transition, in the
# SAME transaction, so the runner is immediately free for other work.
# --------------------------------------------------------------------- #


def test_plan_build_failure_frees_the_runner_for_another_job(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE automation_jobs SET input_hash = 'tampered' || input_hash WHERE job_id = ?", (envelope.job_id,))
    p = principal(conn, runner)
    with pytest.raises(UserInputError):
        _start(conn, p, envelope, encryptor)

    active = conn.execute(
        "SELECT 1 FROM workstation_job_dispatch WHERE runner_id = ? AND status IN ('CLAIMED', 'RUNNING')", (runner,)
    ).fetchone()
    assert active is None  # never stranded -- no active assignment remains

    create_job(conn, "job-2", account_id=OUJDA, user_id=user, workflow_name=VALID_WORKFLOW_NAME,
               typed_input=VALID_TYPED_INPUT, encryptor=encryptor, created_at="2026-01-01T00:05:00+00:00")
    envelope2 = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    assert envelope2 is not None
    assert envelope2.job_id == "job-2"  # the SAME runner can claim other work immediately, not after lease expiry


def test_plan_build_failure_transaction_rolls_back_both_halves_on_injected_crash(conn, encryptor, monkeypatch):
    """An injected failure between landing the job's ERROR and the
    dispatch row's FAILED write must roll back BOTH -- never leave ERROR
    committed alone with the assignment still CLAIMED."""
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE automation_jobs SET input_hash = 'tampered' || input_hash WHERE job_id = ?", (envelope.job_id,))
    p = principal(conn, runner)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash between the two writes")

    monkeypatch.setattr(dispatch, "fail_closed_on_runner_exception", _boom)
    with pytest.raises(RuntimeError):
        _start(conn, p, envelope, encryptor)

    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "QUEUED"  # rolled back -- never landed ERROR alone
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "CLAIMED"  # rolled back -- never landed FAILED alone


def test_stale_generation_cannot_close_a_newer_assignment_on_plan_failure(conn, encryptor):
    """If the claim this attempt started with is released and the job
    re-claimed under a NEW generation WHILE planning is under way, and the
    plan build then fails, the stale attempt's failure handling must
    refuse generically -- never touching the newer assignment or mutating
    the job out from under it."""
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    newer = {}

    def _release_and_reclaim_then_fail():
        dispatch.release_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
            reason_code="RUNNER_SHUTDOWN", now=T0,
        )
        newer["envelope"] = dispatch.claim_job(
            conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        )
        raise RuntimeError("simulated plan-build failure after a concurrent release+reclaim")

    with pytest.raises(UserInputError) as exc_info:
        _start_with_side_effect(conn, p, envelope, encryptor, _release_and_reclaim_then_fail)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"  # the STALE (generation 1) attempt, refused generically

    newer_envelope = newer["envelope"]
    assert newer_envelope is not None
    assert newer_envelope.generation == envelope.generation + 1
    newer_row = conn.execute(
        "SELECT generation, status FROM workstation_job_dispatch WHERE job_id = ? ORDER BY generation DESC LIMIT 1",
        (envelope.job_id,),
    ).fetchone()
    assert newer_row["generation"] == envelope.generation + 1
    assert newer_row["status"] == "CLAIMED"  # the newer assignment is completely untouched
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "QUEUED"  # never moved to ERROR by the stale attempt


# --------------------------------------------------------------------- #
# Dispatch correction (issue 2): start_job must use a genuinely fresh
# server time taken AFTER planning, never the entry-time value, for the
# second fencing pass, the final lease check, eligibility, and every
# timestamp it persists.
# --------------------------------------------------------------------- #


def test_start_uses_fresh_server_time_after_planning_a_lease_expiring_mid_plan_is_refused(conn, encryptor, monkeypatch):
    """Simulated via a monkeypatched dispatch.utcnow returning two distinct
    values -- the first (valid at entry) lets the up-front checks and
    planning proceed; the second (already past the lease deadline) proves
    the post-planning fencing pass genuinely re-evaluates against real
    elapsed time rather than reusing the stale entry-time value. Every
    OTHER test in this module injects `now=` explicitly and is unaffected
    by this change -- only the `now=None` (production) path ever calls
    dispatch.utcnow at all."""
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    t_entry = T0
    t_after_planning = T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS + 1)
    times = iter([t_entry, t_after_planning])
    monkeypatch.setattr(dispatch, "utcnow", lambda: next(times))

    with pytest.raises(UserInputError) as exc_info:
        dispatch.start_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
            workflow_registry=REGISTRY, encryptor=encryptor, now=None,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"

    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "EXPIRED"  # fenced by the post-planning pass -- never left dangling as CLAIMED
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "QUEUED"  # no browser admission -- never PLANNING/PLANNED/READ_ONLY_IDENTITY_CHECK


# --------------------------------------------------------------------- #
# finish_job
# --------------------------------------------------------------------- #


def _running(conn, encryptor, *, user, runner, job_id="job-1", typed_input=None):
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner, job_id=job_id, typed_input=typed_input)
    p = principal(conn, runner)
    _start(conn, p, envelope, encryptor)
    return envelope, p


def _finish(conn, p, envelope, result, *, now=T0):
    return dispatch.finish_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        result=result, now=now,
    )


def test_finish_identity_matched_lands_dry_run_verified_and_succeeded(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    result = _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert result["status"] == "SUCCEEDED"
    assert result["job_status"] == "DRY_RUN_VERIFIED"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "DRY_RUN_VERIFIED"
    row = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "SUCCEEDED"
    assert row["outcome_code"] == "IDENTITY_MATCHED"


@pytest.mark.parametrize("result", ["IDENTITY_NOT_MATCHED", "SESSION_UNAVAILABLE", "PORTAL_READ_FAILED", "RUNNER_CANCELLED"])
def test_finish_every_non_match_result_lands_identity_failed_and_failed(conn, encryptor, result):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    response = _finish(conn, p, envelope, result)
    assert response["status"] == "FAILED"
    assert response["job_status"] == "IDENTITY_FAILED"
    job = conn.execute("SELECT status, reason_code FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "IDENTITY_FAILED"
    assert job["reason_code"] == result
    row = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "FAILED"
    assert row["outcome_code"] == result


def test_finish_requires_running_not_merely_claimed(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_finish_rejects_an_arbitrary_result_value(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    with pytest.raises(UserInputError):
        _finish(conn, p, envelope, "SOMETHING_MADE_UP")
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "RUNNING"  # unaffected by the rejected attempt


def test_duplicate_identical_finish_is_idempotent(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    first = _finish(conn, p, envelope, "IDENTITY_MATCHED")
    second = _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert second == first


def test_conflicting_finish_is_refused_generically(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    _finish(conn, p, envelope, "IDENTITY_MATCHED")
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "IDENTITY_NOT_MATCHED")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    # the first outcome is untouched by the conflicting retry
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "DRY_RUN_VERIFIED"


def test_finish_is_refused_once_access_to_the_exact_claimed_account_is_removed(conn, encryptor):
    """P1 correction 4: Oujda and Nador both granted; the RUNNING claim is
    on Oujda; ONLY Oujda access is removed (Nador remains) -- the OLD
    "generally eligible" check alone would still pass (Nador keeps them
    >= 1 MCMA account); finish must recheck the job's own exact account."""
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    revoke_access(conn, user, OUJDA)
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


@pytest.mark.parametrize("new_state", ["LOGIN_REQUIRED", "ERROR"])
def test_finish_is_refused_once_the_exact_account_is_no_longer_ready(conn, encryptor, new_state):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    set_ready(conn, runner, OUJDA, state=new_state)
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_finish_is_refused_once_the_exact_account_capability_row_is_missing(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    conn.execute("DELETE FROM runner_account_capabilities WHERE runner_id = ? AND account_id = ?", (runner, OUJDA))
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_unrelated_nador_removal_does_not_block_a_valid_oujda_finish(conn, encryptor):
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    revoke_access(conn, user, NADOR)
    result = _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert result["status"] == "SUCCEEDED"


def test_finish_is_refused_once_the_runner_is_revoked(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE runners SET status = 'REVOKED', revoked_at = ? WHERE runner_id = ?", (dispatch._iso(T0), runner))
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "IDENTITY_MATCHED")
    assert exc_info.value.status == 401


def test_finish_is_refused_once_the_runner_is_offline(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    way_later = T0 + timedelta(hours=1)
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "IDENTITY_MATCHED", now=way_later)
    # expire_stale_assignments (called first, with the SAME server time)
    # will have already fenced this RUNNING assignment as LEASE_EXPIRED by
    # the time offline-ness would otherwise be checked -- either way, the
    # refusal is the same generic CLAIM_NOT_FOUND.
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_refused_finish_leaves_job_and_dispatch_completely_unchanged(conn, encryptor):
    """Except for LEGITIMATE server-side expiry fencing (exercised
    separately), a refused finish() must never mutate either table."""
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    revoke_access(conn, user, OUJDA)
    with pytest.raises(UserInputError):
        _finish(conn, p, envelope, "IDENTITY_MATCHED")
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "READ_ONLY_IDENTITY_CHECK"
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "RUNNING"


def test_a_wrong_runners_bearer_cannot_finish_this_job(conn, encryptor):
    user, runner = _world(conn)
    envelope, _p = _running(conn, encryptor, user=user, runner=runner)
    other_user = create_user(conn)
    other_runner = create_runner(conn, other_user)
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, principal(conn, other_runner), envelope, "IDENTITY_MATCHED")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_finish_is_atomic_job_status_and_dispatch_state_agree(conn, encryptor):
    """Never a terminal job with an active dispatch row, or a terminal
    dispatch row with a job still mid-check."""
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    _finish(conn, p, envelope, "IDENTITY_MATCHED")
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    dispatch_row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    job_is_terminal = job["status"] in ("DRY_RUN_VERIFIED", "IDENTITY_FAILED")
    dispatch_is_terminal = dispatch_row["status"] in ("SUCCEEDED", "FAILED")
    assert job_is_terminal == dispatch_is_terminal


def test_finish_error_bodies_and_state_contain_no_sensitive_marker(conn, encryptor):
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    with pytest.raises(UserInputError) as exc_info:
        _finish(conn, p, envelope, "SOMETHING_MADE_UP")
    assert envelope.claim_token not in str(exc_info.value)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.finish_job(conn, p, job_id=envelope.job_id, claim_token="mcma_ct_" + "z" * 40,
                             generation=envelope.generation, result="IDENTITY_MATCHED", now=T0)
    assert envelope.claim_token not in str(exc_info.value)


# --------------------------------------------------------------------- #
# P1 correction 2 -- start_job planning and dispatch admission are atomic:
# a state change occurring BETWEEN plan construction and final admission
# (revocation, exact-account removal, release, expiry) must never strand
# the job at PLANNING/PLANNED with no matching dispatch outcome.
# --------------------------------------------------------------------- #


class _SideEffectRegistry:
    """A workflow_registry stand-in whose builder performs a caller-given
    side effect (simulating a state change that happens WHILE start_job is
    mid-plan-construction) before returning the SAME real plan the genuine
    registry would have built. Lets these tests reproduce the exact race
    window deterministically, with no real threading."""

    def __init__(self, side_effect):
        self._side_effect = side_effect

    def get(self, name):
        real_builder = REGISTRY.get(name)

        def _build(typed_input):
            self._side_effect()
            return real_builder(typed_input)

        return _build


def _start_with_side_effect(conn, p, envelope, encryptor, side_effect, *, now=T0):
    return dispatch.start_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        workflow_registry=_SideEffectRegistry(side_effect), encryptor=encryptor, now=now,
    )


def _job_row(conn, job_id):
    return conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (job_id,)).fetchone()


def test_runner_revoked_during_planning_never_strands_the_job(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)

    def _revoke():
        conn.execute("UPDATE runners SET status = 'REVOKED', revoked_at = ? WHERE runner_id = ?", (dispatch._iso(T0), runner))

    with pytest.raises(UserInputError) as exc_info:
        _start_with_side_effect(conn, p, envelope, encryptor, _revoke)
    assert exc_info.value.status == 401
    assert _job_row(conn, envelope.job_id)["status"] == "QUEUED"  # never stranded at PLANNING/PLANNED


def test_exact_account_removed_during_planning_never_strands_the_job(conn, encryptor):
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)

    def _remove_oujda():
        revoke_access(conn, user, OUJDA)

    with pytest.raises(UserInputError) as exc_info:
        _start_with_side_effect(conn, p, envelope, encryptor, _remove_oujda)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    assert _job_row(conn, envelope.job_id)["status"] == "QUEUED"


def test_claim_released_during_planning_never_strands_the_job(conn, encryptor):
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)

    def _release():
        dispatch.release_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
            reason_code="RUNNER_SHUTDOWN", now=T0,
        )

    with pytest.raises(UserInputError) as exc_info:
        _start_with_side_effect(conn, p, envelope, encryptor, _release)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    assert _job_row(conn, envelope.job_id)["status"] == "QUEUED"


def test_claim_expiring_during_planning_never_strands_the_job(conn, encryptor):
    """The lease is comfortably valid when start_job BEGINS (its own
    up-front expire_stale_assignments pass sees a live claim) but is made
    to look expired -- relative to the SAME fixed `now` -- while planning
    is under way, proving the SECOND expiry-fencing pass (added by this
    correction, right after planning and before the final transaction)
    genuinely fences it rather than trusting the earlier, now-stale
    check."""
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    mid_lease = T0 + timedelta(seconds=60)  # well within the original 120s lease
    conn.execute("UPDATE runners SET last_seen_at = ? WHERE runner_id = ?", (dispatch._iso(mid_lease), runner))

    def _shrink_lease_to_already_expired():
        conn.execute(
            "UPDATE workstation_job_dispatch SET lease_expires_at = ? WHERE job_id = ?",
            (dispatch._iso(T0 + timedelta(seconds=30)), envelope.job_id),
        )

    with pytest.raises(UserInputError) as exc_info:
        _start_with_side_effect(conn, p, envelope, encryptor, _shrink_lease_to_already_expired, now=mid_lease)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    assert _job_row(conn, envelope.job_id)["status"] == "QUEUED"
    row = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "EXPIRED"
    assert row["outcome_code"] == "LEASE_EXPIRED"


def test_a_job_that_survives_planning_unaffected_still_starts_normally(conn, encryptor):
    """Positive control: with no interference, start_job succeeds exactly
    as before this correction."""
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    result = _start_with_side_effect(conn, p, envelope, encryptor, side_effect=lambda: None)
    assert result["status"] == "RUNNING"
    assert _job_row(conn, envelope.job_id)["status"] == "READ_ONLY_IDENTITY_CHECK"


def test_running_expiry_is_atomic_an_injected_failure_commits_neither_half(conn, encryptor, monkeypatch):
    """P1 correction 3: for a RUNNING expiry, the dispatch row's own
    EXPIRED write and the automation_jobs fail-closed transition must
    commit together, in ONE transaction. An injected failure between them
    (simulated by making fail_closed_on_runner_exception itself raise)
    must roll back EVERYTHING -- never leave dispatch=EXPIRED paired with
    a job still at READ_ONLY_IDENTITY_CHECK that no future scan could
    repair."""
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    conn.execute(
        "UPDATE workstation_job_dispatch SET lease_expires_at = ? WHERE job_id = ?",
        (dispatch._iso(T0), envelope.job_id),
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash between the two writes")

    monkeypatch.setattr(dispatch, "fail_closed_on_runner_exception", _boom)
    later = T0 + timedelta(seconds=1)
    with pytest.raises(RuntimeError):
        dispatch.expire_stale_assignments(conn, now=later)

    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "RUNNING"  # the dispatch-side write was rolled back too
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "READ_ONLY_IDENTITY_CHECK"


def test_repeated_expiry_scans_never_strand_an_inconsistent_row(conn, encryptor):
    """A 'restart' re-running expire_stale_assignments over an
    already-expired RUNNING assignment must be a safe no-op: no further
    mutation, no duplicate fail-closed transition, no exception."""
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    conn.execute(
        "UPDATE workstation_job_dispatch SET lease_expires_at = ? WHERE job_id = ?",
        (dispatch._iso(T0), envelope.job_id),
    )
    later = T0 + timedelta(seconds=1)

    count1 = dispatch.expire_stale_assignments(conn, now=later)
    assert count1 == 1
    row = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "EXPIRED" and row["outcome_code"] == "LEASE_EXPIRED"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"

    count2 = dispatch.expire_stale_assignments(conn, now=later + timedelta(seconds=1))
    assert count2 == 0
    row2 = conn.execute("SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert (row2["status"], row2["outcome_code"]) == (row["status"], row["outcome_code"])
    job2 = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job2["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"


def test_claimed_expiry_still_batches_without_touching_automation_jobs(conn, encryptor):
    """Unaffected by this correction: a CLAIMED (never-started) expiry
    still leaves the job untouched and safely re-claimable."""
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    way_later = T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS + 1)
    count = dispatch.expire_stale_assignments(conn, now=way_later)
    assert count == 1
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "QUEUED"


def test_running_expiry_does_not_defeat_a_concurrent_renewal(conn, encryptor):
    """Dispatch correction (issue 1): the per-assignment RUNNING-expiry
    UPDATE must re-check the lease deadline INSIDE its own transaction, not
    just trust the earlier, unlocked SELECT that discovered the candidate.
    A lease renewed in the window between that SELECT and this
    assignment's own conditional UPDATE (here, a renewal spliced in right
    after the SELECT runs, simulating a concurrent renew_job() landing in
    that exact window) must leave the row completely untouched -- neither
    the dispatch row nor its job may be expired."""
    user, runner = _world(conn)
    envelope, p = _running(conn, encryptor, user=user, runner=runner)
    conn.execute(
        "UPDATE workstation_job_dispatch SET lease_expires_at = ? WHERE job_id = ?",
        (dispatch._iso(T0), envelope.job_id),
    )
    later = T0 + timedelta(seconds=1)
    renewed_lease = later + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS)

    real_execute = conn.execute
    renewed = {"done": False}

    def _execute_with_race(sql, parameters=()):
        result = real_execute(sql, parameters)
        if not renewed["done"] and "WHERE status = 'RUNNING' AND lease_expires_at" in sql:
            # A concurrent renew_job() committing exactly between this scan
            # and the per-assignment UPDATE below.
            renewed["done"] = True
            real_execute(
                "UPDATE workstation_job_dispatch SET lease_expires_at = ?, last_renewed_at = ? WHERE job_id = ?",
                (dispatch._iso(renewed_lease), dispatch._iso(later), envelope.job_id),
            )
        return result

    conn.execute = _execute_with_race
    try:
        count = dispatch.expire_stale_assignments(conn, now=later)
    finally:
        conn.execute = real_execute

    assert count == 0
    row = conn.execute(
        "SELECT status, lease_expires_at FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "RUNNING"  # never expired -- the renewal fenced it
    assert row["lease_expires_at"] == dispatch._iso(renewed_lease)
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "READ_ONLY_IDENTITY_CHECK"  # untouched -- neither dispatch nor job expired


def test_a_rejected_start_after_planning_never_leaves_planning_or_planned(conn, encryptor):
    """Direct proof of the exact invariant: whatever REASON start_job
    refuses for, automation_jobs is never observed at PLANNING or PLANNED
    afterward -- only QUEUED (untouched) or, for a genuine plan-build
    failure, ERROR (truthfully landed)."""
    user, runner = _world(conn)
    envelope = _claim_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)

    def _revoke():
        conn.execute("UPDATE runners SET status = 'REVOKED', revoked_at = ? WHERE runner_id = ?", (dispatch._iso(T0), runner))

    with pytest.raises(UserInputError):
        _start_with_side_effect(conn, p, envelope, encryptor, _revoke)
    status = _job_row(conn, envelope.job_id)["status"]
    assert status not in ("PLANNING", "PLANNED")
