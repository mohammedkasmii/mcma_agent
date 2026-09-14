"""What serve() actually hands uvicorn.run.

use_colors=False is the fix for the agency PC: with the flag absent uvicorn
autodetects whether the console understands ANSI colour, and on legacy
Windows PowerShell it guessed wrong -- every startup line arrived as
literal escape codes ("<-[32mINFO<-[0m:     Started server process").

The TLS assertions here are not incidental: they pin that adding a
formatting flag did not disturb the fail-closed certificate path, which is
the whole point of this module.
"""

from __future__ import annotations

import uvicorn
import pytest

from mcma.app.serve import TlsConfig, TlsConfigurationError, serve
from serve_test_support import requires_openssl


class _Recorder:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, app, **kwargs):
        self.calls.append((app, kwargs))


@pytest.fixture()
def recorded_run(monkeypatch):
    """serve() does `import uvicorn` inside the function, so patching the
    module attribute is what the real call resolves to -- no server ever
    starts and no port is bound."""
    recorder = _Recorder()
    monkeypatch.setattr(uvicorn, "run", recorder)
    return recorder


@requires_openssl
def test_serve_disables_uvicorn_colour_output(self_signed_cert, recorded_run):
    cert_path, key_path = self_signed_cert
    app = object()

    serve(app, TlsConfig(cert_path=cert_path, key_path=key_path, host="127.0.0.1", port=8443))

    assert len(recorded_run.calls) == 1
    served_app, kwargs = recorded_run.calls[0]
    assert kwargs["use_colors"] is False
    # Explicit, not merely falsy: uvicorn treats None as "autodetect", which
    # is the behaviour that produced the escape codes.
    assert kwargs["use_colors"] is not None
    # No subnet allowlist -> the app is passed straight through.
    assert served_app is app
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8443


@requires_openssl
def test_serve_still_passes_the_validated_tls_material(self_signed_cert, recorded_run):
    cert_path, key_path = self_signed_cert

    serve(object(), TlsConfig(cert_path=cert_path, key_path=key_path))

    _, kwargs = recorded_run.calls[0]
    assert kwargs["ssl_certfile"] == str(cert_path)
    assert kwargs["ssl_keyfile"] == str(key_path)
    # There is no plaintext fallback kwarg of any kind.
    assert "ssl_certfile" in kwargs and "ssl_keyfile" in kwargs


def test_a_bad_certificate_still_fails_before_any_server_starts(tmp_path, recorded_run):
    """Fail-closed TLS is unchanged: uvicorn.run is never reached."""
    with pytest.raises(TlsConfigurationError):
        serve(object(), TlsConfig(cert_path=tmp_path / "absent.crt", key_path=tmp_path / "absent.key"))
    assert recorded_run.calls == []


@requires_openssl
def test_a_configured_subnet_allowlist_still_wraps_the_app(self_signed_cert, recorded_run):
    cert_path, key_path = self_signed_cert
    app = object()

    serve(
        app,
        TlsConfig(cert_path=cert_path, key_path=key_path, subnet_allowlist=("127.0.0.0/8",)),
    )

    served_app, kwargs = recorded_run.calls[0]
    assert served_app is not app  # wrapped by the allowlist middleware
    assert kwargs["use_colors"] is False
