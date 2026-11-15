"""
mcma.core.client_certificate -- the SinAuto TLS client certificate (mTLS)
used by the CENTRAL server's headless notification browser.

SinAuto requests a client certificate during the TLS handshake and rejects
connections that do not present one, before any HTTP, login or session
handling happens. The central server therefore holds one PKCS#12 bundle
(private key + certificate) and a SEPARATE file holding its passphrase.
Configuration names the two PATHS; the secrets themselves never appear in
settings, environment values, command lines, logs, exceptions or health
output.

Only mcma.app.central_server calls load_sinauto_client_certificate(). The
Windows workstation runner and every local composition never read these
settings and never hold a certificate.

Everything here FAILS CLOSED with a fixed sentence (ClientCertificateError)
that never contains the passphrase, the key or the bundle bytes:

  * a missing file, a symlink, a non-regular file, an oversized file;
  * on POSIX: a file not owned by the running service user, or readable /
    writable by group or others (mode 0600 or stricter is required);
  * an empty passphrase, invalid UTF-8, or control characters other than
    one trailing newline;
  * a bundle that cannot be decrypted with the passphrase or is malformed;
  * no private key, no certificate, or a key that does not match it;
  * a certificate that is expired or not yet valid;
  * no TLS Web Client Authentication extended key usage.

The validated bundle is re-encoded IN MEMORY with modern PKCS#12 algorithms
(PBES2 / AES-256-CBC, SHA-256 MAC). Playwright's driver loads it with
Node's OpenSSL 3, which rejects the legacy RC2/3DES encodings many issuing
tools still produce; re-encoding removes that failure mode without ever
writing a converted copy to disk.
"""

from __future__ import annotations

import datetime as _dt
import os
import stat
from pathlib import Path
from typing import Mapping, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID

from mcma.core.aead import key_file_permission_problem

# The ONE origin the certificate may ever be offered to. Kept as a literal
# because mcma.core may not import mcma.portal (where DEFAULT_SINAUTO_HOST
# lives); a test pins the two to the same value.
SINAUTO_HOST = "sinauto.mamda-mcma.ma"
SINAUTO_ORIGIN = f"https://{SINAUTO_HOST}"

MAX_PFX_BYTES = 64 * 1024
MAX_PASSPHRASE_BYTES = 1024
EXPIRY_WARNING_DAYS = 30
_KDF_ROUNDS = 50_000

# Environment variables that would change how Playwright's client-
# certificate proxy behaves. DEBUG=pw:protocol / pw:channel prints the
# driver protocol -- including the passphrase -- to stderr; the proxy
# variables would route the certificate-bearing TLS connection through a
# third party (Playwright honours them via proxy-from-env).
_PROXY_VARIABLES = (
    "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
    "npm_config_https_proxy", "npm_config_proxy",
)


class ClientCertificateError(Exception):
    """The client certificate or its passphrase is missing or unsafe.
    The message is a fixed sentence; it never contains secret material."""


def sinauto_client_origin(portal_host: object) -> str:
    """The exact origin the certificate is bound to, derived from
    settings.portal_host. Anything but the bare SinAuto host -- a port, a
    wildcard, a scheme, a path, different case, surrounding whitespace -- is
    refused rather than normalized."""
    if not isinstance(portal_host, str) or portal_host != SINAUTO_HOST:
        raise ClientCertificateError(
            f"portal_host must be exactly {SINAUTO_HOST} (no scheme, port, path or wildcard) "
            "for the SinAuto client certificate"
        )
    return SINAUTO_ORIGIN


def environment_problems(environ: Mapping[str, str]) -> list[str]:
    """Process-environment settings that would leak the passphrase or
    divert the certificate-bearing connection. Names only, never values."""
    problems = []
    if "pw:" in environ.get("DEBUG", ""):
        problems.append("DEBUG must not enable Playwright protocol logging (pw:*) on the central server")
    for name in _PROXY_VARIABLES:
        if environ.get(name):
            problems.append(f"{name} must not be set: the SinAuto client certificate connection is direct")
    return problems


def read_protected_file(path: Path, *, label: str, max_bytes: int) -> bytes:
    """Reads a small secret file safely. Refuses symlinks and non-regular
    files; checks ownership/mode on the OPEN descriptor (POSIX) so a path
    swap between check and read is detected; bounds the size."""
    path = Path(path)
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        raise ClientCertificateError(f"{label} not found") from None
    except OSError:
        raise ClientCertificateError(f"{label} cannot be inspected") from None
    if stat.S_ISLNK(before.st_mode):
        raise ClientCertificateError(f"{label} must not be a symlink")
    if not stat.S_ISREG(before.st_mode):
        raise ClientCertificateError(f"{label} must be a regular file")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NOCTTY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise ClientCertificateError(f"{label} cannot be opened") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ClientCertificateError(f"{label} must be a regular file")
        if os.name == "posix":
            if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
                raise ClientCertificateError(f"{label} changed while it was being opened")
            problem = key_file_permission_problem(info.st_mode, info.st_uid, os.geteuid())
            if problem is not None:
                raise ClientCertificateError(f"{label}: {problem}")
        if info.st_size > max_bytes:
            raise ClientCertificateError(f"{label} is larger than {max_bytes} bytes")
        chunks = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if len(data) > max_bytes:
        raise ClientCertificateError(f"{label} is larger than {max_bytes} bytes")
    if not data:
        raise ClientCertificateError(f"{label} is empty")
    return data


def decode_passphrase(raw: bytes) -> str:
    """UTF-8 text; exactly one trailing newline (LF or CRLF) is tolerated
    because editors add one. Nothing else is stripped."""
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ClientCertificateError("the client certificate passphrase file is not valid UTF-8 text") from None
    if not text:
        raise ClientCertificateError("the client certificate passphrase file is empty")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        raise ClientCertificateError(
            "the client certificate passphrase file contains control characters "
            "(only one trailing newline is allowed)"
        )
    return text


def _public_der(public_key) -> bytes:
    return public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )


class SinautoClientCertificate:
    """A validated client certificate bound to one origin. Holds the secret
    material privately; repr/str show only public metadata, and the object
    refuses to be pickled or copied into anything that might be persisted."""

    __slots__ = ("_origin", "_pfx", "_passphrase", "subject", "issuer", "not_after", "fingerprint_sha256")

    def __init__(
        self, *, origin: str, pfx: bytes, passphrase: str,
        subject: str, issuer: str, not_after: _dt.datetime, fingerprint_sha256: str,
    ) -> None:
        self._origin = origin
        self._pfx = pfx
        self._passphrase = passphrase
        self.subject = subject
        self.issuer = issuer
        self.not_after = not_after
        self.fingerprint_sha256 = fingerprint_sha256

    @property
    def origin(self) -> str:
        return self._origin

    def playwright_client_certificates(self) -> list[dict]:
        """The `client_certificates` value for Playwright's new_context():
        one entry, bound to exactly this origin. Bytes, not a path -- the
        file was already read once through a checked descriptor."""
        return [{"origin": self._origin, "pfx": self._pfx, "passphrase": self._passphrase}]

    def expires_within(self, days: int, *, now: Optional[_dt.datetime] = None) -> bool:
        now = now or _dt.datetime.now(_dt.timezone.utc)
        return self.not_after - now <= _dt.timedelta(days=days)

    def __repr__(self) -> str:
        return (
            f"SinautoClientCertificate(origin={self._origin!r}, subject={self.subject!r}, "
            f"not_after={self.not_after.isoformat()!r}, secret=<redacted>)"
        )

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("SinautoClientCertificate holds secret material and cannot be pickled")

    def __copy__(self):
        raise TypeError("SinautoClientCertificate cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("SinautoClientCertificate cannot be copied")


def validate_pkcs12(
    pfx: bytes, passphrase: str, *, origin: str, now: Optional[_dt.datetime] = None,
) -> SinautoClientCertificate:
    """Decrypts and checks the bundle; returns it re-encoded with modern
    algorithms. Every failure is a fixed message raised `from None`, so no
    library exception (or its traceback context) travels with it."""
    secret = passphrase.encode("utf-8")
    try:
        bundle = pkcs12.load_pkcs12(pfx, secret)
    except Exception:
        raise ClientCertificateError(
            "the client certificate bundle could not be opened (wrong passphrase, or not a valid PKCS#12 file)"
        ) from None

    key = bundle.key
    certificate = bundle.cert.certificate if bundle.cert is not None else None
    if key is None:
        raise ClientCertificateError("the client certificate bundle contains no private key")
    if certificate is None:
        raise ClientCertificateError("the client certificate bundle contains no certificate")
    try:
        matches = _public_der(key.public_key()) == _public_der(certificate.public_key())
    except Exception:
        matches = False
    if not matches:
        raise ClientCertificateError("the private key in the bundle does not match its certificate")

    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now < certificate.not_valid_before_utc:
        raise ClientCertificateError("the client certificate is not valid yet")
    if now >= certificate.not_valid_after_utc:
        raise ClientCertificateError("the client certificate has expired")

    try:
        usages = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    except x509.ExtensionNotFound:
        usages = ()
    except Exception:
        raise ClientCertificateError("the client certificate extensions could not be read") from None
    if ExtendedKeyUsageOID.CLIENT_AUTH not in usages:
        raise ClientCertificateError(
            "the client certificate does not allow TLS Web Client Authentication (extended key usage)"
        )
    try:
        key_usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        key_usage = None
    if key_usage is not None and not key_usage.digital_signature:
        raise ClientCertificateError("the client certificate key usage does not allow digital signatures")

    try:
        encryption = (
            serialization.PrivateFormat.PKCS12.encryption_builder()
            .kdf_rounds(_KDF_ROUNDS)
            .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC)
            .hmac_hash(hashes.SHA256())
            .build(secret)
        )
        modern = pkcs12.serialize_key_and_certificates(
            None, key, certificate,
            [extra.certificate for extra in bundle.additional_certs] or None,
            encryption,
        )
    except Exception:
        raise ClientCertificateError("the client certificate bundle could not be re-encoded") from None

    return SinautoClientCertificate(
        origin=origin,
        pfx=modern,
        passphrase=passphrase,
        subject=certificate.subject.rfc4514_string(),
        issuer=certificate.issuer.rfc4514_string(),
        not_after=certificate.not_valid_after_utc,
        fingerprint_sha256=certificate.fingerprint(hashes.SHA256()).hex(),
    )


def load_sinauto_client_certificate(
    pfx_path: Path, passphrase_path: Path, portal_host: str,
    *, now: Optional[_dt.datetime] = None,
) -> SinautoClientCertificate:
    """Central server only. Reads both files once, validates, and returns
    the certificate bound to https://sinauto.mamda-mcma.ma."""
    origin = sinauto_client_origin(portal_host)
    if pfx_path is None or passphrase_path is None:
        raise ClientCertificateError("both the client certificate and its passphrase file are required")
    pfx = read_protected_file(pfx_path, label="the client certificate bundle", max_bytes=MAX_PFX_BYTES)
    passphrase = decode_passphrase(
        read_protected_file(
            passphrase_path, label="the client certificate passphrase file", max_bytes=MAX_PASSPHRASE_BYTES,
        )
    )
    return validate_pkcs12(pfx, passphrase, origin=origin, now=now)
