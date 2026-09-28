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
    MAMDA_OUJDA, NADOR, OUJDA, conn, create_job, create_runner, create_user, db_path, encryptor, grant_access,
    principal, revoke_access, set_ready,
)
from mcma.app.auth.users import UserInputError
from mcma.app.runners import dispatch
from mcma.execution.inputs import TestOnlyPlaintextEncryptor

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
    ("EXECUTE", "PLANNED", True),
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
