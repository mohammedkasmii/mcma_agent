"""Notification-onboarding control plane (service level): durable request
state machine, runner fencing, vault completion. Synthetic data, fake clock,
no network, no browser."""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from dispatch_test_support import (  # noqa: F401
    MAMDA_NADOR, MAMDA_OUJDA, NADOR, OUJDA, conn, create_job, create_runner, create_user, db_path, encryptor,
    grant_access, principal, revoke_access, set_ready,
)
from mcma.app.auth.users import UserInputError
from mcma.app.connection_state import ConnectionStateTracker
from mcma.app.runners import notification_onboarding as onb
from mcma.app.runners import registry
from mcma.persistence.db import open_database
from mcma.persistence.leases import acquire_lease
from mcma.portal.vault import AesGcmSessionVaultBackend, TestOnlyAclVerifier, load_and_verify_session

ALL = (OUJDA, NADOR, MAMDA_OUJDA, MAMDA_NADOR)
T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
MARKER = "COOKIE-SECRET-MARKER-9f3a"


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def iso(moment: datetime) -> str:
    return moment.isoformat()


def good_state(value=MARKER):
    return {
        "cookies": [{"name": "sid", "value": value, "domain": "sinauto.mamda-mcma.ma", "path": "/", "expires": -1,
                     "httpOnly": True, "secure": True, "sameSite": "Lax"}],
        "origins": [],
    }


class World:
    def __init__(self, conn, tmp_path):
        self.conn = conn
        self.vault = tmp_path / "vault"
        self.vault.mkdir()
        self.tracker = ConnectionStateTracker()
        self.backend = AesGcmSessionVaultBackend(b"k" * 32)
        self.svc = self.service(conn)
        self.user = create_user(conn, role="operator")
        for account in ALL:
            grant_access(conn, self.user, account)
        self.runner = create_runner(conn, self.user, last_seen_at=iso(T0))
        self.principal = principal(conn, self.runner)

    def service(self, connection):
        return onb.NotificationOnboardingService(
            connection, vault_dir=self.vault, instance_id="central-test", crypto_backend=self.backend,
            acl_verifier=TestOnlyAclVerifier(True), portal_host="sinauto.mamda-mcma.ma", connection_tracker=self.tracker,
        )

    def beat(self, when=0):
        self.conn.execute("UPDATE runners SET last_seen_at = ? WHERE runner_id = ?", (iso(at(when)), self.runner))

    def request(self, account=OUJDA, when=0, user=None):
        return self.svc.request_login(user or self.user, account, now=at(when))

    def claim(self, when=1):
        return self.svc.claim(self.principal, protocol_version=1, app_version="0.1.0", now=at(when))

    def seed_job_assignment(self):
        create_job(self.conn, "job-x", account_id=OUJDA, user_id=self.user)
        self.conn.execute(
            "INSERT INTO workstation_job_dispatch (assignment_id, job_id, runner_id, generation, claim_token_digest, "
            "status, claimed_at, lease_expires_at) VALUES ('a1', 'job-x', ?, 1, ?, 'CLAIMED', ?, ?)",
            (self.runner, "e" * 64, iso(T0), iso(at(120))),
        )


@pytest.fixture()
def w(conn, tmp_path):
    return World(conn, tmp_path)


def code_of(call):
    with pytest.raises(UserInputError) as err:
        call()
    return err.value.code


# --------------------------------------------------------------------- #
# request creation (browser side)
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("account", ALL)
def test_all_four_notification_accounts_can_be_queued(w, account):
    view, created = w.request(account)
    assert created and view["state"] == "QUEUED" and view["account_id"] == account
    assert view["outcome_code"] is None and view["cancel_requested"] is False


def test_view_has_exactly_the_closed_keys(w):
    view, _ = w.request()
    assert set(view) == {"account_id", "request_id", "state", "outcome_code", "cancel_requested", "expires_at", "updated_at"}


def test_repeated_click_is_idempotent(w):
    first, created1 = w.request()
    second, created2 = w.request(when=5)
    assert created1 and not created2 and first["request_id"] == second["request_id"]
    assert w.conn.execute("SELECT COUNT(*) FROM notification_onboarding_requests").fetchone()[0] == 1


def test_other_employee_cannot_join_active_request(w):
    w.request()
    other = create_user(w.conn, role="operator")
    grant_access(w.conn, other, OUJDA)
    create_runner(w.conn, other, last_seen_at=iso(T0))
    assert code_of(lambda: w.request(user=other)) == "ONBOARDING_IN_PROGRESS"


def test_unknown_or_non_canonical_account_refused(w):
    assert code_of(lambda: w.request("acct-other")) == "ACCOUNT_NOT_ALLOWED"


def test_employee_without_exact_account_access_refused(w):
    revoke_access(w.conn, w.user, MAMDA_NADOR)
    assert code_of(lambda: w.request(MAMDA_NADOR)) == "ACCOUNT_NOT_ALLOWED"


def test_no_runner_refused(conn, tmp_path):
    world = World(conn, tmp_path)
    loner = create_user(conn, role="operator")
    grant_access(conn, loner, OUJDA)
    assert code_of(lambda: world.request(user=loner)) == "RUNNER_MISSING"


def test_viewer_has_no_runner_so_is_refused(w):
    viewer = create_user(w.conn, role="viewer")
    grant_access(w.conn, viewer, OUJDA)
    assert code_of(lambda: w.request(user=viewer)) == "RUNNER_MISSING"


def test_revoked_runner_refused(w):
    w.conn.execute("UPDATE runners SET status='REVOKED', revoked_at=? WHERE runner_id=?", (iso(T0), w.runner))
    assert code_of(lambda: w.request()) == "RUNNER_MISSING"


def test_offline_runner_refused_with_inclusive_boundary(w):
    limit = registry.OFFLINE_AFTER_SECONDS
    assert w.request(when=limit)[1] is True                       # exactly at the limit: still online
    w.svc.cancel(w.user, OUJDA, now=at(limit))
    assert code_of(lambda: w.request(NADOR, when=limit + 1)) == "RUNNER_OFFLINE"


def test_runner_busy_with_another_account_request(w):
    w.request(OUJDA)
    assert code_of(lambda: w.request(NADOR, when=1)) == "RUNNER_BUSY"


def test_runner_busy_with_a_job_assignment(w):
    w.seed_job_assignment()
    assert code_of(lambda: w.request(NADOR)) == "RUNNER_BUSY"


def test_unclaimed_request_expires_and_frees_the_account(w):
    view, _ = w.request()
    w.beat(onb.PENDING_TTL_SECONDS)
    again, created = w.request(when=onb.PENDING_TTL_SECONDS)       # <= semantics: expired exactly at the deadline
    assert created and again["request_id"] != view["request_id"]
    old = w.conn.execute("SELECT status, outcome_code FROM notification_onboarding_requests WHERE request_id=?",
                         (view["request_id"],)).fetchone()
    assert (old["status"], old["outcome_code"]) == ("EXPIRED", "REQUEST_EXPIRED")


def test_generation_increases_per_account(w):
    w.request()
    w.svc.cancel(w.user, OUJDA, now=at(1))
    w.request(when=2)
    gens = [r[0] for r in w.conn.execute("SELECT generation FROM notification_onboarding_requests ORDER BY generation")]
    assert gens == [1, 2]


# --------------------------------------------------------------------- #
# claim / renew
# --------------------------------------------------------------------- #


def test_claim_returns_token_once_and_stores_only_digest(w):
    view, _ = w.request()
    envelope = w.claim()
    assert set(envelope) == {"request_id", "account_id", "generation", "claim_token", "lease_expires_at", "expires_at",
                             "server_time"}
    assert envelope["request_id"] == view["request_id"] and envelope["account_id"] == OUJDA
    assert envelope["claim_token"].startswith("mcma_ot_")
    dump = str([tuple(r) for r in w.conn.execute("SELECT * FROM notification_onboarding_requests")])
    assert envelope["claim_token"] not in dump
    assert onb.digest_token(envelope["claim_token"]) in dump
    assert w.claim(2) is None


def test_claim_without_pending_request_is_none(w):
    assert w.claim() is None


def test_claim_only_by_the_owning_runner(w):
    w.request()
    other = create_user(w.conn, role="operator")
    grant_access(w.conn, other, OUJDA)
    other_runner = create_runner(w.conn, other, last_seen_at=iso(T0))
    assert w.svc.claim(principal(w.conn, other_runner), protocol_version=1, app_version="0.1.0", now=at(1)) is None


def test_claim_refused_for_offline_runner(w):
    w.request()
    assert w.claim(registry.OFFLINE_AFTER_SECONDS + 1) is None


def test_claim_deferred_while_runner_has_a_job(w):
    w.request()
    w.seed_job_assignment()
    assert w.claim() is None


def test_claim_after_pending_deadline_expires_instead(w):
    w.request()
    w.beat(onb.PENDING_TTL_SECONDS)
    assert w.claim(onb.PENDING_TTL_SECONDS) is None
    assert w.conn.execute("SELECT status FROM notification_onboarding_requests").fetchone()[0] == "EXPIRED"


def test_claim_rechecks_employee_access(w):
    w.request(MAMDA_OUJDA)
    revoke_access(w.conn, w.user, MAMDA_OUJDA)
    assert w.claim() is None
    row = w.conn.execute("SELECT status, outcome_code FROM notification_onboarding_requests").fetchone()
    assert (row["status"], row["outcome_code"]) == ("FAILED", "ACCESS_REVOKED")


def test_claim_rechecks_runner_still_eligible(w):
    w.request()
    w.conn.execute("UPDATE users SET role='viewer' WHERE user_id=?", (w.user,))
    assert w.claim() is None


def _race(w, db_path, action):
    results, barrier = [], threading.Barrier(4)

    def attempt():
        local = open_database(db_path)
        try:
            svc = w.service(local)
            barrier.wait()
            try:
                results.append(action(svc))
            except UserInputError as exc:
                results.append(exc.code)
        finally:
            local.close()

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


def test_concurrent_claims_on_separate_connections_yield_one_token(w, db_path):
    w.request()
    results = _race(w, db_path, lambda svc: svc.claim(w.principal, protocol_version=1, app_version="0.1.0", now=at(1)))
    assert len([r for r in results if isinstance(r, dict)]) == 1


def test_concurrent_double_click_creates_one_request(w, db_path):
    results = _race(w, db_path, lambda svc: svc.request_login(w.user, OUJDA, now=at(1)))
    assert w.conn.execute("SELECT COUNT(*) FROM notification_onboarding_requests").fetchone()[0] == 1
    assert sum(1 for r in results if isinstance(r, tuple) and r[1]) == 1


def claimed(w, account=OUJDA):
    w.request(account)
    return w.claim()


def renew(w, env, when, **override):
    args = dict(request_id=env["request_id"], claim_token=env["claim_token"], generation=env["generation"],
                phase="WAITING_FOR_LOGIN")
    args.update(override)
    return w.svc.renew(w.principal, now=at(when), **args)


def test_renew_extends_lease_and_reports_phase(w):
    env = claimed(w)
    w.beat(30)
    result = renew(w, env, 30, phase="WINDOW_OPENED")
    assert result["cancel_requested"] is False
    assert datetime.fromisoformat(result["lease_expires_at"]) == at(30 + onb.LEASE_TTL_SECONDS)
    assert w.svc.status(w.user, OUJDA, now=at(31))["state"] == "WINDOW_OPENED"
    renew(w, env, 31)
    assert w.svc.status(w.user, OUJDA, now=at(31))["state"] == "WAITING_FOR_LOGIN"


def test_lease_expiry_boundary_is_inclusive(w):
    env = claimed(w)
    boundary = 1 + onb.LEASE_TTL_SECONDS
    w.beat(boundary)
    assert code_of(lambda: renew(w, env, boundary)) == "CLAIM_NOT_FOUND"          # <= : expired exactly at the lease end
    assert w.svc.status(w.user, OUJDA, now=at(boundary))["outcome_code"] == "LEASE_EXPIRED"


def test_renew_just_before_expiry_still_works(w):
    env = claimed(w)
    when = onb.LEASE_TTL_SECONDS
    w.beat(when)
    renew(w, env, when)


def test_renew_is_capped_by_hard_request_expiry(w):
    env = claimed(w)
    for when in [*range(31, onb.LOGIN_WINDOW_SECONDS - 5, 30), onb.LOGIN_WINDOW_SECONDS - 5]:
        w.beat(when)
        result = renew(w, env, when)
    assert datetime.fromisoformat(result["lease_expires_at"]) <= datetime.fromisoformat(env["expires_at"])


def test_hard_request_expiry_ends_a_claimed_request(w):
    env = claimed(w)
    when = 1 + onb.LOGIN_WINDOW_SECONDS
    w.beat(when)
    assert code_of(lambda: renew(w, env, when)) == "CLAIM_NOT_FOUND"
    assert w.svc.status(w.user, OUJDA, now=at(when))["outcome_code"] in ("REQUEST_EXPIRED", "LEASE_EXPIRED")


@pytest.mark.parametrize("override", [{"claim_token": "mcma_ot_wrong"}, {"generation": 99}, {"request_id": "f" * 32}])
def test_renew_with_wrong_credentials_gets_one_answer(w, override):
    env = claimed(w)
    assert code_of(lambda: renew(w, env, 5, **override)) == "CLAIM_NOT_FOUND"


@pytest.mark.parametrize("phase", ["NOPE", None, 3])
def test_renew_phase_is_a_closed_enum(w, phase):
    env = claimed(w)
    assert code_of(lambda: renew(w, env, 5, phase=phase)) == "BAD_REQUEST"


def test_renew_by_another_runner_refused(w):
    env = claimed(w)
    other = create_user(w.conn, role="operator")
    grant_access(w.conn, other, OUJDA)
    other_runner = create_runner(w.conn, other, last_seen_at=iso(T0))
    with pytest.raises(UserInputError) as err:
        w.svc.renew(principal(w.conn, other_runner), request_id=env["request_id"], claim_token=env["claim_token"],
                    generation=env["generation"], phase="WINDOW_OPENED", now=at(5))
    assert err.value.code == "CLAIM_NOT_FOUND"


def test_stale_generation_cannot_touch_a_newer_request(w):
    old = claimed(w)
    later = onb.LEASE_TTL_SECONDS + 5
    w.beat(later)
    _, created = w.request(when=later)                           # old one expires; a new generation is queued
    assert created
    new_env = w.claim(later + 1)
    assert new_env["generation"] == old["generation"] + 1
    assert code_of(lambda: renew(w, old, later + 2)) == "CLAIM_NOT_FOUND"
    assert code_of(lambda: w.svc.fail(w.principal, request_id=old["request_id"], claim_token=old["claim_token"],
                                      generation=old["generation"], reason_code="INTERNAL_ERROR",
                                      now=at(later + 2))) == "CLAIM_NOT_FOUND"
    assert code_of(lambda: complete(w, old, later + 2)) == "CLAIM_NOT_FOUND"
    assert w.conn.execute("SELECT status FROM notification_onboarding_requests WHERE request_id=?",
                          (new_env["request_id"],)).fetchone()[0] == "CLAIMED"          # the new one is untouched


def test_renew_stops_when_access_revoked(w):
    env = claimed(w)
    revoke_access(w.conn, w.user, OUJDA)
    assert code_of(lambda: renew(w, env, 5)) == "CLAIM_NOT_FOUND"
    row = w.conn.execute("SELECT status, outcome_code FROM notification_onboarding_requests").fetchone()
    assert (row["status"], row["outcome_code"]) == ("FAILED", "ACCESS_REVOKED")


# --------------------------------------------------------------------- #
# complete
# --------------------------------------------------------------------- #


_DEFAULT = object()


def complete(w, env, when, state=_DEFAULT, **override):
    args = dict(request_id=env["request_id"], claim_token=env["claim_token"], generation=env["generation"],
                storage_state=good_state() if state is _DEFAULT else state)
    args.update(override)
    return w.svc.complete(w.principal, now=at(when), **args)


def test_complete_stores_encrypted_session_and_marks_connected(w):
    env = claimed(w)
    w.beat(10)
    assert complete(w, env, 10)["status"] == "SUCCEEDED"
    stored = json.loads(load_and_verify_session(w.conn, OUJDA, vault_dir=w.vault, backend=w.backend))
    assert stored["cookies"][0]["value"] == MARKER
    for path in w.vault.iterdir():
        assert MARKER.encode() not in path.read_bytes()
    assert w.tracker.is_verified(OUJDA)
    assert w.svc.status(w.user, OUJDA, now=at(11))["state"] == "SUCCEEDED"


@pytest.mark.parametrize("account", [MAMDA_OUJDA, MAMDA_NADOR, NADOR])
def test_complete_for_each_other_account(w, account):
    env = claimed(w, account)
    complete(w, env, 5)
    assert w.tracker.is_verified(account)
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions WHERE account_id=? AND status='ACTIVE'",
                          (account,)).fetchone()[0] == 1


def test_lost_response_retry_is_idempotent_and_stores_nothing_twice(w):
    env = claimed(w)
    first = complete(w, env, 10)
    second = complete(w, env, 12, state=good_state("DIFFERENT"))
    assert second["status"] == "SUCCEEDED" and first["status"] == "SUCCEEDED"
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 1
    stored = json.loads(load_and_verify_session(w.conn, OUJDA, vault_dir=w.vault, backend=w.backend))
    assert stored["cookies"][0]["value"] == MARKER
    assert len(list(w.vault.iterdir())) == 1


def test_complete_after_lease_expiry_is_refused_and_stores_nothing(w):
    env = claimed(w)
    boundary = 1 + onb.LEASE_TTL_SECONDS
    w.beat(boundary)
    assert code_of(lambda: complete(w, env, boundary)) == "CLAIM_NOT_FOUND"
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0


def test_complete_by_wrong_token_or_generation(w):
    env = claimed(w)
    assert code_of(lambda: complete(w, env, 5, claim_token="mcma_ot_nope")) == "CLAIM_NOT_FOUND"
    assert code_of(lambda: complete(w, env, 5, generation=env["generation"] + 1)) == "CLAIM_NOT_FOUND"


def test_complete_rechecks_access(w):
    env = claimed(w)
    revoke_access(w.conn, w.user, OUJDA)
    assert code_of(lambda: complete(w, env, 5)) == "CLAIM_NOT_FOUND"
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0


def test_complete_with_offline_runner_is_refused(w):
    env = claimed(w)
    assert code_of(lambda: complete(w, env, registry.OFFLINE_AFTER_SECONDS + 5)) == "CLAIM_NOT_FOUND"


@pytest.mark.parametrize("bad", [{"cookies": "x"}, {"cookies": [], "extra": 1}, [], None, {"cookies": [{"name": "a"}]}],
                         ids=["cookies-str", "extra-field", "list", "none", "short-cookie"])
def test_invalid_payload_fails_closed_and_is_not_stored(w, bad):
    env = claimed(w)
    assert code_of(lambda: complete(w, env, 5, state=bad)) == "SESSION_REJECTED"
    row = w.conn.execute("SELECT status, outcome_code FROM notification_onboarding_requests").fetchone()
    assert (row["status"], row["outcome_code"]) == ("FAILED", "UPLOAD_FAILED")
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0
    assert not list(w.vault.iterdir())


def test_account_lease_held_elsewhere_keeps_request_retryable(w):
    env = claimed(w)
    held = acquire_lease(w.conn, OUJDA, "poller", ttl_seconds=60)
    assert code_of(lambda: complete(w, env, 5)) == "ACCOUNT_BUSY"
    assert w.conn.execute("SELECT status FROM notification_onboarding_requests").fetchone()[0] == "CLAIMED"
    held.release()
    complete(w, env, 6)
    assert w.tracker.is_verified(OUJDA)


def test_vault_failure_is_reported_without_detail_and_lease_released(w):
    env = claimed(w)

    class Boom:
        def verify_restrictive(self, path):
            raise OSError(f"secret path {MARKER}")

    w.svc._acl_verifier = Boom()
    with pytest.raises(UserInputError) as err:
        complete(w, env, 5)
    assert err.value.code == "STORAGE_UNAVAILABLE" and MARKER not in err.value.message
    acquire_lease(w.conn, OUJDA, "poller", ttl_seconds=5).release()           # the lease was released


def test_cancel_requested_blocks_completion(w):
    env = claimed(w)
    w.svc.cancel(w.user, OUJDA, now=at(3))
    assert renew(w, env, 4)["cancel_requested"] is True
    assert code_of(lambda: complete(w, env, 5)) == "CLAIM_NOT_FOUND"
    row = w.conn.execute("SELECT status, outcome_code FROM notification_onboarding_requests").fetchone()
    assert (row["status"], row["outcome_code"]) == ("CANCELLED", "CANCELLED_BY_USER")
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 0


def test_no_session_marker_anywhere_in_database(w):
    env = claimed(w)
    complete(w, env, 5)
    tables = [r["name"] for r in w.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    dump = " ".join(str([tuple(r) for r in w.conn.execute(f"SELECT * FROM {t}")]) for t in tables)
    assert MARKER not in dump and env["claim_token"] not in dump


# --------------------------------------------------------------------- #
# fail / cancel
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("reason,status,outcome", [
    ("LOGIN_TIMED_OUT", "FAILED", "LOGIN_TIMED_OUT"), ("LOGIN_WINDOW_CLOSED", "FAILED", "LOGIN_WINDOW_CLOSED"),
    ("LOGIN_PAGE_UNREACHABLE", "FAILED", "LOGIN_PAGE_UNREACHABLE"), ("UPLOAD_FAILED", "FAILED", "UPLOAD_FAILED"),
    ("RUNNER_BUSY", "FAILED", "RUNNER_BUSY"), ("INTERNAL_ERROR", "FAILED", "INTERNAL_ERROR"),
    ("RUNNER_SHUTDOWN", "CANCELLED", "RUNNER_SHUTDOWN"), ("CANCELLED", "CANCELLED", "CANCELLED_BY_USER"),
])
def test_fail_maps_reason_and_is_idempotent(w, reason, status, outcome):
    env = claimed(w)
    args = dict(request_id=env["request_id"], claim_token=env["claim_token"], generation=env["generation"],
                reason_code=reason)
    assert w.svc.fail(w.principal, now=at(5), **args)["status"] == status
    assert w.svc.fail(w.principal, now=at(6), **args)["status"] == status        # lost-response retry
    row = w.conn.execute("SELECT status, outcome_code FROM notification_onboarding_requests").fetchone()
    assert (row["status"], row["outcome_code"]) == (status, outcome)
    assert w.request(when=7)[1] is True                                          # the account is free again


def test_fail_with_unknown_reason_refused(w):
    env = claimed(w)
    assert code_of(lambda: w.svc.fail(w.principal, request_id=env["request_id"], claim_token=env["claim_token"],
                                      generation=env["generation"], reason_code="ANYTHING", now=at(5))) == "BAD_REQUEST"


def test_fail_cannot_overwrite_a_different_terminal_outcome(w):
    env = claimed(w)
    args = dict(request_id=env["request_id"], claim_token=env["claim_token"], generation=env["generation"])
    complete(w, env, 5)
    assert code_of(lambda: w.svc.fail(w.principal, reason_code="INTERNAL_ERROR", now=at(6), **args)) == "CLAIM_NOT_FOUND"
    assert w.conn.execute("SELECT status FROM notification_onboarding_requests").fetchone()[0] == "SUCCEEDED"


def test_cancel_pending_is_immediate_and_idempotent(w):
    w.request()
    assert w.svc.cancel(w.user, OUJDA, now=at(1))["state"] == "CANCELLED"
    assert w.svc.cancel(w.user, OUJDA, now=at(2))["state"] == "CANCELLED"
    assert w.claim(3) is None


def test_cancel_claimed_sets_flag_only(w):
    claimed(w)
    view = w.svc.cancel(w.user, OUJDA, now=at(3))
    assert view["cancel_requested"] is True and view["state"] == "QUEUED"
    assert w.svc.cancel(w.user, OUJDA, now=at(4))["cancel_requested"] is True


def test_cancel_by_other_employee_changes_nothing(w):
    w.request()
    other = create_user(w.conn, role="operator")
    grant_access(w.conn, other, OUJDA)
    w.svc.cancel(other, OUJDA, now=at(1))
    assert w.svc.status(w.user, OUJDA, now=at(2))["state"] == "QUEUED"


def test_status_idle_when_nothing_requested(w):
    view = w.svc.status(w.user, OUJDA, now=at(0))
    assert view["state"] == "IDLE" and view["request_id"] is None


# --------------------------------------------------------------------- #
# invariants that must NOT move
# --------------------------------------------------------------------- #


def test_runner_account_ids_and_heartbeat_remain_mcma_only(w):
    assert registry.RUNNER_ACCOUNT_IDS == (OUJDA, NADOR)
    assert code_of(lambda: registry.heartbeat(w.conn, w.principal, protocol_version=1, app_version="0.1.0",
                                              sessions=[{"account_id": MAMDA_OUJDA, "state": "READY"}])) == "ACCOUNT_NOT_ALLOWED"


def test_no_agent_session_state_changes_for_mamda_request(w):
    claimed(w, MAMDA_OUJDA)
    assert w.conn.execute("SELECT COUNT(*) FROM runner_account_capabilities").fetchone()[0] == 0


def test_onboarding_module_has_no_browser_or_writer_imports():
    source = open(onb.__file__, encoding="utf-8").read()
    for banned in ("import playwright", "browser_supervisor", "mcma.portal.writer", "mcma.portal.browser",
                   "mcma.portal.mission", "workstation_execute"):
        assert banned not in source
