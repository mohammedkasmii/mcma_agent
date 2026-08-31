"""
mcma.app.local_tls -- generate the loopback certificate a local install
serves with.

There is no plaintext HTTP listener anywhere in this application
(ADR-0008, mcma.app.serve), so a local run cannot start without a
certificate. Preparing one by hand is not a decision an employee should
have to make on their own machine, and it is not a security decision
either: this cert is bound to 127.0.0.1 and is never a substitute for the
internal-CA certificate deploy/tls/README.md describes for a real LAN
deployment.

Two routes, so a default Windows install needs nothing new: the openssl
that ships with Git for Windows, or the `cryptography` library in
process. An existing pair is never overwritten.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _find_openssl() -> "str | None":
    """PATH first, then the places Windows actually keeps one. Git for
    Windows ships openssl and is already installed on any machine that
    cloned this repository, so the common case needs no new install."""
    found = shutil.which("openssl")
    if found:
        return found
    candidates = [
        Path(r"C:\Program Files\Git\usr\bin\openssl.exe"),
        Path(r"C:\Program Files (x86)\Git\usr\bin\openssl.exe"),
        Path(r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "usr" / "bin" / "openssl.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _generate_with_cryptography(cert_path: Path, key_path: Path) -> bool:
    """Pure-Python fallback. Returns False if the library is unavailable,
    so the caller can report both routes at once rather than failing
    twice."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        return False

    import datetime
    import ipaddress

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return True


def ensure_local_certificate(cert_path: Path, key_path: Path) -> None:
    """Generates a self-signed 127.0.0.1 certificate, the same shape
    deploy/tls/README.md describes for a developer machine. Never
    overwrites an existing pair, and never produces a cert for anything
    but loopback."""
    if cert_path.is_file() and key_path.is_file():
        return

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[*] Generation du certificat local dans {cert_path.parent} ...")

    openssl = _find_openssl()
    if openssl is not None:
        try:
            subprocess.run(
                [
                    openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                    "-days", "365", "-nodes",
                    "-keyout", str(key_path),
                    "-out", str(cert_path),
                    "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1",
                ],
                check=True,
                capture_output=True,
            )
            print(f"[*] Dev certificate generated with {openssl}")
            return
        except subprocess.CalledProcessError as exc:
            print(f"[!] openssl failed, trying the Python fallback:\n{exc.stderr.decode(errors='replace')}")

    if _generate_with_cryptography(cert_path, key_path):
        print("[*] Dev certificate generated with the `cryptography` library.")
        return

    raise SystemExit(
        "Could not generate a development certificate: no openssl was found and the\n"
        "`cryptography` library is not installed. Either:\n"
        "  pip install cryptography\n"
        "or add Git's openssl to PATH (usually C:\\Program Files\\Git\\usr\\bin),\n"
        "or place your own cert/key at:\n"
        f"  {cert_path}\n  {key_path}"
    )
