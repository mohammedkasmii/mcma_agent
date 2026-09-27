"""POSIX-only primitives used by the Ubuntu server. Skipped on Windows,
where they cannot run -- they execute in Linux CI / on the target host."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only primitives")


def test_flock_mutex_is_exclusive_and_releasable(tmp_path):
    from mcma.core.mutex import MutexAcquisitionError, PosixFlockMutex

    lock = tmp_path / "mcma.lock"
    first, second = PosixFlockMutex(lock), PosixFlockMutex(lock)
    first.acquire()
    with pytest.raises(MutexAcquisitionError):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_factory_picks_flock_only_when_a_lock_file_is_configured(tmp_path):
    from mcma.core.mutex import PosixFlockMutex, create_single_instance_mutex

    assert isinstance(create_single_instance_mutex("x", lock_path=tmp_path / "l"), PosixFlockMutex)
    with pytest.raises(RuntimeError):
        create_single_instance_mutex("x")  # still refuses by omission


def test_vault_directory_verifier(tmp_path):
    from mcma.portal.vault import PosixVaultDirectoryVerifier, get_acl_verifier

    directory = tmp_path / "vault"
    directory.mkdir()
    verifier = PosixVaultDirectoryVerifier()
    os.chmod(directory, 0o700)
    assert verifier.verify_restrictive(directory) is True
    os.chmod(directory, 0o750)
    assert verifier.verify_restrictive(directory) is False
    assert verifier.verify_restrictive(tmp_path / "missing") is False
    assert isinstance(get_acl_verifier(), PosixVaultDirectoryVerifier)
