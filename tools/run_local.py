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

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEV_TLS_DIR = REPO_ROOT / "var" / "dev-tls"
DEV_CERT = DEV_TLS_DIR / "dev-localhost.crt"
DEV_KEY = DEV_TLS_DIR / "dev-localhost.key"


def ensure_dev_certificate() -> None:
    """Generates a self-signed 127.0.0.1 certificate via the local
    openssl CLI, the same way deploy/tls/README.md §dev describes. Never
    overwrites an existing pair."""
    if DEV_CERT.is_file() and DEV_KEY.is_file():
        print(f"[*] Using existing dev certificate: {DEV_CERT}")
        return

    DEV_TLS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[*] Generating a self-signed loopback certificate in {DEV_TLS_DIR} ...")
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                "-days", "365", "-nodes",
                "-keyout", str(DEV_KEY),
                "-out", str(DEV_CERT),
                "-subj", "/CN=127.0.0.1",
                "-addext", "subjectAltName=IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise SystemExit(
            "openssl was not found on PATH. Install it (Git for Windows ships it in\n"
            "  C:\\Program Files\\Git\\usr\\bin) or supply your own cert/key at:\n"
            f"  {DEV_CERT}\n  {DEV_KEY}"
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"openssl failed:\n{exc.stderr.decode(errors='replace')}")
    print("[*] Dev certificate generated.")


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
