"""INC-18 -- shared fixtures for tests/app/serve/*. Generates a temporary
self-signed cert/key pair LOCALLY via the system `openssl` CLI (a pure
local crypto operation, zero network access -- no external cert-service
is ever contacted, satisfying the campaign's egress rules)."""

import shutil
import subprocess
from pathlib import Path

import pytest


def _openssl_available() -> bool:
    return shutil.which("openssl") is not None


requires_openssl = pytest.mark.skipif(not _openssl_available(), reason="openssl CLI not available on this machine")


@pytest.fixture()
def self_signed_cert(tmp_path: Path):
    """A valid, locally-generated self-signed cert/key pair -- the
    increment doc's own "Mock/fixtures: a temporary self-signed cert for
    the 'valid cert' case." Skips (not fails) on a machine without the
    openssl CLI rather than fabricating fake success."""
    if not _openssl_available():
        pytest.skip("openssl CLI not available on this machine")
    cert_path = tmp_path / "dev-cert.pem"
    key_path = tmp_path / "dev-key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_path), "-out", str(cert_path),
            "-days", "1", "-nodes", "-subj", "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, key_path


@pytest.fixture()
def mismatched_key(tmp_path: Path, self_signed_cert):
    """A SECOND, independently-generated key -- deliberately does not
    match the cert from self_signed_cert, for the cert/key-mismatch case."""
    cert_path, _ = self_signed_cert
    other_key_path = tmp_path / "other-key.pem"
    other_cert_path = tmp_path / "other-cert.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(other_key_path), "-out", str(other_cert_path),
            "-days", "1", "-nodes", "-subj", "/CN=other",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, other_key_path
