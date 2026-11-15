"""Throwaway TLS material for the SinAuto mTLS tests. Every key and
certificate is generated in memory at test time; nothing here is, or is
derived from, a real certificate. EC P-256 keys keep generation fast.

Importable from other test directories by path (see load_factory())."""

from __future__ import annotations

import datetime as dt
import importlib.util
import ipaddress
import sys
from pathlib import Path
from typing import Iterable, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

TEST_PASSPHRASE = "unit-test-passphrase-Ω"
CLIENT_AUTH = ExtendedKeyUsageOID.CLIENT_AUTH
SERVER_AUTH = ExtendedKeyUsageOID.SERVER_AUTH


def load_factory():
    """For tests outside tests/central (their own directory is the one on
    sys.path): load this module by file path."""
    name = "mcma_test_client_cert_factory"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_key():
    return ec.generate_private_key(ec.SECP256R1())


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca(cn: str = "mcma-test-ca"):
    key = new_key()
    now = _now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn)).issuer_name(_name(cn))
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def issue(
    ca, *, cn: str = "client-test", key=None,
    eku: Optional[Iterable] = (CLIENT_AUTH,),
    not_before: Optional[dt.datetime] = None, not_after: Optional[dt.datetime] = None,
    digital_signature: Optional[bool] = True, san_ips: Iterable[str] = (),
):
    """A leaf certificate signed by `ca` (a (key, cert) pair). eku=None
    omits the extension; digital_signature=None omits KeyUsage."""
    ca_key, ca_cert = ca
    key = key or new_key()
    now = _now()
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(cn)).issuer_name(ca_cert.subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - dt.timedelta(days=1))
        .not_valid_after(not_after or now + dt.timedelta(days=365))
    )
    if eku is not None:
        builder = builder.add_extension(x509.ExtendedKeyUsage(list(eku)), critical=False)
    if digital_signature is not None:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=digital_signature, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=not digital_signature, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
    if san_ips:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)) for ip in san_ips]),
            critical=False,
        )
    return key, builder.sign(ca_key, hashes.SHA256())


def pack(key, cert, passphrase: str = TEST_PASSPHRASE, *, extra=(), legacy: bool = False) -> bytes:
    """PKCS#12 bytes. legacy=True uses PBES1 SHA1/3DES (what older issuing
    tools produce); otherwise PBES2/AES-256."""
    if legacy:
        encryption = (
            serialization.PrivateFormat.PKCS12.encryption_builder()
            .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
            .hmac_hash(hashes.SHA1())
            .build(passphrase.encode("utf-8"))
        )
    else:
        encryption = serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
    return pkcs12.serialize_key_and_certificates(b"test", key, cert, list(extra) or None, encryption)


def client_bundle(passphrase: str = TEST_PASSPHRASE, **issue_kwargs) -> bytes:
    """A valid client bundle (key + clientAuth certificate) by default."""
    ca = make_ca()
    key, cert = issue(ca, **issue_kwargs)
    return pack(key, cert, passphrase)


def write_owner_only(path: Path, data: bytes) -> Path:
    import os

    path.write_bytes(data)
    if os.name == "posix":
        os.chmod(path, 0o600)
    return path


def write_client_files(directory: Path, passphrase: str = TEST_PASSPHRASE, bundle: Optional[bytes] = None):
    """(pfx_path, passphrase_path) holding a valid bundle and its passphrase
    (with the trailing newline an editor would add)."""
    directory.mkdir(parents=True, exist_ok=True)
    pfx = write_owner_only(directory / "sinauto-client.p12", bundle or client_bundle(passphrase))
    secret = write_owner_only(directory / "sinauto-client.pass", (passphrase + "\n").encode("utf-8"))
    return pfx, secret
