"""mcma.app.workstation_runner.execution_permit -- Phase 1C-C Pass 2A,
requirement B. Pure unit tests -- no Playwright, no portal, no threads
beyond the single cross-thread invalidate() check below."""

import asyncio
import threading

import pytest

from mcma.app.workstation_runner.execution_permit import ExecutionPermit, ExecutionPermitInvalid


def test_starts_invalid():
    permit = ExecutionPermit("acct-mcma-oujda")
    assert permit.is_valid is False


def test_assert_valid_raises_before_activation():
    permit = ExecutionPermit("acct-mcma-oujda")
    with pytest.raises(ExecutionPermitInvalid):
        asyncio.run(permit.assert_valid())


def test_activate_makes_it_valid():
    permit = ExecutionPermit("acct-mcma-oujda")
    permit.activate()
    assert permit.is_valid is True
    asyncio.run(permit.assert_valid())  # must not raise


def test_invalidate_makes_it_invalid():
    permit = ExecutionPermit("acct-mcma-oujda")
    permit.activate()
    permit.invalidate()
    assert permit.is_valid is False
    with pytest.raises(ExecutionPermitInvalid):
        asyncio.run(permit.assert_valid())


def test_activate_after_invalidate_never_makes_it_valid_again():
    """The one-way ratchet: a stale activate() racing a shutdown/renewal-
    failure/cancellation must never win."""
    permit = ExecutionPermit("acct-mcma-oujda")
    permit.activate()
    permit.invalidate()
    permit.activate()  # too late -- must be a no-op
    assert permit.is_valid is False


def test_invalidate_before_activate_stays_invalid_even_if_activated_later():
    permit = ExecutionPermit("acct-mcma-oujda")
    permit.invalidate()
    permit.activate()
    assert permit.is_valid is False


def test_invalidate_is_idempotent():
    permit = ExecutionPermit("acct-mcma-oujda")
    permit.activate()
    permit.invalidate()
    permit.invalidate()
    permit.invalidate()
    assert permit.is_valid is False


def test_account_id_is_exposed_and_carries_no_other_data():
    permit = ExecutionPermit("acct-mcma-nador")
    assert permit.account_id == "acct-mcma-nador"
    # __slots__ means no other attribute can ever be attached -- a server
    # secret or claimant identifier could never accidentally end up here.
    with pytest.raises(AttributeError):
        permit.claim_token = "mcma_ct_should_not_be_settable"  # type: ignore[attr-defined]


def test_exception_carries_only_the_account_id():
    permit = ExecutionPermit("acct-mcma-oujda")
    try:
        asyncio.run(permit.assert_valid())
    except ExecutionPermitInvalid as exc:
        assert exc.account_id == "acct-mcma-oujda"
    else:
        pytest.fail("expected ExecutionPermitInvalid")


def test_invalidate_from_another_thread_is_observed_here():
    """The permit may be invalidated from a thread other than the one
    running the write (e.g. an operator-initiated shutdown) -- one lock
    guards every read/write."""
    permit = ExecutionPermit("acct-mcma-oujda")
    permit.activate()
    other = threading.Thread(target=permit.invalidate)
    other.start()
    other.join(timeout=5.0)
    assert permit.is_valid is False
