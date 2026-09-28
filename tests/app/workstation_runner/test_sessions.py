import pytest

from mcma.app.workstation_runner.sessions import (
    AccountState, ProbeOutcome, VerificationScheduler, WorkstationSessionManager,
)
from tests.app.workstation_runner._fakes import FakeClock

OUJDA = "acct-mcma-oujda"
NADOR = "acct-mcma-nador"


def _manager(saved=()):
    saved = set(saved)
    return WorkstationSessionManager(has_saved_session=lambda account_id: account_id in saved)


# --------------------------------------------------------------------- #
# reconciliation / bootstrap
# --------------------------------------------------------------------- #


def test_no_tracked_accounts_before_the_first_reconciliation_means_empty_heartbeat():
    manager = _manager()
    assert manager.heartbeat_sessions() == ()
    assert manager.snapshot() == ()


def test_reconcile_with_no_saved_session_yields_not_configured():
    manager = _manager()
    result = manager.reconcile_allowed_accounts((OUJDA,))
    assert manager.state_of(OUJDA) is AccountState.NOT_CONFIGURED
    assert result.added_needing_verification == ()


def test_reconcile_with_a_saved_session_yields_pending_verification_never_ready():
    manager = _manager(saved=(OUJDA,))
    result = manager.reconcile_allowed_accounts((OUJDA,))
    assert manager.state_of(OUJDA) is AccountState.PENDING_VERIFICATION
    assert result.added_needing_verification == (OUJDA,)
    # PENDING_VERIFICATION must never be reported as READY (or at all) on the wire
    assert manager.heartbeat_sessions() == ()


def test_account_removal_purges_it_from_tracking_and_reports_it_in_removed():
    manager = _manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA, NADOR))
    result = manager.reconcile_allowed_accounts((NADOR,))
    assert result.removed == (OUJDA,)
    assert manager.is_authorized(OUJDA) is False
    assert manager.is_authorized(NADOR) is True


def test_reconcile_is_idempotent_for_an_unchanged_allowed_set():
    manager = _manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA,))
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)
    result = manager.reconcile_allowed_accounts((OUJDA,))
    assert result.removed == ()
    assert result.added_needing_verification == ()
    assert manager.state_of(OUJDA) is AccountState.READY  # unaffected by a no-op reconcile


def test_reconcile_ignores_accounts_outside_the_fixed_workstation_set():
    manager = _manager()
    manager.reconcile_allowed_accounts((OUJDA, "acct-mamda-oujda", "unknown"))
    assert manager.tracked_account_ids() == (OUJDA,)


def test_reconcile_deduplicates_repeated_allowed_account_ids():
    """The server sending the same account_id twice in one heartbeat
    response must not enqueue two VERIFY commands for it."""
    manager = _manager(saved=(OUJDA,))
    result = manager.reconcile_allowed_accounts((OUJDA, OUJDA, NADOR, NADOR))
    assert manager.tracked_account_ids() == (OUJDA, NADOR)
    assert result.added_needing_verification == (OUJDA,)


def test_reconcile_preserves_the_servers_given_order_for_newly_added_accounts():
    manager = _manager()
    manager.reconcile_allowed_accounts((NADOR, OUJDA))
    assert manager.tracked_account_ids() == (NADOR, OUJDA)


def test_stale_probe_after_removal_does_not_restore_the_account():
    manager = _manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA,))
    manager.reconcile_allowed_accounts(())  # OUJDA removed
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)
    assert manager.is_authorized(OUJDA) is False
    assert manager.state_of(OUJDA) is None


# --------------------------------------------------------------------- #
# probe outcomes -> state transitions
# --------------------------------------------------------------------- #


def test_authenticated_probe_sets_ready():
    manager = _manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA,))
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)
    assert manager.state_of(OUJDA) is AccountState.READY
    assert manager.heartbeat_sessions() == ({"account_id": OUJDA, "state": "READY"},)


def test_logged_out_probe_sets_login_required():
    manager = _manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA,))
    manager.record_probe_outcome(OUJDA, ProbeOutcome.LOGGED_OUT)
    assert manager.state_of(OUJDA) is AccountState.LOGIN_REQUIRED
    assert manager.heartbeat_sessions() == ({"account_id": OUJDA, "state": "LOGIN_REQUIRED"},)


@pytest.mark.parametrize("outcome", [ProbeOutcome.INDETERMINATE, ProbeOutcome.ERROR])
def test_indeterminate_or_error_probe_sets_error_state(outcome):
    manager = _manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA,))
    manager.record_probe_outcome(OUJDA, outcome)
    assert manager.state_of(OUJDA) is AccountState.ERROR
    assert manager.heartbeat_sessions() == ({"account_id": OUJDA, "state": "ERROR"},)


def test_probe_outcome_for_an_unauthorized_account_is_ignored():
    manager = _manager()
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)
    assert manager.state_of(OUJDA) is None


# --------------------------------------------------------------------- #
# record_* transition methods return True iff actually applied -- the
# caller (browser_worker.py) gates its update callback on this return
# value instead of a separate, racy, earlier is_authorized() check.
# --------------------------------------------------------------------- #


def test_record_probe_outcome_returns_true_when_applied_false_when_not():
    manager = _manager(saved=(OUJDA,))
    manager.reconcile_allowed_accounts((OUJDA,))
    assert manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED) is True
    assert manager.record_probe_outcome(NADOR, ProbeOutcome.AUTHENTICATED) is False


def test_record_login_success_returns_true_when_applied_false_when_not():
    manager = _manager()
    manager.reconcile_allowed_accounts((OUJDA,))
    assert manager.record_login_success(OUJDA) is True
    assert manager.record_login_success(NADOR) is False


def test_record_operation_error_returns_true_when_applied_false_when_not():
    manager = _manager()
    manager.reconcile_allowed_accounts((OUJDA,))
    assert manager.record_operation_error(OUJDA) is True
    assert manager.record_operation_error(NADOR) is False


def test_record_missing_saved_session_returns_true_when_applied_false_when_not():
    manager = _manager()
    manager.reconcile_allowed_accounts((OUJDA,))
    assert manager.record_missing_saved_session(OUJDA) is True
    assert manager.record_missing_saved_session(NADOR) is False


def test_record_login_success_sets_ready_only_if_still_authorized():
    manager = _manager()
    manager.reconcile_allowed_accounts((OUJDA,))
    manager.record_login_success(OUJDA)
    assert manager.state_of(OUJDA) is AccountState.READY
    manager.reconcile_allowed_accounts(())  # revoked before the login result lands
    manager.record_login_success(OUJDA)
    assert manager.state_of(OUJDA) is None


def test_oujda_and_nador_states_are_fully_independent():
    manager = _manager()
    manager.reconcile_allowed_accounts((OUJDA, NADOR))
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)
    manager.record_probe_outcome(NADOR, ProbeOutcome.LOGGED_OUT)
    assert manager.state_of(OUJDA) is AccountState.READY
    assert manager.state_of(NADOR) is AccountState.LOGIN_REQUIRED


def test_reset_clears_every_tracked_account():
    manager = _manager()
    manager.reconcile_allowed_accounts((OUJDA, NADOR))
    manager.record_probe_outcome(OUJDA, ProbeOutcome.AUTHENTICATED)
    manager.reset()
    assert manager.snapshot() == ()
    assert manager.heartbeat_sessions() == ()
    assert manager.is_authorized(OUJDA) is False


# --------------------------------------------------------------------- #
# VerificationScheduler -- testable without real waiting
# --------------------------------------------------------------------- #


def test_account_never_verified_is_immediately_due():
    scheduler = VerificationScheduler(clock=FakeClock())
    assert scheduler.due_accounts((OUJDA, NADOR)) == (OUJDA, NADOR)


def test_marking_verified_makes_it_not_due_until_the_interval_elapses():
    clock = FakeClock()
    scheduler = VerificationScheduler(interval_seconds=300.0, clock=clock)
    scheduler.mark_verified(OUJDA)
    assert scheduler.due_accounts((OUJDA,)) == ()
    clock.advance(299.0)
    assert scheduler.due_accounts((OUJDA,)) == ()
    clock.advance(1.0)
    assert scheduler.due_accounts((OUJDA,)) == (OUJDA,)


def test_scheduler_tracks_accounts_independently():
    clock = FakeClock()
    scheduler = VerificationScheduler(interval_seconds=300.0, clock=clock)
    scheduler.mark_verified(OUJDA)
    clock.advance(100.0)
    scheduler.mark_verified(NADOR)
    clock.advance(250.0)  # oujda: 350s ago (due); nador: 250s ago (not due)
    assert scheduler.due_accounts((OUJDA, NADOR)) == (OUJDA,)


def test_forget_makes_an_account_immediately_due_again():
    clock = FakeClock()
    scheduler = VerificationScheduler(interval_seconds=300.0, clock=clock)
    scheduler.mark_verified(OUJDA)
    scheduler.forget(OUJDA)
    assert scheduler.due_accounts((OUJDA,)) == (OUJDA,)


@pytest.mark.parametrize("bad_interval", [0, -1.0, float("nan"), float("inf"), float("-inf"), True, "300"])
def test_scheduler_rejects_a_non_finite_or_non_positive_interval(bad_interval):
    with pytest.raises(ValueError):
        VerificationScheduler(interval_seconds=bad_interval)
