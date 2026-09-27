import json
from pathlib import Path

import pytest

from mcma.app.workstation_runner.identity import (
    IDENTITY_FORMAT_VERSION, IdentityStore, RunnerIdentity, _valid_account_ids,
    select_production_crypto_backend,
)
from mcma.core.dpapi import DpapiUnavailable
from tests.app.workstation_runner._fakes import InMemoryCryptoBackend, WrongUserCryptoBackend

ORIGIN = "https://central.example.local"


def _identity(**overrides) -> RunnerIdentity:
    base = dict(
        format_version=IDENTITY_FORMAT_VERSION, server_origin=ORIGIN,
        runner_id="a" * 32, runner_secret="mcma_rs_" + "b" * 40,
        allowed_account_ids=("acct-mcma-oujda",),
    )
    base.update(overrides)
    return RunnerIdentity(**base)


def test_save_then_load_round_trips(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())
    identity = _identity()
    store.save(identity)
    loaded = store.load(expected_server_origin=ORIGIN)
    assert loaded == identity


def test_load_missing_file_returns_none(tmp_path):
    store = IdentityStore(tmp_path / "missing.bin", InMemoryCryptoBackend())
    assert store.load(expected_server_origin=ORIGIN) is None


def test_save_is_atomic_no_tmp_file_left_behind(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())
    store.save(_identity())
    leftovers = [p for p in tmp_path.iterdir() if p.name != "identity.bin"]
    assert leftovers == []


def test_save_never_writes_plaintext_secret(tmp_path):
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())
    store.save(_identity(runner_secret="mcma_rs_" + "s3cr3t-marker" + "z" * 20))
    raw = (tmp_path / "identity.bin").read_bytes()
    assert b"s3cr3t-marker" not in raw


@pytest.mark.parametrize("corrupt", [
    lambda b: b[:-5],                      # truncated
    lambda b: b[:10] + b"\xff" * 10 + b[20:],  # bit-flipped middle
    lambda b: b"not even our format" + b,   # prefixed garbage
    lambda b: b"",                          # empty
])
def test_load_fails_closed_on_corrupt_ciphertext(tmp_path, corrupt):
    path = tmp_path / "identity.bin"
    store = IdentityStore(path, InMemoryCryptoBackend())
    store.save(_identity())
    path.write_bytes(corrupt(path.read_bytes()))
    assert store.load(expected_server_origin=ORIGIN) is None


def test_load_fails_closed_on_wrong_user_backend(tmp_path):
    path = tmp_path / "identity.bin"
    IdentityStore(path, InMemoryCryptoBackend()).save(_identity())
    reader = IdentityStore(path, WrongUserCryptoBackend())
    assert reader.load(expected_server_origin=ORIGIN) is None


def test_load_fails_closed_on_server_origin_mismatch(tmp_path):
    path = tmp_path / "identity.bin"
    IdentityStore(path, InMemoryCryptoBackend()).save(_identity(server_origin=ORIGIN))
    store = IdentityStore(path, InMemoryCryptoBackend())
    assert store.load(expected_server_origin="https://other.example.local") is None


def test_load_fails_closed_on_wrong_format_version(tmp_path):
    path = tmp_path / "identity.bin"
    backend = InMemoryCryptoBackend()
    IdentityStore(path, backend).save(_identity(format_version=999))
    assert IdentityStore(path, backend).load(expected_server_origin=ORIGIN) is None


@pytest.mark.parametrize("bad_secret", ["", "not-prefixed", "mcma_rs_" + "x" * 300])
def test_load_fails_closed_on_invalid_secret_shape(tmp_path, bad_secret):
    path = tmp_path / "identity.bin"
    backend = InMemoryCryptoBackend()
    IdentityStore(path, backend).save(_identity(runner_secret=bad_secret))
    assert IdentityStore(path, backend).load(expected_server_origin=ORIGIN) is None


def test_load_fails_closed_on_disallowed_account_id(tmp_path):
    path = tmp_path / "identity.bin"
    backend = InMemoryCryptoBackend()
    IdentityStore(path, backend).save(_identity(allowed_account_ids=("acct-mamda",)))
    assert IdentityStore(path, backend).load(expected_server_origin=ORIGIN) is None


def test_save_cleans_up_temp_file_on_write_failure(tmp_path, monkeypatch):
    """Regression: a failure writing the temp ciphertext file (e.g. disk
    full) must never leave a stray encrypted temp file behind."""
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())
    original_write_bytes = Path.write_bytes

    def failing_write_bytes(self, data):
        if self.name.endswith(".identity.tmp"):
            raise OSError("simulated disk full")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write_bytes)
    with pytest.raises(OSError):
        store.save(_identity())
    assert list(tmp_path.iterdir()) == []


def test_save_cleans_up_temp_file_on_replace_failure(tmp_path, monkeypatch):
    """Regression: a failure in the atomic os.replace() (e.g. a permissions
    or cross-device error) must not leave the temp file the write already
    created lying around."""
    store = IdentityStore(tmp_path / "identity.bin", InMemoryCryptoBackend())

    def failing_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("mcma.app.workstation_runner.identity.os.replace", failing_replace)
    with pytest.raises(OSError):
        store.save(_identity())
    assert list(tmp_path.iterdir()) == []


def test_save_propagates_dpapi_failure_and_creates_no_file(tmp_path):
    class _FailingBackend:
        def protect(self, data):
            raise DpapiUnavailable("simulated DPAPI failure")

        def unprotect(self, data):
            raise NotImplementedError

    store = IdentityStore(tmp_path / "identity.bin", _FailingBackend())
    with pytest.raises(DpapiUnavailable):
        store.save(_identity())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", [
    [{}],                                    # unhashable entry -- set(value) used to raise TypeError
    [[]],                                    # unhashable entry
    [None],                                  # hashable but not a string
    [1, 2],                                  # ints, hashable but not strings
    ["acct-mcma-oujda", {}],                 # mixed valid/invalid
    ["acct-mcma-oujda", "acct-mcma-oujda"],  # duplicate
    ["acct-mamda"],                          # well-formed string, but not an allowed account
    ["acct-mcma-oujda", "acct-mcma-nador", "acct-mcma-oujda"],  # too many + duplicate
    "acct-mcma-oujda",                       # not a list at all
    {"acct-mcma-oujda": True},               # not a list at all
])
def test_valid_account_ids_rejects_malformed_values_without_raising(value):
    """RELEASE FOLLOW-UP: the old implementation called set(value) BEFORE
    checking each entry was a string, so an unhashable entry (a dict or a
    list -- both valid JSON values) raised a raw TypeError instead of
    being rejected cleanly."""
    assert _valid_account_ids(value) is False


@pytest.mark.parametrize("value", [[], ["acct-mcma-oujda"], ["acct-mcma-oujda", "acct-mcma-nador"]])
def test_valid_account_ids_accepts_well_formed_values(value):
    assert _valid_account_ids(value) is True


def test_load_fails_closed_on_malformed_account_ids_shape_without_raising(tmp_path):
    """A structurally invalid decrypted identity (allowed_account_ids
    containing an unhashable entry) must make IdentityStore.load() return
    None, never raise a raw TypeError out of a fail-closed path."""
    path = tmp_path / "identity.bin"
    backend = InMemoryCryptoBackend()
    payload = json.dumps({
        "format_version": IDENTITY_FORMAT_VERSION, "server_origin": ORIGIN,
        "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40,
        "allowed_account_ids": [{}],
    }).encode("utf-8")
    path.write_bytes(backend.protect(payload))
    store = IdentityStore(path, backend)
    assert store.load(expected_server_origin=ORIGIN) is None


def test_clear_removes_the_file(tmp_path):
    path = tmp_path / "identity.bin"
    store = IdentityStore(path, InMemoryCryptoBackend())
    store.save(_identity())
    store.clear()
    assert not path.exists()
    store.clear()  # idempotent


def test_clear_on_missing_file_is_a_noop(tmp_path):
    IdentityStore(tmp_path / "missing.bin", InMemoryCryptoBackend()).clear()


def test_select_production_crypto_backend_refuses_off_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(RuntimeError):
        select_production_crypto_backend()
