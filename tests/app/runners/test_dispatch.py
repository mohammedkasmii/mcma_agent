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
    create_runner, create_user, db_path, encryptor, grant_access, principal, real_plan_hash, revoke_access, set_ready,
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
# Correction (Phase 1C-C, finding 1): renew_job requires the job's exact
# account to remain READY for this runner.
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("new_state", ["LOGIN_REQUIRED", "ERROR"])
def test_renewal_is_refused_once_the_exact_account_is_no_longer_ready(conn, encryptor, new_state):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    set_ready(conn, runner, OUJDA, state=new_state)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_renewal_is_refused_once_the_exact_account_capability_row_is_missing(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    conn.execute("DELETE FROM runner_account_capabilities WHERE runner_id = ? AND account_id = ?", (runner, OUJDA))
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_unrelated_accounts_state_change_never_blocks_a_valid_renewal(conn, encryptor):
    """P1 correction 4's own reasoning, reused here: Oujda and Nador both
    READY; the claim is on Oujda; ONLY Nador's state changes -- renewal on
    Oujda must be unaffected."""
    user, runner = _world(conn, ready=(OUJDA, NADOR))
    grant_access(conn, user, NADOR)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    set_ready(conn, runner, NADOR, state="ERROR")
    later = T0 + timedelta(seconds=30)
    result = dispatch.renew_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=later,
    )
    assert result["lease_expires_at"] > envelope.lease_expires_at


def test_a_refused_renewal_never_extends_the_lease(conn, encryptor):
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    set_ready(conn, runner, OUJDA, state="LOGIN_REQUIRED")
    with pytest.raises(UserInputError):
        dispatch.renew_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
        )
    row = conn.execute(
        "SELECT lease_expires_at, last_renewed_at FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["lease_expires_at"] == envelope.lease_expires_at
    assert row["last_renewed_at"] is None


def test_a_refused_renewals_reason_is_never_distinguishable_from_any_other(conn, encryptor):
    """Never leaks WHY the renewal was refused (session state vs. wrong
    token vs. anything else) -- the same generic error every other
    refusal in this module gives."""
    user, runner = _world(conn)
    create_job(conn, "job-1", account_id=OUJDA, user_id=user, encryptor=encryptor)
    p = principal(conn, runner)
    envelope = dispatch.claim_job(conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0)
    set_ready(conn, runner, OUJDA, state="ERROR")
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    assert "LOGIN_REQUIRED" not in str(exc_info.value)
    assert "ERROR" not in str(exc_info.value)
    assert "READY" not in str(exc_info.value)


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


# --------------------------------------------------------------------- #
# Phase 1C-C, Pass 1 -- server-owned EXECUTE lifecycle. Explicitly enabled
# ONLY via dependency injection (execute_dispatch_enabled=True passed
# directly to claim_job/start_job/finish_job) -- see dispatch.
# EXECUTE_DISPATCH_ENABLED's own module comment: production never passes
# this. Every helper below mirrors the DRY_RUN helpers above exactly, one
# layer up for EXECUTE.
# --------------------------------------------------------------------- #


def _seed_execute_job(
    conn, encryptor, *, user, job_id="execute-1", parent_id="parent-dry-run-1",
    account_id=OUJDA, typed_input=None, plan_hash=None,
):
    """Seeds an approved DRY_RUN parent (DRY_RUN_VERIFIED) and its EXECUTE
    child (PLANNED, parent_job_id set, plan_hash pre-approved) directly --
    dispatch tests may seed jobs directly (this support module's own
    established convention), rather than going through the full
    create_execution API flow."""
    typed_input = typed_input if typed_input is not None else VALID_TYPED_INPUT
    plan_hash = plan_hash if plan_hash is not None else real_plan_hash(typed_input)
    create_job(
        conn, parent_id, account_id=account_id, user_id=user, mode="DRY_RUN", status="DRY_RUN_VERIFIED",
        workflow_name=VALID_WORKFLOW_NAME, typed_input=typed_input, encryptor=encryptor,
        created_at="2026-01-01T00:00:00+00:00",
    )
    create_job(
        conn, job_id, account_id=account_id, user_id=user, mode="EXECUTE", status="PLANNED",
        workflow_name=VALID_WORKFLOW_NAME, typed_input=typed_input, encryptor=encryptor,
        created_at="2026-01-01T00:01:00+00:00", parent_job_id=parent_id, plan_hash=plan_hash,
    )
    return job_id, parent_id


def _claim_execute_valid(conn, encryptor, *, user, runner, **kwargs):
    job_id, parent_id = _seed_execute_job(conn, encryptor, user=user, **kwargs)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        execute_dispatch_enabled=True,
    )
    assert envelope is not None and envelope.job_id == job_id
    return envelope, parent_id


def _start_execute(conn, p, envelope, encryptor, *, now=T0):
    return dispatch.start_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        workflow_registry=REGISTRY, encryptor=encryptor, now=now, execute_dispatch_enabled=True,
    )


def _running_execute(conn, encryptor, *, user, runner, **kwargs):
    envelope, parent_id = _claim_execute_valid(conn, encryptor, user=user, runner=runner, **kwargs)
    p = principal(conn, runner)
    _start_execute(conn, p, envelope, encryptor)
    return envelope, p, parent_id


def _finish_execute(conn, p, envelope, result, *, now=T0):
    return dispatch.finish_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        result=result, now=now, execute_dispatch_enabled=True,
    )


# ---- claim ------------------------------------------------------------ #


def test_execute_is_claimed_once_explicitly_enabled(conn, encryptor):
    user, runner = _world(conn)
    envelope, _parent = _claim_execute_valid(conn, encryptor, user=user, runner=runner)
    assert envelope.mode == "EXECUTE"


def test_execute_claim_still_respects_the_ready_state_requirement(conn, encryptor):
    """The EXECUTE gate never bypasses any EXISTING eligibility machinery
    -- MAMDA exclusion and the READY-state requirement are SHARED with
    DRY_RUN, not re-implemented for EXECUTE."""
    user, runner = _world(conn, ready=())  # never marked READY
    _seed_execute_job(conn, encryptor, user=user)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        execute_dispatch_enabled=True,
    )
    assert envelope is None


def test_execute_claim_still_excludes_mamda(conn, encryptor):
    user, runner = _world(conn)
    grant_access(conn, user, MAMDA_OUJDA)
    _seed_execute_job(conn, encryptor, user=user, account_id=MAMDA_OUJDA)
    envelope = dispatch.claim_job(
        conn, principal(conn, runner), protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0,
        execute_dispatch_enabled=True,
    )
    assert envelope is None


# ---- start -------------------------------------------------------------- #


def test_execute_start_moves_planned_to_running_and_identity_verifying(conn, encryptor):
    user, runner = _world(conn)
    envelope, _parent = _claim_execute_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    result = _start_execute(conn, p, envelope, encryptor)
    assert result["status"] == "RUNNING"
    assert result["job_status"] == "IDENTITY_VERIFYING"
    assert result["plan_hash"]
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "IDENTITY_VERIFYING"
    row = conn.execute(
        "SELECT status, started_at FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "RUNNING"
    assert row["started_at"] is not None


def test_execute_start_returns_the_same_plan_hash_a_local_rebuild_would_produce(conn, encryptor):
    user, runner = _world(conn)
    envelope, _parent = _claim_execute_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    result = _start_execute(conn, p, envelope, encryptor)
    local_plan = REGISTRY.get(VALID_WORKFLOW_NAME)(parse_wexia(VALID_TYPED_INPUT))
    assert result["plan_hash"] == local_plan.provenance.plan_hash


def test_execute_start_requires_parent_still_dry_run_verified(conn, encryptor):
    """Item 3: start_job re-verifies the parent DRY_RUN relationship AND its
    verified status fresh, right before admission -- never trusts that
    creation-time authorization alone is still true."""
    user, runner = _world(conn)
    envelope, parent_id = _claim_execute_valid(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE automation_jobs SET status = 'IDENTITY_FAILED' WHERE job_id = ?", (parent_id,))
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _start_execute(conn, p, envelope, encryptor)
    assert exc_info.value.code == "JOB_NOT_STARTABLE"
    assert _job_row(conn, envelope.job_id)["status"] == "PLANNED"  # never stranded


def test_execute_start_fails_closed_on_plan_hash_mismatch_against_retained_approval(conn, encryptor):
    """Item 3/4: start_job independently rebuilds the plan from the job's
    OWN retained input and compares it against the job's OWN already-
    approved plan_hash -- never trusts it, and never executed on a
    mismatch."""
    user, runner = _world(conn)
    envelope, _parent = _claim_execute_valid(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE automation_jobs SET plan_hash = 'tampered' WHERE job_id = ?", (envelope.job_id,))
    p = principal(conn, runner)
    with pytest.raises(UserInputError) as exc_info:
        _start_execute(conn, p, envelope, encryptor)
    assert exc_info.value.code == "JOB_NOT_STARTABLE"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "ERROR"
    row = conn.execute(
        "SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "FAILED"
    assert row["outcome_code"] == "PLANNING_FAILED"


def test_execute_start_never_drifts_into_a_dry_run_only_status(conn, encryptor):
    """A rejected EXECUTE start must never leave automation_jobs at
    PLANNING/QUEUED/READ_ONLY_IDENTITY_CHECK/NEEDS_REVIEW (the DRY_RUN-only
    in-flight statuses) -- only its own PLANNED (untouched) or ERROR."""
    user, runner = _world(conn)
    envelope, _parent = _claim_execute_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)

    def _revoke():
        conn.execute("UPDATE runners SET status = 'REVOKED', revoked_at = ? WHERE runner_id = ?", (dispatch._iso(T0), runner))

    with pytest.raises(UserInputError):
        dispatch.start_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
            workflow_registry=_SideEffectRegistry(_revoke), encryptor=encryptor, now=T0, execute_dispatch_enabled=True,
        )
    status = _job_row(conn, envelope.job_id)["status"]
    assert status not in ("PLANNING", "QUEUED", "READ_ONLY_IDENTITY_CHECK", "NEEDS_REVIEW")


# ---- finish -------------------------------------------------------------- #


def test_execute_finish_ready_for_human_review_chains_through_the_full_write_path(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    result = _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    assert result["status"] == "SUCCEEDED"
    assert result["job_status"] == "READY_FOR_HUMAN_REVIEW"
    job = conn.execute(
        "SELECT status, finished_at FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert job["status"] == "READY_FOR_HUMAN_REVIEW"
    assert job["finished_at"] is None  # F.8: not a terminal outcome -- the browser stays open
    row = conn.execute(
        "SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "SUCCEEDED"
    assert row["outcome_code"] == "READY_FOR_HUMAN_REVIEW"


@pytest.mark.parametrize("result,expected_reason", [
    ("IDENTITY_FAILED", None),
    ("SESSION_NOT_READY", "SESSION_NOT_READY"),
    ("INPUT_OR_PLAN_MISMATCH", "INPUT_OR_PLAN_MISMATCH"),
])
def test_execute_finish_pre_write_failures_land_identity_failed(conn, encryptor, result, expected_reason):
    """These three outcomes can only ever be reported BEFORE the injected
    write callable is invoked (mcma.app.workstation_runner.execute_executor
    never calls it until every pre-write check has passed) -- one hop,
    IDENTITY_VERIFYING -> IDENTITY_FAILED, never touching WRITING."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    response = _finish_execute(conn, p, envelope, result)
    assert response["status"] == "FAILED"
    assert response["job_status"] == "IDENTITY_FAILED"
    job = conn.execute(
        "SELECT status, reason_code FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert job["status"] == "IDENTITY_FAILED"
    assert job["reason_code"] == expected_reason
    row = conn.execute(
        "SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "FAILED"
    assert row["outcome_code"] == result


@pytest.mark.parametrize("result,expected_reason", [
    ("WRITE_ABORTED", None),
    ("RUNNER_CANCELLED", "RUNNER_CANCELLED"),
    ("INTERNAL_EXECUTION_ERROR", "INTERNAL_EXECUTION_ERROR"),
])
def test_execute_finish_post_write_failures_chain_through_writing_to_write_aborted(conn, encryptor, result, expected_reason):
    """Critical rule (item 6): once mutation may have begun (the executor
    invoked the injected write callable), interruption/cancellation/
    internal error must land on WRITE_ABORTED via the legal
    IDENTITY_VERIFIED -> WRITING chain -- never IDENTITY_FAILED, never back
    to PLANNED/QUEUED, and always with a mandatory finished_at."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    response = _finish_execute(conn, p, envelope, result)
    assert response["status"] == "FAILED"
    assert response["job_status"] == "WRITE_ABORTED"
    job = conn.execute(
        "SELECT status, reason_code, finished_at FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert job["status"] == "WRITE_ABORTED"
    assert job["reason_code"] == expected_reason
    assert job["finished_at"] is not None
    row = conn.execute(
        "SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "FAILED"
    assert row["outcome_code"] == result


def test_execute_finish_never_reachable_without_the_gate(conn, encryptor):
    """Defense in depth: even if a RUNNING EXECUTE assignment somehow
    exists, finish_job's own default parameter refuses to use the EXECUTE
    mapping unless execute_dispatch_enabled=True is explicitly passed --
    the DRY_RUN-only FINISH_RESULTS enum rejects every EXECUTE-only value."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.finish_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
            result="READY_FOR_HUMAN_REVIEW", now=T0,  # gate omitted -- defaults False
        )
    assert exc_info.value.code == "BAD_REQUEST"
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "RUNNING"  # unaffected


def test_execute_duplicate_identical_finish_is_idempotent(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    first = _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    second = _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    assert second == first


def test_execute_conflicting_finish_is_refused_generically(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    with pytest.raises(UserInputError) as exc_info:
        _finish_execute(conn, p, envelope, "WRITE_ABORTED")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "READY_FOR_HUMAN_REVIEW"  # the first outcome is untouched


def test_execute_idempotent_finish_disambiguates_from_the_dry_run_mapping_of_the_shared_result(conn, encryptor):
    """RUNNER_CANCELLED is a member of BOTH FINISH_RESULTS and
    EXECUTE_FINISH_RESULTS, with a DIFFERENT resulting job_status per mode
    -- the idempotent-retry lookup must key off the row's own job's mode,
    never guess the mapping from the shared result string alone."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    first = _finish_execute(conn, p, envelope, "RUNNER_CANCELLED")
    assert first["job_status"] == "WRITE_ABORTED"
    second = _finish_execute(conn, p, envelope, "RUNNER_CANCELLED")
    assert second == first


def test_execute_finish_ready_for_human_review_is_atomic_across_the_full_chain(conn, encryptor, monkeypatch):
    """Item 8: every hop of _finish_execute_transitions, plus the dispatch
    row's own terminal write, commits inside ONE transaction -- an injected
    failure partway through the chain (simulated here right before the
    VERIFYING hop, i.e. AFTER WRITING would have been recorded) must roll
    back EVERYTHING: never a job stranded mid-chain with the dispatch row
    already showing a terminal outcome, and never the reverse."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    real_transition = dispatch.transition
    calls = {"n": 0}

    def _boom_on_third_hop(conn_, job_id, new_status, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # IDENTITY_VERIFYING -> IDENTITY_VERIFIED -> WRITING -> [boom before VERIFYING]
            raise RuntimeError("simulated crash mid-chain")
        return real_transition(conn_, job_id, new_status, **kwargs)

    monkeypatch.setattr(dispatch, "transition", _boom_on_third_hop)
    with pytest.raises(RuntimeError):
        _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "IDENTITY_VERIFYING"  # rolled back entirely
    row = conn.execute("SELECT status FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert row["status"] == "RUNNING"  # rolled back entirely


def test_execute_finish_is_refused_once_the_runner_is_revoked(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    conn.execute("UPDATE runners SET status = 'REVOKED', revoked_at = ? WHERE runner_id = ?", (dispatch._iso(T0), runner))
    with pytest.raises(UserInputError) as exc_info:
        _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    assert exc_info.value.status == 401


def test_execute_finish_is_refused_once_access_to_the_exact_claimed_account_is_removed(conn, encryptor):
    user, runner = _world(conn)
    grant_access(conn, user, NADOR)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    revoke_access(conn, user, OUJDA)
    with pytest.raises(UserInputError) as exc_info:
        _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


@pytest.mark.parametrize("new_state", ["LOGIN_REQUIRED", "ERROR"])
def test_execute_finish_is_refused_once_the_exact_account_is_no_longer_ready(conn, encryptor, new_state):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    set_ready(conn, runner, OUJDA, state=new_state)
    with pytest.raises(UserInputError) as exc_info:
        _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW")
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


# ---- expiry / stale-generation fencing ----------------------------------- #


def test_execute_running_expiry_lands_interrupted_needs_human_review_never_requeued(conn, encryptor):
    """Critical rule (item 6) + restart-reconciliation parity: an EXECUTE
    lease lost while mutation may be underway (IDENTITY_VERIFYING is one of
    mcma.execution.jobs' own _WRITE_IN_PROGRESS_STATUSES) must fail closed
    to INTERRUPTED_NEEDS_HUMAN_REVIEW via the EXISTING fail_closed_on_
    runner_exception -- never back to PLANNED/QUEUED, and never silently
    reclaimable again."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    conn.execute(
        "UPDATE workstation_job_dispatch SET lease_expires_at = ? WHERE job_id = ?",
        (dispatch._iso(T0), envelope.job_id),
    )
    later = T0 + timedelta(seconds=1)
    count = dispatch.expire_stale_assignments(conn, now=later)
    assert count == 1
    row = conn.execute(
        "SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "EXPIRED"
    assert row["outcome_code"] == "LEASE_EXPIRED"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    again = dispatch.claim_job(
        conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=later, execute_dispatch_enabled=True,
    )
    assert again is None  # never reclaimable -- INTERRUPTED_NEEDS_HUMAN_REVIEW is not a dispatchable status


def test_a_stale_generation_cannot_affect_a_newer_execute_assignment(conn, encryptor):
    """Once a CLAIMED EXECUTE assignment is released and a fresh generation
    claims the SAME job again, the OLD envelope's token/generation must
    never be able to start the NEW assignment."""
    user, runner = _world(conn)
    envelope, _parent = _claim_execute_valid(conn, encryptor, user=user, runner=runner)
    p = principal(conn, runner)
    dispatch.release_job(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation,
        reason_code="RUNNER_SHUTDOWN", now=T0,
    )
    new_envelope = dispatch.claim_job(
        conn, p, protocol_version=1, app_version="1.0.0", encryptor=encryptor, now=T0, execute_dispatch_enabled=True,
    )
    assert new_envelope is not None
    assert new_envelope.generation > envelope.generation
    with pytest.raises(UserInputError) as exc_info:
        _start_execute(conn, p, envelope, encryptor)  # the STALE envelope
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


# ---- EXECUTE human-review browser-closed handoff (item 7) --------------- #


def _finish_ready_for_review(conn, p, envelope, *, now=T0):
    return _finish_execute(conn, p, envelope, "READY_FOR_HUMAN_REVIEW", now=now)


def test_browser_closed_moves_ready_for_review_to_awaiting_confirmation(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_ready_for_review(conn, p, envelope)
    result = dispatch.report_execute_review_browser_closed(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
    )
    assert result["status"] == "AWAITING_HUMAN_CONFIRMATION"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "AWAITING_HUMAN_CONFIRMATION"


def test_browser_closed_is_idempotent(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_ready_for_review(conn, p, envelope)
    first = dispatch.report_execute_review_browser_closed(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
    )
    second = dispatch.report_execute_review_browser_closed(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
    )
    assert second == first


def test_browser_closed_idempotent_after_the_employee_already_confirmed(conn, encryptor):
    """Calling this again after the SEPARATE, employee-authenticated
    review-completion API already reached HUMAN_CONFIRMED_COMPLETE is a
    no-op success, never an error and never a second transition attempt."""
    from mcma.execution.jobs import confirm_review_completed

    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_ready_for_review(conn, p, envelope)
    dispatch.report_execute_review_browser_closed(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
    )
    confirm_review_completed(conn, envelope.job_id, confirmed_by_user_id=user)
    result = dispatch.report_execute_review_browser_closed(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
    )
    assert result["status"] == "HUMAN_CONFIRMED_COMPLETE"


def test_browser_closed_rejects_a_wrong_claim_token(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_ready_for_review(conn, p, envelope)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.report_execute_review_browser_closed(
            conn, p, job_id=envelope.job_id, claim_token="mcma_ct_" + "z" * 40,
            generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_browser_closed_rejects_a_wrong_runners_bearer(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_ready_for_review(conn, p, envelope)
    other_user = create_user(conn)
    other_runner = create_runner(conn, other_user)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.report_execute_review_browser_closed(
            conn, principal(conn, other_runner), job_id=envelope.job_id, claim_token=envelope.claim_token,
            generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_browser_closed_refused_before_finish_has_reported_ready_for_review(conn, encryptor):
    """The dispatch row must already be terminal (SUCCEEDED); still RUNNING
    (never finished) is refused generically -- the same as every other
    fencing failure in this module."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    with pytest.raises(UserInputError) as exc_info:
        dispatch.report_execute_review_browser_closed(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_browser_closed_refused_when_the_finish_outcome_was_not_ready_for_review(conn, encryptor):
    """A terminal (FAILED) dispatch row exists, but its outcome was
    WRITE_ABORTED, never READY_FOR_HUMAN_REVIEW -- this event is never
    confused for that job's own, different outcome."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_execute(conn, p, envelope, "WRITE_ABORTED")
    with pytest.raises(UserInputError) as exc_info:
        dispatch.report_execute_review_browser_closed(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_browser_closed_never_reaches_human_confirmed_complete_by_itself(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_ready_for_review(conn, p, envelope)
    result = dispatch.report_execute_review_browser_closed(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
    )
    assert result["status"] != "HUMAN_CONFIRMED_COMPLETE"


def test_browser_closed_is_idempotent_after_an_employee_already_reported_a_problem(conn, encryptor):
    """Correction (Phase 1C-C, finding 5), the exact race/order regression:
    READY_FOR_HUMAN_REVIEW -> employee reports a problem (moving the job
    straight to INTERRUPTED_NEEDS_HUMAN_REVIEW, WITHOUT ever passing
    through AWAITING_HUMAN_CONFIRMATION) -> the browser then closes.
    report_execute_review_browser_closed() must answer idempotently with
    the job's current INTERRUPTED_NEEDS_HUMAN_REVIEW status, never
    CLAIM_NOT_FOUND, and must never itself have CREATED that status."""
    from mcma.execution.jobs import report_review_problem

    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    _finish_ready_for_review(conn, p, envelope)
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "READY_FOR_HUMAN_REVIEW"

    report_review_problem(conn, envelope.job_id, reported_by_user_id=user, reason_code="EMPLOYEE_REPORTED_PROBLEM")
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"  # produced by the employee path, NOT by browser-closed

    result = dispatch.report_execute_review_browser_closed(
        conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
    )
    assert result["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"  # unchanged -- browser-closed only recognized it


# --------------------------------------------------------------------- #
# Correction (Phase 1C-C, finding 4): LEASE_LOST is a first-class member
# of EXECUTE_FINISH_RESULTS, mapped like RUNNER_CANCELLED/INTERNAL_
# EXECUTION_ERROR to WRITE_ABORTED with its own distinct reason_code.
# --------------------------------------------------------------------- #


def test_execute_finish_lease_lost_lands_write_aborted(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    response = _finish_execute(conn, p, envelope, "LEASE_LOST")
    assert response["status"] == "FAILED"
    assert response["job_status"] == "WRITE_ABORTED"
    job = conn.execute(
        "SELECT status, reason_code, finished_at FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert job["status"] == "WRITE_ABORTED"
    assert job["reason_code"] == "LEASE_LOST"
    assert job["finished_at"] is not None
    row = conn.execute(
        "SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "FAILED"
    assert row["outcome_code"] == "LEASE_LOST"


def test_execute_finish_lease_lost_after_actual_expiry_is_rejected_expiry_recovery_stays_authoritative(conn, encryptor):
    """'A finish after actual expiry may be rejected; that is acceptable
    because expiry recovery remains authoritative' (finding 4). Once the
    server has ALREADY fenced the RUNNING assignment via
    expire_stale_assignments, a late-arriving finish(LEASE_LOST) is simply
    refused -- the job stays on the INTERRUPTED_NEEDS_HUMAN_REVIEW the
    expiry path already produced, never overwritten to WRITE_ABORTED."""
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    conn.execute(
        "UPDATE workstation_job_dispatch SET lease_expires_at = ? WHERE job_id = ?",
        (dispatch._iso(T0), envelope.job_id),
    )
    later = T0 + timedelta(seconds=1)
    dispatch.expire_stale_assignments(conn, now=later)
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"

    with pytest.raises(UserInputError) as exc_info:
        _finish_execute(conn, p, envelope, "LEASE_LOST", now=later)
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"  # untouched -- expiry recovery stays authoritative


# --------------------------------------------------------------------- #
# Correction (Phase 1C-C, finding 1), EXECUTE integration: a RUNNING
# EXECUTE assignment whose exact account drops out of READY is left to
# expire naturally (renewal refuses to extend it) and lands on
# INTERRUPTED_NEEDS_HUMAN_REVIEW via the EXISTING expiry-recovery path --
# never silently kept alive on a session that can no longer be trusted.
# --------------------------------------------------------------------- #


def test_execute_renewal_refused_once_not_ready_then_natural_expiry_lands_interrupted_needs_human_review(conn, encryptor):
    user, runner = _world(conn)
    envelope, p, _parent = _running_execute(conn, encryptor, user=user, runner=runner)
    set_ready(conn, runner, OUJDA, state="LOGIN_REQUIRED")
    with pytest.raises(UserInputError) as exc_info:
        dispatch.renew_job(
            conn, p, job_id=envelope.job_id, claim_token=envelope.claim_token, generation=envelope.generation, now=T0,
        )
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
    # The lease was never extended -- it now expires at its ORIGINAL
    # deadline, exactly like a runner that simply stopped renewing.
    way_later = T0 + timedelta(seconds=dispatch.DEFAULT_LEASE_TTL_SECONDS + 1)
    count = dispatch.expire_stale_assignments(conn, now=way_later)
    assert count == 1
    row = conn.execute(
        "SELECT status, outcome_code FROM workstation_job_dispatch WHERE job_id = ?", (envelope.job_id,)
    ).fetchone()
    assert row["status"] == "EXPIRED"
    assert row["outcome_code"] == "LEASE_EXPIRED"
    job = conn.execute("SELECT status FROM automation_jobs WHERE job_id = ?", (envelope.job_id,)).fetchone()
    assert job["status"] == "INTERRUPTED_NEEDS_HUMAN_REVIEW"
