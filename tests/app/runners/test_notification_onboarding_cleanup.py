"""COMMIT failure, lease-release failure and idempotent tracker reconciliation
for the atomic onboarding completion. Deterministic injection only."""

import pytest

from dispatch_test_support import (  # noqa: F401
    MAMDA_NADOR, MAMDA_OUJDA, NADOR, OUJDA, conn, create_job, create_runner, create_user, db_path, encryptor,
    grant_access, principal, revoke_access, set_ready,
)
from test_notification_onboarding import (  # noqa: F401
    ALL, T0, World, at, claimed, code_of, complete, good_state, iso, renew, w,
)
from test_notification_onboarding_atomicity import (  # noqa: F401
    NEW, OLD, active_rows, active_value, assert_nothing_installed, interfere_after_staging, with_prior_session,
)
from mcma.app.auth.users import UserInputError
from mcma.app.runners import notification_onboarding as onb


class CommitFailingConnection:
    """Delegates to the real connection, but the COMMIT that closes the
    admission transaction (the one right after its audit INSERT) raises WITHOUT
    committing -- what a disk or lock error at commit time does."""

    def __init__(self, real):
        self._real = real
        self._last = ""
        self.armed = False
        self.fired = 0

    def execute(self, sql, *args, **kwargs):
        if self.armed and sql.strip().upper() == "COMMIT" and self._last.startswith("INSERT INTO audit_events"):
            self.armed = False
            self.fired += 1
            raise RuntimeError(f"disk I/O error {NEW}")
        self._last = sql.strip()
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_commit_failure_rolls_back_everything_and_the_same_claim_can_retry(w, monkeypatch):
    env = with_prior_session(w)
    failing = CommitFailingConnection(w.conn)
    w.svc._conn = failing
    interfere_after_staging(monkeypatch, lambda: setattr(failing, "armed", True))
    with pytest.raises(UserInputError) as err:
        complete(w, env, 14, state=good_state(NEW))
    assert failing.fired == 1
    assert err.value.code == "STORAGE_UNAVAILABLE" and NEW not in err.value.message
    assert_nothing_installed(w)                                   # old active + readable, staged AND final file gone
    assert w.conn.execute("SELECT status FROM notification_onboarding_requests WHERE generation=2").fetchone()[0] == "CLAIMED"
    w.conn.execute("BEGIN IMMEDIATE")                             # raises if the connection were still inside a transaction
    w.conn.execute("ROLLBACK")
    monkeypatch.undo()                                            # stop re-arming the injected commit failure
    complete(w, env, 15, state=good_state(NEW))                   # the same claim now completes
    assert active_value(w) == NEW and active_rows(w) == 1 and w.tracker.is_verified(OUJDA)


class ReleaseFailingLease:
    def __init__(self, real):
        self._real = real
        self.account_id = real.account_id
        self._fencing_token = real._fencing_token

    def release(self):
        self._real.release()                                      # really free it so the test DB stays usable
        raise RuntimeError(f"release exploded {NEW}")


def failing_release(monkeypatch):
    real = onb.acquire_lease
    monkeypatch.setattr(onb, "acquire_lease", lambda *a, **k: ReleaseFailingLease(real(*a, **k)))


def test_release_failure_after_an_admission_refusal_keeps_the_refusal_and_cleans_files(w, monkeypatch, caplog):
    env = with_prior_session(w)
    failing_release(monkeypatch)
    interfere_after_staging(monkeypatch, lambda: w.svc.cancel(w.user, OUJDA, now=at(13)))
    with pytest.raises(UserInputError) as err:
        complete(w, env, 14, state=good_state(NEW))
    assert err.value.code == "CLAIM_NOT_FOUND"                   # not replaced by the release error
    assert_nothing_installed(w)
    assert NEW not in caplog.text


def test_release_failure_after_an_activation_failure_keeps_the_storage_error_and_cleans_files(w, monkeypatch, caplog):
    env = with_prior_session(w)
    failing_release(monkeypatch)
    monkeypatch.setattr(onb, "_mark_succeeded", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(NEW)))
    with pytest.raises(UserInputError) as err:
        complete(w, env, 14, state=good_state(NEW))
    assert err.value.code == "STORAGE_UNAVAILABLE"
    assert_nothing_installed(w)
    assert NEW not in caplog.text


def test_release_failure_after_a_committed_success_does_not_turn_it_into_a_failure(w, monkeypatch, caplog):
    env = with_prior_session(w)
    failing_release(monkeypatch)
    response = complete(w, env, 14, state=good_state(NEW))
    assert response["status"] == "SUCCEEDED"
    row = w.conn.execute("SELECT status, outcome_code FROM notification_onboarding_requests WHERE generation=2").fetchone()
    assert (row["status"], row["outcome_code"]) == ("SUCCEEDED", "SESSION_STORED")
    assert active_value(w) == NEW and active_rows(w) == 1
    assert len(list(w.vault.iterdir())) == 1                      # old inactive file still cleaned up
    assert w.tracker.is_verified(OUJDA)                           # marked after the commit
    assert NEW not in caplog.text and "release exploded" not in caplog.text


def test_idempotent_retry_reconciles_the_tracker_without_touching_storage(w):
    env = claimed(w)
    complete(w, env, 5)
    w.tracker.forget(OUJDA)                                        # e.g. a restart, or a failure after the commit
    assert not w.tracker.is_verified(OUJDA)
    files = sorted(p.name for p in w.vault.iterdir())
    sessions = w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0]
    audits = w.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    assert complete(w, env, 6, state=good_state("OTHER"))["status"] == "SUCCEEDED"
    assert w.tracker.is_verified(OUJDA)
    assert sorted(p.name for p in w.vault.iterdir()) == files
    assert w.conn.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == sessions
    assert w.conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == audits
