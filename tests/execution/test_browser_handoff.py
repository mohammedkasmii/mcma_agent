"""Correction batch (owner amendment) -- the in-memory active-review-
session registry: no second form job may concurrently use the same
shared portal account; the close callback drives the caller's own
transition (mcma.execution.jobs.transition_on_browser_closed in real
wiring); no Playwright object is ever serialized here (a bare fake
handle is enough -- this module doesn't know what a real one looks like)."""

import pytest

from mcma.execution.browser_handoff import ActiveReviewRegistry, DuplicateActiveReview


class FakeHandle:
    def __init__(self):
        self._on_close = None

    def register_close_callback(self, on_close):
        self._on_close = on_close

    def simulate_close(self):
        assert self._on_close is not None
        self._on_close()


def test_register_and_get():
    registry = ActiveReviewRegistry()
    handle = FakeHandle()
    registry.register("job-1", "acct-1", handle, on_close=lambda job_id: None)
    assert registry.get("job-1") is handle
    assert registry.is_account_active("acct-1") is True


def test_second_job_for_same_account_is_rejected_while_first_is_active():
    registry = ActiveReviewRegistry()
    registry.register("job-1", "acct-1", FakeHandle(), on_close=lambda job_id: None)
    with pytest.raises(DuplicateActiveReview):
        registry.register("job-2", "acct-1", FakeHandle(), on_close=lambda job_id: None)


def test_a_different_account_is_unaffected():
    registry = ActiveReviewRegistry()
    registry.register("job-1", "acct-1", FakeHandle(), on_close=lambda job_id: None)
    registry.register("job-2", "acct-2", FakeHandle(), on_close=lambda job_id: None)  # no raise
    assert registry.active_job_count() == 2


def test_close_callback_unregisters_and_invokes_on_close():
    registry = ActiveReviewRegistry()
    handle = FakeHandle()
    closed_job_ids = []
    registry.register("job-1", "acct-1", handle, on_close=lambda job_id: closed_job_ids.append(job_id))

    handle.simulate_close()

    assert closed_job_ids == ["job-1"]
    assert registry.get("job-1") is None
    assert registry.is_account_active("acct-1") is False


def test_after_close_a_new_job_for_the_same_account_can_register():
    registry = ActiveReviewRegistry()
    handle = FakeHandle()
    registry.register("job-1", "acct-1", handle, on_close=lambda job_id: None)
    handle.simulate_close()
    registry.register("job-2", "acct-1", FakeHandle(), on_close=lambda job_id: None)  # no raise
    assert registry.is_account_active("acct-1") is True


def test_unregister_is_idempotent_and_safe_for_unknown_job_id():
    registry = ActiveReviewRegistry()
    registry.unregister("no-such-job")  # never raises
    assert registry.active_job_count() == 0


def test_no_real_playwright_object_is_required_a_bare_fake_suffices():
    """This module is deliberately capability-agnostic -- proven here by
    the fact that every test in this file uses only FakeHandle, never
    anything from mcma.portal/playwright."""
    registry = ActiveReviewRegistry()
    registry.register("job-1", "acct-1", FakeHandle(), on_close=lambda job_id: None)
    assert registry.active_job_count() == 1
