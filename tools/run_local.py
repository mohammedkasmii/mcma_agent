"""
tools/run_local.py -- start the rebuilt application on a single machine,
against the LOOPBACK MOCK PORTAL only.

    python tools/run_local.py

This is the local/demo entry point, not a deployment tool. It differs
from a production start in exactly two ways, both of which are checked
rather than trusted:

  * dev_mode=True selects the TEST-ONLY plaintext job-input encryptor,
    because no DPAPI-backed InputEncryptor exists yet (INC-21).
    mcma.core.config.require_dev_mode_is_safe() refuses to start if this
    is ever combined with a non-loopback allowed_host, so real dossier
    PII cannot be written through it.
  * It generates a self-signed loopback TLS certificate if none exists.
    There is no plaintext HTTP path anywhere in the service (ADR-0008),
    so a cert is required even locally. deploy/tls/README.md covers real
    internal-CA certs; a dev cert is bound to 127.0.0.1 and is never a
    substitute for one.

It does NOT start mock_server.py -- run that yourself first, in its own
terminal:

    python mock_server.py

Not part of the `mcma` import-linter root package: like
tools/onboarding_tool.py this is a standalone operator script.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEV_TLS_DIR = REPO_ROOT / "var" / "dev-tls"
DEV_CERT = DEV_TLS_DIR / "dev-localhost.crt"
DEV_KEY = DEV_TLS_DIR / "dev-localhost.key"


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


def _generate_with_cryptography() -> bool:
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
    DEV_KEY.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    DEV_CERT.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return True


def ensure_dev_certificate() -> None:
    """Generates a self-signed 127.0.0.1 certificate, the same shape
    deploy/tls/README.md describes for a developer machine. Never
    overwrites an existing pair, and never produces a cert for anything
    but loopback."""
    if DEV_CERT.is_file() and DEV_KEY.is_file():
        print(f"[*] Using existing dev certificate: {DEV_CERT}")
        return

    DEV_TLS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[*] Generating a self-signed loopback certificate in {DEV_TLS_DIR} ...")

    openssl = _find_openssl()
    if openssl is not None:
        try:
            subprocess.run(
                [
                    openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                    "-days", "365", "-nodes",
                    "-keyout", str(DEV_KEY),
                    "-out", str(DEV_CERT),
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

    if _generate_with_cryptography():
        print("[*] Dev certificate generated with the `cryptography` library.")
        return

    raise SystemExit(
        "Could not generate a development certificate: no openssl was found and the\n"
        "`cryptography` library is not installed. Either:\n"
        "  pip install cryptography\n"
        "or add Git's openssl to PATH (usually C:\\Program Files\\Git\\usr\\bin),\n"
        "or place your own cert/key at:\n"
        f"  {DEV_CERT}\n  {DEV_KEY}"
    )


def main() -> None:
    from mcma.app.main import main as run_service
    from mcma.core.config import Settings

    ensure_dev_certificate()

    settings = Settings(
        dev_mode=True,
        allowed_host="127.0.0.1:8080",   # the mock portal
        tls_cert_path=DEV_CERT,
        tls_key_path=DEV_KEY,
        api_host="127.0.0.1",
        api_port=8443,
        headless_browser=False,          # the handoff window must be visible
    )

    print()
    print("=" * 68)
    print("  MCMA - local run (MOCK PORTAL ONLY, no live portal contact)")
    print("=" * 68)
    print(f"  Dashboard : https://127.0.0.1:{settings.api_port}/")
    print(f"  Portal    : http://{settings.allowed_host}  (start: python mock_server.py)")
    print(f"  Database  : {settings.db_path}")
    print()
    print("  Your browser will warn about the self-signed certificate.")
    print("  That is expected locally; accept it to continue.")
    print()
    print("  First run? Create the first admin:")
    print(f"    POST https://127.0.0.1:{settings.api_port}/bootstrap-app/bootstrap/tokens")
    print("  (loopback-only, single-use, expiring)")
    print("=" * 68)
    print()

    run_service(settings)


if __name__ == "__main__":
    main()
