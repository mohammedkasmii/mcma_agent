"""Atomic staged activation of an onboarding session, server/runner browser
exclusion in both directions, and the OPENING_WINDOW phase. Deterministic
failure injection: nothing here sleeps or races on wall-clock timing except
the explicit thread-barrier tests, which assert an invariant that must hold
for EVERY interleaving."""

import json
import threading

import pytest

from dispatch_test_support import (  # noqa: F401
    MAMDA_NADOR, MAMDA_OUJDA, NADOR, OUJDA, conn, create_job, create_runner, create_user, db_path, encryptor,
    grant_access, principal, revoke_access, set_ready,
)
from test_notification_onboarding import (  # noqa: F401
    ALL, T0, World, at, claimed, code_of, complete, good_state, iso, renew, w,
)
from mcma.app.auth.users import UserInputError
from mcma.app.runners import dispatch
from mcma.app.runners import notification_onboarding as onb
from mcma.persistence.db import open_database
from mcma.persistence.leases import acquire_lease
from mcma.portal.vault import load_and_verify_session

OLD = "OLD-SESSION-MARKER"
NEW = "NEW-SESSION-MARKER"


def active_value(w):
    raw = load_and_verify_session(w.conn, OUJDA, vault_dir=w.vault, backend=w.backend)
    return json.loads(raw)["cookies"][0]["value"]


def active_rows(w):
    return w.conn.execute("SELECT COUNT(*) FROM portal_sessions WHERE account_id=? AND status='ACTIVE'", (OUJDA,)).fetchone()[0]


def with_prior_session(w):
    """An already-active session (OLD) for OUJDA, then a fresh claimed request."""
    env = claimed(w)
    complete(w, env, 2, state=good_state(OLD))
    w.tracker.forget(OUJDA)
    w.beat(10)
    w.request(when=10)
    return w.claim(11)


def interfere_after_staging(monkeypatch, action):
    """Runs `action` immediately after the new session is staged and before
    final admission -- the exact race window the atomic switch must close."""
    real = onb.stage_session

    def staged_then_interfere(*args, **kwargs):
        result = real(*args, **kwargs)
        action()
        return result

    monkeypatch.setattr(onb, "stage_session", staged_then_interfere)


def assert_nothing_installed(w):
    assert active_value(w) == OLD and active_rows(w) == 1
    assert len(list(w.vault.iterdir())) == 1                       # only the old file: staged file discarded
    assert not w.tracker.is_verified(OUJDA)
    assert w.conn.execute("SELECT COUNT(*) FROM notification_onboarding_requests WHERE status='SUCCEEDED' AND generation=2"
                          ).fetchone()[0] == 0


@pytest.mark.parametrize("name,action", [
    ("cancel", lambda w: w.svc.cancel(w.user, OUJDA, now=at(13))),
    ("lease-expired", lambda w: w.conn.execute(
        "UPDATE notification_onboarding_requests SET lease_expires_at=? WHERE status='CLAIMED'", (iso(at(14)),))),
    ("hard-deadline", lambda w: w.conn.execute(
        "UPDATE notification_onboarding_requests SET expires_at=? WHERE status='CLAIMED'", (iso(at(14)),))),
    ("access-revoked", lambda w: revoke_access(w.conn, w.user, OUJDA)),
    ("runner-revoked", lambda w: w.conn.execute("UPDATE runners SET status='REVOKED', revoked_at=?", (iso(T0),))),
    ("runner-offline", lambda w: w.conn.execute("UPDATE runners SET last_seen_at=?", (iso(at(-3600)),))),
])
def test_race_just_before_admission_installs_nothing(w, monkeypatch, name, action):
    env = with_prior_session(w)
    interfere_after_staging(monkeypatch, lambda: action(w))
    with pytest.raises(UserInputError) as err:
        complete(w, env, 14)
    assert err.value.code == "CLAIM_NOT_FOUND"
    assert_nothing_installed(w)


def test_lease_lost_just_before_admission_installs_nothing(w, monkeypatch):
    env = with_prior_session(w)
    real = onb.acquire_lease

    def acquire_then_lose(conn, account_id, instance, **kw):
        handle = real(conn, account_id, instance, **kw)
        conn.execute("UPDATE account_leases SET fencing_token='someone-else' WHERE account_id=?", (account_id,))
        return handle

    monkeypatch.setattr(onb, "acquire_lease", acquire_then_lose)
    assert code_of(lambda: complete(w, env, 14)) == "ACCOUNT_BUSY"
    assert_nothing_installed(w)
    assert w.conn.execute("SELECT status FROM notification_onboarding_requests WHERE generation=2").fetchone()[0] == "CLAIMED"


def test_failure_after_portal_session_mutation_rolls_back_both(w, monkeypatch):
    env = with_prior_session(w)
    seen = {}
    real = onb._mark_succeeded

    def break_after_session_swap(conn, *args, **kwargs):
        seen["swapped"] = conn.execute("SELECT COUNT(*) FROM portal_sessions WHERE status='ACTIVE'").fetchone()[0]
        assert not w.tracker.is_verified(OUJDA)                     # tracker is not touched before the commit
        raise RuntimeError(f"disk full {NEW}")

    monkeypatch.setattr(onb, "_mark_succeeded", break_after_session_swap)
    with pytest.raises(UserInputError) as err:
        complete(w, env, 14, state=good_state(NEW))
    assert err.value.code == "STORAGE_UNAVAILABLE" and NEW not in err.value.message
    assert seen["swapped"] == 1                                     # the swap really had happened inside the txn
    assert_nothing_installed(w)
    assert w.conn.execute("SELECT status FROM notification_onboarding_requests WHERE generation=2").fetchone()[0] == "CLAIMED"
    monkeypatch.setattr(onb, "_mark_succeeded", real)
    acquire_lease(w.conn, OUJDA, "x", ttl_seconds=1).release()      # lease released on failure
    complete(w, env, 15, state=good_state(NEW))                      # and the SAME claim can still complete afterwards
    assert active_value(w) == NEW and active_rows(w) == 1


def test_audit_row_rolls_back_with_the_switch(w, monkeypatch):
    env = with_prior_session(w)
    monkeypatch.setattr(onb.NotificationOnboardingService, "_audit",
                        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    assert code_of(lambda: complete(w, env, 14)) == "STORAGE_UNAVAILABLE"
    assert_nothing_installed(w)


def test_tracker_marked_only_after_commit(w, monkeypatch):
    env = claimed(w)
    states = []
    real = onb._mark_succeeded
    monkeypatch.setattr(onb, "_mark_succeeded", lambda *a, **k: (states.append(w.tracker.is_verified(OUJDA)), real(*a, **k))[1])
    complete(w, env, 5)
    assert states == [False] and w.tracker.is_verified(OUJDA)


def test_success_replaces_prior_session_and_removes_old_file(w):
    env = with_prior_session(w)
    complete(w, env, 14, state=good_state(NEW))
    assert active_value(w) == NEW and active_rows(w) == 1
    assert len(list(w.vault.iterdir())) == 1
    assert w.tracker.is_verified(OUJDA)


def test_later_cancel_or_expiry_cannot_reverse_a_committed_success(w):
    env = claimed(w)
    complete(w, env, 5)
    w.svc.cancel(w.user, OUJDA, now=at(6))
    w.svc.expire_stale(at(100000))
    assert w.svc.status(w.user, OUJDA, now=at(100001))["state"] == "SUCCEEDED"
    assert active_rows(w) == 1 and active_value(w) == "COOKIE-SECRET-MARKER-9f3a"


def test_lost_response_retry_after_atomic_success_stores_nothing_twice(w):
    env = claimed(w)
    complete(w, env, 5)
    before = sorted(p.name for p in w.vault.iterdir())
    complete(w, env, 6, state=good_state("OTHER"))
    assert sorted(p.name for p in w.vault.iterdir()) == before and active_rows(w) == 1


def test_staging_failure_leaves_prior_session_and_no_staged_file(w, monkeypatch):
    env = with_prior_session(w)

    def boom(*a, **k):
        raise OSError(NEW)

    monkeypatch.setattr(onb, "stage_session", boom)
    assert code_of(lambda: complete(w, env, 14, state=good_state(NEW))) == "STORAGE_UNAVAILABLE"
    assert_nothing_installed(w)


# --------------------------------------------------------------------- #
# C: browser exclusion, both directions, decided inside write transactions
# --------------------------------------------------------------------- #


def seed_dispatchable_job(w, job_id="job-race"):
    set_ready(w.conn, w.runner, OUJDA)
    create_job(w.conn, job_id, account_id=OUJDA, user_id=w.user)


def claim_job(w, conn, encryptor, when=1):
    return dispatch.claim_job(conn, w.principal, protocol_version=1, app_version="0.1.0", encryptor=encryptor, now=at(when))


def test_pending_or_claimed_onboarding_blocks_job_claim(w, encryptor):
    seed_dispatchable_job(w)
    w.request()
    assert claim_job(w, w.conn, encryptor) is None                  # PENDING
    w.claim()
    assert claim_job(w, w.conn, encryptor, when=2) is None          # CLAIMED



def test_job_claim_proceeds_once_onboarding_is_terminal_or_stale(w, encryptor):
    seed_dispatchable_job(w)
    w.request()
    w.svc.cancel(w.user, OUJDA, now=at(1))
    assert claim_job(w, w.conn, encryptor, when=2) is not None


def test_stale_onboarding_row_does_not_block_a_job(w, encryptor):
    seed_dispatchable_job(w)
    w.request()                                                      # PENDING, hard deadline at T0+120
    w.beat(onb.PENDING_TTL_SECONDS)
    assert claim_job(w, w.conn, encryptor, when=onb.PENDING_TTL_SECONDS) is not None     # <= semantics


@pytest.mark.parametrize("round_", range(8))
def test_job_claim_and_onboarding_request_race_has_one_winner(w, db_path, encryptor, round_):
    seed_dispatchable_job(w, f"job-race-{round_}")
    barrier, results = threading.Barrier(2), {}

    def job_side():
        local = open_database(db_path)
        try:
            barrier.wait()
            results["job"] = claim_job(w, local, encryptor)
        finally:
            local.close()

    def onboarding_side():
        local = open_database(db_path)
        try:
            svc = w.service(local)
            barrier.wait()
            try:
                results["onb"] = svc.request_login(w.user, OUJDA, now=at(1))
            except UserInputError as exc:
                results["onb"] = exc.code
        finally:
            local.close()

    threads = [threading.Thread(target=job_side), threading.Thread(target=onboarding_side)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    jobs = w.conn.execute("SELECT COUNT(*) FROM workstation_job_dispatch WHERE status IN ('CLAIMED','RUNNING')").fetchone()[0]
    onboarding = w.conn.execute("SELECT COUNT(*) FROM notification_onboarding_requests WHERE status IN ('PENDING','CLAIMED')").fetchone()[0]
    assert jobs + onboarding == 1                                    # exactly one control plane owns the runner
    if jobs:
        assert results["onb"] == "RUNNER_BUSY"
    else:
        assert results["job"] is None


def test_onboarding_claim_and_job_claim_race_cannot_both_win(w, db_path, encryptor):
    """A PENDING request exists; the job claim must see it (inside its own
    transaction) no matter how the claim interleaves."""
    seed_dispatchable_job(w)
    w.request()
    barrier, results = threading.Barrier(2), {}

    def job_side():
        local = open_database(db_path)
        try:
            barrier.wait()
            results["job"] = claim_job(w, local, encryptor)
        finally:
            local.close()

    def onboarding_side():
        local = open_database(db_path)
        try:
            svc = w.service(local)
            barrier.wait()
            results["onb"] = svc.claim(w.principal, protocol_version=1, app_version="0.1.0", now=at(1))
        finally:
            local.close()

    threads = [threading.Thread(target=job_side), threading.Thread(target=onboarding_side)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results["job"] is None and results["onb"] is not None


# --------------------------------------------------------------------- #
# D (server side): OPENING_WINDOW and the deadline budget
# --------------------------------------------------------------------- #


def test_opening_window_phase_is_accepted_right_after_claim_and_reported(w):
    env = claimed(w)
    assert renew(w, env, 2, phase="OPENING_WINDOW")["cancel_requested"] is False
    assert w.svc.status(w.user, OUJDA, now=at(3))["state"] == "OPENING_WINDOW"
    renew(w, env, 3, phase="WINDOW_OPENED")
    assert w.svc.status(w.user, OUJDA, now=at(4))["state"] == "WINDOW_OPENED"


def test_hard_deadline_budget_covers_startup_login_and_upload(w):
    env = claimed(w)
    assert onb.LOGIN_WINDOW_SECONDS == 420
    assert onb.STARTUP_RESERVE_SECONDS + onb.LOGIN_TIMEOUT_SECONDS + onb.UPLOAD_RESERVE_SECONDS == onb.LOGIN_WINDOW_SECONDS
    from datetime import datetime
    assert (datetime.fromisoformat(env["expires_at"]) - datetime.fromisoformat(env["server_time"])).total_seconds() == 420


def test_cancel_seen_during_opening_prevents_activation(w):
    env = claimed(w)
    renew(w, env, 2, phase="OPENING_WINDOW")
    w.svc.cancel(w.user, OUJDA, now=at(3))
    assert renew(w, env, 4, phase="OPENING_WINDOW")["cancel_requested"] is True
    assert code_of(lambda: complete(w, env, 5)) == "CLAIM_NOT_FOUND"
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0


def test_renewals_through_a_long_startup_keep_the_claim_alive_and_expiry_still_fences(w):
    env = claimed(w)
    for when in range(31, 200, 30):                                  # 170 s of slow startup > two lease TTLs
        w.beat(when)
        renew(w, env, when, phase="OPENING_WINDOW")
    w.beat(300)
    assert code_of(lambda: renew(w, env, 300, phase="OPENING_WINDOW")) == "CLAIM_NOT_FOUND"      # lapsed lease: fenced
    assert code_of(lambda: complete(w, env, 300)) == "CLAIM_NOT_FOUND"
