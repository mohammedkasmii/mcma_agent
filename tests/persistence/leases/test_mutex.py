"""
INC-11 -- OS single-instance mutex. Real WindowsSingleInstanceMutex is
exercised implicitly by create_single_instance_mutex() on a real Windows
CI/dev host (sys.platform=="win32"); the portable test-only backend
(explicitly requested) proves the SAME contract (single acquire,
second-holder rejected) on any platform, including the Linux CI
namespace this suite also runs under.
"""

import pytest

from mcma.core.mutex import (
    MutexAcquisitionError,
    PortableTestOnlyMutex,
    create_single_instance_mutex,
)


def test_second_process_cannot_acquire_write_capability():
    first = PortableTestOnlyMutex("mcma-service-test")
    first.acquire()
    try:
        second = PortableTestOnlyMutex("mcma-service-test")
        with pytest.raises(MutexAcquisitionError):
            second.acquire()
    finally:
        first.release()


def test_release_frees_the_name_for_a_new_holder():
    first = PortableTestOnlyMutex("mcma-service-test-2")
    first.acquire()
    first.release()
    second = PortableTestOnlyMutex("mcma-service-test-2")
    second.acquire()  # must not raise -- name is free again
    second.release()


def test_production_rejects_non_os_mutex(monkeypatch):
    monkeypatch.setattr("mcma.core.mutex.sys.platform", "linux")
    with pytest.raises(RuntimeError):
        create_single_instance_mutex("mcma-service")


def test_test_only_flag_opts_into_the_portable_backend(monkeypatch):
    monkeypatch.setattr("mcma.core.mutex.sys.platform", "linux")
    mutex = create_single_instance_mutex("mcma-service-3", _test_only_portable_backend=True)
    assert isinstance(mutex, PortableTestOnlyMutex)
    mutex.acquire()
    mutex.release()


def test_windows_platform_returns_the_real_backend(monkeypatch):
    from mcma.core.mutex import WindowsSingleInstanceMutex

    monkeypatch.setattr("mcma.core.mutex.sys.platform", "win32")
    mutex = create_single_instance_mutex("mcma-service-4")
    assert isinstance(mutex, WindowsSingleInstanceMutex)
