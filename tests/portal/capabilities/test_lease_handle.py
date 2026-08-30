"""
INC-08 amendment #2 -- a Protocol containing only account_id does not prove
lease ownership. LeaseHandle must expose assert_valid(), and open_reader
must call it BEFORE creating any context. INC-08 does not implement
persistence or lease acquisition (that remains INC-11) -- these use a
synthetic valid/invalid LeaseHandle double.
"""

import inspect

import pytest

from capabilities_test_support import (
    ALLOWED_HOST,
    FakeBrowser,
    NotALeaseHandle,
    READ_NORMAL_ROWS_CONTRACT,
    SyntheticLeaseHandle,
    run_async,
)
from mcma.portal.capabilities import LeaseHandle, LeaseInvalid, open_reader


def test_lease_handle_protocol_requires_assert_valid_and_account_id():
    valid_double = SyntheticLeaseHandle()
    assert isinstance(valid_double, LeaseHandle)
    assert not isinstance(NotALeaseHandle(), LeaseHandle)


def test_open_reader_validates_lease_before_creating_any_context():
    browser = FakeBrowser()
    lease = SyntheticLeaseHandle(valid=True)
    run_async(open_reader(browser, lease, (READ_NORMAL_ROWS_CONTRACT,), ALLOWED_HOST))
    assert lease.assert_valid_calls == 1
    assert len(browser.new_context_calls) == 1


def test_open_reader_rejects_an_invalid_lease_before_creating_any_context():
    browser = FakeBrowser()
    lease = SyntheticLeaseHandle(valid=False)
    with pytest.raises(LeaseInvalid):
        run_async(open_reader(browser, lease, (READ_NORMAL_ROWS_CONTRACT,), ALLOWED_HOST))
    assert lease.assert_valid_calls == 1
    assert browser.new_context_calls == []


def test_open_reader_rejects_an_object_that_is_not_a_lease_handle_at_all():
    browser = FakeBrowser()
    with pytest.raises(TypeError):
        run_async(open_reader(browser, NotALeaseHandle(), (READ_NORMAL_ROWS_CONTRACT,), ALLOWED_HOST))
    assert browser.new_context_calls == []


def test_lease_handle_assert_valid_is_a_coroutine_function():
    assert inspect.iscoroutinefunction(LeaseHandle.assert_valid)
