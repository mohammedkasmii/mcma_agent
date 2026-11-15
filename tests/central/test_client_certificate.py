"""mcma.core.client_certificate -- the central server's SinAuto mTLS loader.

Every bundle here is generated at test time (client_cert_factory); no real
certificate is involved. The recurring assertion is that NO failure path
carries the passphrase, the key or the bundle bytes in its message, its
exception chain or the object's repr."""

import copy
import datetime as dt
import os
import pickle

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12

from client_cert_factory import (
    CLIENT_AUTH,
    SERVER_AUTH,
    TEST_PASSPHRASE,
    client_bundle,
    issue,
    make_ca,
    new_key,
    pack,
    write_client_files,
    write_owner_only,
)
from mcma.core.client_certificate import (
    MAX_PASSPHRASE_BYTES,
    MAX_PFX_BYTES,
    SINAUTO_HOST,
    SINAUTO_ORIGIN,
    ClientCertificateError,
    SinautoClientCertificate,
    decode_passphrase,
    environment_problems,
    load_sinauto_client_certificate,
    sinauto_client_origin,
    validate_pkcs12,
)
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX ownership/mode bits")


def _load(tmp_path, *, bundle=None, passphrase=TEST_PASSPHRASE, passphrase_bytes=None, host=SINAUTO_HOST, now=None):
    pfx, secret = write_client_files(tmp_path / "c", passphrase, bundle=bundle or client_bundle(passphrase))
    if passphrase_bytes is not None:
        write_owner_only(secret, passphrase_bytes)
    return load_sinauto_client_certificate(pfx, secret, host, now=now)


def _assert_secret_free(exc: BaseException, *secrets: str) -> None:
    text = str(exc) + repr(exc)
    for secret in secrets:
        assert secret not in text
    # No library exception (or its locals) travels along: either nothing
    # was being handled, or it was raised `from None`.
    assert exc.__cause__ is None
    assert exc.__context__ is None or exc.__suppress_context__ is True


# ------------------------------- origin -------------------------------- #


def test_the_core_literal_matches_the_portal_constant():
    assert SINAUTO_HOST == DEFAULT_SINAUTO_HOST
    assert SINAUTO_ORIGIN == "https://sinauto.mamda-mcma.ma"


@pytest.mark.parametrize("host", [
    "sinauto.mamda-mcma.ma:443", "*.mamda-mcma.ma", "Sinauto.mamda-mcma.ma", "https://sinauto.mamda-mcma.ma",
    "sinauto.mamda-mcma.ma.", "sinauto.mamda-mcma.ma ", "127.0.0.1:8080", "", None, 42,
])
def test_only_the_bare_sinauto_host_yields_an_origin(host):
    with pytest.raises(ClientCertificateError):
        sinauto_client_origin(host)
    assert sinauto_client_origin("sinauto.mamda-mcma.ma") == "https://sinauto.mamda-mcma.ma"


# ------------------------------ happy path ------------------------------ #


def test_a_valid_bundle_is_bound_to_exactly_the_sinauto_origin(tmp_path):
    certificate = _load(tmp_path)
    (entry,) = certificate.playwright_client_certificates()
    assert set(entry) == {"origin", "pfx", "passphrase"}
    assert entry["origin"] == "https://sinauto.mamda-mcma.ma"
    assert entry["passphrase"] == TEST_PASSPHRASE
    # The bytes handed to Playwright are a real, decryptable bundle.
    reloaded = pkcs12.load_pkcs12(entry["pfx"], TEST_PASSPHRASE.encode("utf-8"))
    assert reloaded.key is not None and reloaded.cert is not None
    assert certificate.subject == "CN=client-test" and len(certificate.fingerprint_sha256) == 64


def test_a_legacy_encoded_bundle_is_re_encoded_in_memory(tmp_path):
    ca = make_ca()
    key, cert = issue(ca)
    legacy = pack(key, cert, legacy=True)
    certificate = _load(tmp_path, bundle=legacy)
    (entry,) = certificate.playwright_client_certificates()
    assert entry["pfx"] != legacy
    reloaded = pkcs12.load_pkcs12(entry["pfx"], TEST_PASSPHRASE.encode("utf-8"))
    assert reloaded.cert.certificate.fingerprint(hashes.SHA256()) == cert.fingerprint(hashes.SHA256())


def test_chain_certificates_are_kept(tmp_path):
    ca = make_ca()
    key, cert = issue(ca)
    certificate = _load(tmp_path, bundle=pack(key, cert, extra=[ca[1]]))
    (entry,) = certificate.playwright_client_certificates()
    assert len(pkcs12.load_pkcs12(entry["pfx"], TEST_PASSPHRASE.encode()).additional_certs) == 1


@pytest.mark.parametrize("suffix", [b"", b"\n", b"\r\n"])
def test_exactly_one_trailing_newline_is_tolerated(tmp_path, suffix):
    certificate = _load(tmp_path, passphrase_bytes=TEST_PASSPHRASE.encode("utf-8") + suffix)
    assert certificate.playwright_client_certificates()[0]["passphrase"] == TEST_PASSPHRASE


def test_no_secret_in_repr_str_and_no_pickling_or_copying(tmp_path):
    certificate = _load(tmp_path)
    for text in (repr(certificate), str(certificate), f"{certificate}"):
        assert TEST_PASSPHRASE not in text and "redacted" in text and "pfx" not in text.lower()
    with pytest.raises(TypeError):
        pickle.dumps(certificate)
    with pytest.raises(TypeError):
        copy.copy(certificate)
    with pytest.raises(TypeError):
        copy.deepcopy(certificate)
    assert not hasattr(certificate, "__dict__")      # slots: nothing to dump by accident


def test_expiry_warning_window(tmp_path):
    certificate = _load(tmp_path)
    assert not certificate.expires_within(30)
    assert certificate.expires_within(400)


# ---------------------------- fail closed ------------------------------- #


def test_a_wrong_passphrase_is_refused_without_echoing_either_passphrase(tmp_path):
    wrong = "the-WRONG-passphrase"
    with pytest.raises(ClientCertificateError, match="could not be opened") as info:
        _load(tmp_path, passphrase_bytes=wrong.encode())
    _assert_secret_free(info.value, wrong, TEST_PASSPHRASE)


@pytest.mark.parametrize(("bundle_kind", "expected"), [
    ("garbage", "could not be opened"),
    ("no_key", "no private key"),
    ("expired", "has expired"),
    ("not_yet_valid", "not valid yet"),
    ("no_eku", "TLS Web Client Authentication"),
    ("server_only", "TLS Web Client Authentication"),
    ("no_digital_signature", "digital signatures"),
])
def test_unusable_bundles_are_refused(tmp_path, bundle_kind, expected):
    ca = make_ca()
    now = dt.datetime.now(dt.timezone.utc)
    if bundle_kind == "garbage":
        bundle = b"not a pkcs12 bundle at all"
    elif bundle_kind == "no_key":
        _, cert = issue(ca)
        bundle = pkcs12.serialize_key_and_certificates(
            b"x", None, cert, None,
            __import__("cryptography.hazmat.primitives.serialization", fromlist=["x"]).BestAvailableEncryption(
                TEST_PASSPHRASE.encode()),
        )
    elif bundle_kind == "expired":
        key, cert = issue(ca, not_before=now - dt.timedelta(days=10), not_after=now - dt.timedelta(days=1))
        bundle = pack(key, cert)
    elif bundle_kind == "not_yet_valid":
        key, cert = issue(ca, not_before=now + dt.timedelta(days=1), not_after=now + dt.timedelta(days=10))
        bundle = pack(key, cert)
    elif bundle_kind == "no_eku":
        key, cert = issue(ca, eku=None)
        bundle = pack(key, cert)
    elif bundle_kind == "server_only":
        key, cert = issue(ca, eku=(SERVER_AUTH,))
        bundle = pack(key, cert)
    else:
        key, cert = issue(ca, digital_signature=False)
        bundle = pack(key, cert)
    with pytest.raises(ClientCertificateError, match=expected) as info:
        _load(tmp_path, bundle=bundle)
    _assert_secret_free(info.value, TEST_PASSPHRASE)


def test_a_key_that_does_not_match_the_certificate_is_refused(monkeypatch):
    """cryptography will not even SERIALIZE such a bundle, but other tools
    can produce one; the loaded parts are substituted to reach the check."""
    from types import SimpleNamespace

    import mcma.core.client_certificate as module

    _, cert = issue(make_ca())
    fake = SimpleNamespace(key=new_key(), cert=SimpleNamespace(certificate=cert), additional_certs=[])
    monkeypatch.setattr(module.pkcs12, "load_pkcs12", lambda data, password: fake)
    with pytest.raises(ClientCertificateError, match="does not match") as info:
        validate_pkcs12(b"irrelevant", TEST_PASSPHRASE, origin=SINAUTO_ORIGIN)
    _assert_secret_free(info.value, TEST_PASSPHRASE)


def test_validity_is_judged_at_the_given_instant(tmp_path):
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=400)
    with pytest.raises(ClientCertificateError, match="expired"):
        _load(tmp_path, now=later)


def test_the_client_auth_bundle_with_both_usages_is_accepted(tmp_path):
    ca = make_ca()
    key, cert = issue(ca, eku=(SERVER_AUTH, CLIENT_AUTH))
    assert _load(tmp_path, bundle=pack(key, cert)).origin == SINAUTO_ORIGIN


@pytest.mark.parametrize(("raw", "expected"), [
    (b"", "is empty"),
    (b"\n", "is empty"),
    (b"pass\n\n", "control characters"),
    (b"pa\tss", "control characters"),
    (b"pa\x00ss", "control characters"),
    (b"\xff\xfe", "UTF-8"),
])
def test_bad_passphrase_files_are_refused(tmp_path, raw, expected):
    with pytest.raises(ClientCertificateError, match=expected) as info:
        _load(tmp_path, passphrase_bytes=raw)
    _assert_secret_free(info.value, TEST_PASSPHRASE)


def test_decode_passphrase_strips_only_one_newline():
    assert decode_passphrase(b"abc\n") == "abc"
    with pytest.raises(ClientCertificateError):
        decode_passphrase(b"abc\n\n")


def test_oversized_files_are_refused(tmp_path):
    with pytest.raises(ClientCertificateError, match="larger than"):
        _load(tmp_path, passphrase_bytes=b"x" * (MAX_PASSPHRASE_BYTES + 1))
    big = tmp_path / "big"
    pfx, secret = write_client_files(big)
    write_owner_only(pfx, b"\0" * (MAX_PFX_BYTES + 1))
    with pytest.raises(ClientCertificateError, match="larger than"):
        load_sinauto_client_certificate(pfx, secret, SINAUTO_HOST)


def test_missing_files_and_directories_are_refused(tmp_path):
    pfx, secret = write_client_files(tmp_path / "c")
    with pytest.raises(ClientCertificateError, match="bundle not found"):
        load_sinauto_client_certificate(tmp_path / "absent.p12", secret, SINAUTO_HOST)
    with pytest.raises(ClientCertificateError, match="passphrase file not found"):
        load_sinauto_client_certificate(pfx, tmp_path / "absent.pass", SINAUTO_HOST)
    with pytest.raises(ClientCertificateError, match="regular file"):
        load_sinauto_client_certificate(tmp_path, secret, SINAUTO_HOST)
    with pytest.raises(ClientCertificateError, match="both"):
        load_sinauto_client_certificate(None, secret, SINAUTO_HOST)


def test_a_symlinked_file_is_refused(tmp_path):
    pfx, secret = write_client_files(tmp_path / "c")
    link = tmp_path / "link.pass"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("this platform/user cannot create symlinks")
    with pytest.raises(ClientCertificateError, match="symlink"):
        load_sinauto_client_certificate(pfx, link, SINAUTO_HOST)


def test_the_host_is_checked_before_any_file_is_read(tmp_path):
    with pytest.raises(ClientCertificateError, match="portal_host"):
        load_sinauto_client_certificate(tmp_path / "absent", tmp_path / "absent", "sinauto.mamda-mcma.ma:443")


@posix_only
@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
@pytest.mark.parametrize("which", ["pfx", "passphrase"])
def test_group_or_other_access_is_refused(tmp_path, mode, which):
    pfx, secret = write_client_files(tmp_path / "c")
    os.chmod(pfx if which == "pfx" else secret, mode)
    with pytest.raises(ClientCertificateError, match="0600"):
        load_sinauto_client_certificate(pfx, secret, SINAUTO_HOST)


@posix_only
def test_a_file_owned_by_another_user_is_refused(tmp_path, monkeypatch):
    pfx, secret = write_client_files(tmp_path / "c")
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(secret).st_uid + 1)
    with pytest.raises(ClientCertificateError, match="owned by the user running the service"):
        load_sinauto_client_certificate(pfx, secret, SINAUTO_HOST)


def test_validate_pkcs12_exposes_no_public_secret_attribute():
    certificate = validate_pkcs12(client_bundle(), TEST_PASSPHRASE, origin=SINAUTO_ORIGIN)
    assert isinstance(certificate, SinautoClientCertificate)
    public = {name: getattr(certificate, name) for name in dir(certificate) if not name.startswith("_")}
    assert TEST_PASSPHRASE not in {value for value in public.values() if isinstance(value, str)}


# ----------------------------- environment ------------------------------ #


def test_environment_that_would_leak_or_divert_is_reported_by_name_only():
    secretish = "http://user:hunter2@proxy.example:3128"
    problems = environment_problems({"DEBUG": "pw:protocol", "HTTPS_PROXY": secretish, "https_proxy": secretish})
    assert len(problems) == 3
    assert all("hunter2" not in problem for problem in problems)
    assert environment_problems({"DEBUG": "", "HTTP_PROXY": "http://x", "NO_PROXY": "*"}) == []
    assert environment_problems({"DEBUG": "pw:api"}) != []
