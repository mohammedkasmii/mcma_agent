"""
INC-07 — pytest fixtures for tests/portal/safety/*.

Plain constants/fake classes live in portal_test_support.py, not here — see
that file's docstring for why (a bare "conftest" import would collide with
tests/mock/conftest.py in the same test session).
"""

import pytest

from portal_test_support import FakeContext


@pytest.fixture()
def fake_context():
    return FakeContext()
