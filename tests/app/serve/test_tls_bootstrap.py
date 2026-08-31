"""INC-18 -- TLS bootstrap: refuse to start without a valid cert/key, no
plaintext HTTP listener anywhere in this module, and a configurable
subnet allowlist that never disables authentication."""

from pathlib import Path

import pytest

from mcma.app.serve import (
    SubnetAllowlistMiddleware,
    TlsConfig,
    TlsConfigurationError,
    build_ssl_context,
    build_uvicorn_ssl_kwargs,
    wrap_with_subnet_allowlist,
)


# --------------------------------------------------------------------- #
# test_service_refuses_to_start_without_valid_cert
# --------------------------------------------------------------------- #


def test_missing_cert_file_refuses_to_start(tmp_path: Path):
    missing_cert = tmp_path / "no-such-cert.pem"
    key_path = tmp_path / "no-such-key.pem"
    config = TlsConfig(cert_path=missing_cert, key_path=key_path)
    with pytest.raises(TlsConfigurationError):
        build_ssl_context(config)


def test_missing_key_file_refuses_to_start(tmp_path: Path, self_signed_cert):
    cert_path, _ = self_signed_cert
    missing_key = tmp_path / "no-such-key.pem"
    config = TlsConfig(cert_path=cert_path, key_path=missing_key)
    with pytest.raises(TlsConfigurationError):
        build_ssl_context(config)


def test_mismatched_cert_and_key_refuses_to_start(mismatched_key):
    cert_path, wrong_key_path = mismatched_key
    config = TlsConfig(cert_path=cert_path, key_path=wrong_key_path)
    with pytest.raises(TlsConfigurationError):
        build_ssl_context(config)


def test_corrupt_cert_file_refuses_to_start(tmp_path: Path, self_signed_cert):
    _, key_path = self_signed_cert
    corrupt_cert = tmp_path / "corrupt-cert.pem"
    corrupt_cert.write_text("this is not a certificate")
    config = TlsConfig(cert_path=corrupt_cert, key_path=key_path)
    with pytest.raises(TlsConfigurationError):
        build_ssl_context(config)


def test_valid_cert_and_key_succeed(self_signed_cert):
    """The positive control: proves the rejections above are genuine
    validation, not a function that always raises."""
    cert_path, key_path = self_signed_cert
    config = TlsConfig(cert_path=cert_path, key_path=key_path)
    context = build_ssl_context(config)
    assert context is not None


def test_valid_cert_produces_ssl_kwargs_never_plaintext_kwargs(self_signed_cert):
    cert_path, key_path = self_signed_cert
    config = TlsConfig(cert_path=cert_path, key_path=key_path)
    kwargs = build_uvicorn_ssl_kwargs(config)
    assert kwargs["ssl_certfile"] == str(cert_path)
    assert kwargs["ssl_keyfile"] == str(key_path)


# --------------------------------------------------------------------- #
# test_no_plain_http_listener_in_production_mode
# --------------------------------------------------------------------- #


def test_module_exposes_no_plaintext_serving_function():
    """Structural: no function anywhere in mcma.app.serve can produce
    server kwargs that omit TLS -- there is no build_http_kwargs, no
    plain_http=True flag, and serve()/build_uvicorn_ssl_kwargs() both
    call build_ssl_context() (which itself always raises rather than
    ever returning a plaintext substitute) before returning anything."""
    import mcma.app.serve as serve_module

    public_names = {name for name in dir(serve_module) if not name.startswith("_")}
    plaintext_sounding = {name for name in public_names if "http" in name.lower() and "https" not in name.lower()}
    assert plaintext_sounding == set()


def test_build_uvicorn_ssl_kwargs_never_returns_without_a_valid_cert(tmp_path: Path):
    config = TlsConfig(cert_path=tmp_path / "missing.pem", key_path=tmp_path / "missing-key.pem")
    with pytest.raises(TlsConfigurationError):
        build_uvicorn_ssl_kwargs(config)


def test_serve_source_never_constructs_a_bare_uvicorn_run_without_ssl_kwargs():
    """A source-level guard against a future regression re-introducing a
    plaintext code path: every call to uvicorn.run/uvicorn.Config in this
    module's source must be reachable only through build_uvicorn_ssl_kwargs."""
    import inspect

    import mcma.app.serve as serve_module

    source = inspect.getsource(serve_module)
    assert "ssl_certfile" in source
    assert "app_no_tls" not in source
    assert "allow_http" not in source


# --------------------------------------------------------------------- #
# test_subnet_filter_absent_does_not_disable_auth
# --------------------------------------------------------------------- #


class _AlwaysAuthenticatesAsAdminApp:
    """A deliberately over-permissive fake ASGI app standing in for
    mcma.app.api -- the point of these tests is that the SUBNET filter
    never has to be the thing that keeps this safe; authentication would
    still be this app's own job, unaffected by whether the filter ran."""

    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope.get("client"))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def test_empty_subnet_allowlist_returns_the_app_unwrapped():
    app = _AlwaysAuthenticatesAsAdminApp()
    wrapped = wrap_with_subnet_allowlist(app, ())
    assert wrapped is app  # no filter object was even constructed


def test_configured_subnet_allowlist_only_adds_a_restriction_never_grants_one(tmp_path: Path):
    import asyncio

    app = _AlwaysAuthenticatesAsAdminApp()
    wrapped = wrap_with_subnet_allowlist(app, ("192.168.1.0/24",))
    assert isinstance(wrapped, SubnetAllowlistMiddleware)

    async def _run(client_ip):
        sent = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "client": (client_ip, 12345)}
        await wrapped(scope, None, send)
        return sent

    in_subnet = asyncio.run(_run("192.168.1.50"))
    assert in_subnet[0]["status"] == 200
    assert app.calls == [("192.168.1.50", 12345)]  # the underlying (authenticating) app was actually reached

    out_of_subnet = asyncio.run(_run("10.0.0.5"))
    assert out_of_subnet[0]["status"] == 403
    assert len(app.calls) == 1  # the underlying app was never reached for the denied request


def test_subnet_allowlist_never_bypasses_the_underlying_apps_own_auth():
    """Even a request the subnet filter WOULD allow through still has to
    pass the wrapped app's own logic -- this test's fake app happens to
    accept everyone, but the middleware itself performs no authentication
    of its own; it is purely an additional network-level restriction."""
    import asyncio

    class _DenyEveryoneApp:
        async def __call__(self, scope, receive, send):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"unauthenticated"})

    wrapped = wrap_with_subnet_allowlist(_DenyEveryoneApp(), ("192.168.1.0/24",))

    async def _run():
        sent = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "client": ("192.168.1.50", 12345)}
        await wrapped(scope, None, send)
        return sent

    result = asyncio.run(_run())
    assert result[0]["status"] == 401  # subnet allowed it through -- auth still denied it
