"""mcma.portal.browser.ClientCertificateBrowser -- every context the central
notification browser opens carries the SinAuto client certificate for one
exact origin, with HTTPS verification on, and callers cannot override it.

Unit tests use a recording fake Browser. The one real-Chromium test at the
bottom follows the repository's isolation convention (egress_proof +
requires_egress_isolation): it runs only inside loopback-only isolation and
never contacts anything but servers it starts on 127.0.0.1."""

import asyncio
import importlib.util
import ssl
import sys
import threading
from pathlib import Path

import pytest

from mcma.core.client_certificate import (
    SINAUTO_ORIGIN,
    ClientCertificateError,
    validate_pkcs12,
)
from mcma.portal.browser import ClientCertificateBrowser, launch_browser
from mcma.portal.session import open_guarded_context, open_guarded_context_for_login


def _factory():
    path = Path(__file__).resolve().parents[1] / "central" / "client_cert_factory.py"
    name = "mcma_test_client_cert_factory"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


factory = _factory()


def _certificate(origin=SINAUTO_ORIGIN, **issue_kwargs):
    ca = factory.make_ca()
    key, cert = factory.issue(ca, **issue_kwargs)
    return validate_pkcs12(factory.pack(key, cert), factory.TEST_PASSPHRASE, origin=origin)


class _FakeContext:
    def __init__(self):
        self.closed = False
        self.routes = []

    async def route(self, pattern, handler):
        self.routes.append(pattern)

    async def route_web_socket(self, pattern, handler):
        self.routes.append(("ws", pattern))

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, fail_new_context=False):
        self.calls = []
        self.fail_new_context = fail_new_context
        self.closed = False
        self.contexts = []

    async def new_context(self, **options):
        self.calls.append(options)
        if self.fail_new_context:
            raise RuntimeError(
                "Failed to load client certificate: mac verify failure " + factory.TEST_PASSPHRASE
            )
        context = _FakeContext()
        self.contexts.append(context)
        return context

    async def new_page(self, **options):  # pragma: no cover - must never be reached
        raise AssertionError("the wrapper must not delegate new_page")

    def is_connected(self):
        return True

    async def close(self, **options):
        self.closed = True


def _run(coro):
    return asyncio.run(coro)


def test_every_context_gets_exactly_one_certificate_for_the_exact_origin():
    fake = _FakeBrowser()
    wrapped = ClientCertificateBrowser(fake, _certificate())
    _run(wrapped.new_context(storage_state={"cookies": []}))
    _run(wrapped.new_context())
    assert len(fake.calls) == 2
    for options in fake.calls:
        (entry,) = options["client_certificates"]
        assert entry["origin"] == "https://sinauto.mamda-mcma.ma"
        assert set(entry) == {"origin", "pfx", "passphrase"}
        assert options["ignore_https_errors"] is False
    assert fake.calls[0]["storage_state"] == {"cookies": []}


def test_guarded_contexts_opened_through_the_portal_session_helpers_carry_it():
    """The production path: capabilities open contexts via mcma.portal.session,
    which adds service_workers=block and installs the guard -- the
    certificate rides along on the same new_context() call."""
    fake = _FakeBrowser()
    wrapped = ClientCertificateBrowser(fake, _certificate())
    _run(open_guarded_context(wrapped, (), "sinauto.mamda-mcma.ma", {"storage_state": {"cookies": []}}))
    _run(open_guarded_context_for_login(wrapped, "sinauto.mamda-mcma.ma"))
    for options in fake.calls:
        assert options["service_workers"] == "block"
        assert options["client_certificates"][0]["origin"] == SINAUTO_ORIGIN
        assert options["ignore_https_errors"] is False


@pytest.mark.parametrize("options", [
    {"client_certificates": []},
    {"client_certificates": [{"origin": "https://evil.example", "pfx": b"x"}]},
    {"proxy": {"server": "http://127.0.0.1:3128"}},
    {"ignore_https_errors": True},
])
def test_overriding_the_certificate_or_weakening_https_is_refused(options):
    fake = _FakeBrowser()
    wrapped = ClientCertificateBrowser(fake, _certificate())
    with pytest.raises(ValueError):
        _run(wrapped.new_context(**options))
    assert fake.calls == []


def test_an_explicit_false_ignore_https_errors_is_allowed():
    fake = _FakeBrowser()
    _run(ClientCertificateBrowser(fake, _certificate()).new_context(ignore_https_errors=False))
    assert fake.calls[0]["ignore_https_errors"] is False


def test_new_page_is_refused_because_it_would_bypass_the_guards():
    wrapped = ClientCertificateBrowser(_FakeBrowser(), _certificate())
    with pytest.raises(RuntimeError, match="new_page"):
        _run(wrapped.new_page())


def test_self_test_opens_and_closes_one_context_without_navigating():
    fake = _FakeBrowser()
    _run(ClientCertificateBrowser(fake, _certificate()).self_test())
    assert len(fake.calls) == 1 and fake.contexts[0].closed and fake.contexts[0].routes == []


def test_self_test_failure_is_a_fixed_message_with_no_secret_and_no_chain():
    wrapped = ClientCertificateBrowser(_FakeBrowser(fail_new_context=True), _certificate())
    with pytest.raises(ClientCertificateError) as info:
        _run(wrapped.self_test())
    assert str(info.value) == "the browser could not load the SinAuto client certificate"
    assert factory.TEST_PASSPHRASE not in repr(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__ is True


def test_repr_carries_no_secret():
    text = repr(ClientCertificateBrowser(_FakeBrowser(), _certificate()))
    assert factory.TEST_PASSPHRASE not in text and "sinauto.mamda-mcma.ma" in text


def test_lifecycle_methods_are_forwarded():
    fake = _FakeBrowser()
    wrapped = ClientCertificateBrowser(fake, _certificate())
    assert wrapped.is_connected() is True
    assert wrapped.contexts is fake.contexts
    _run(wrapped.close())
    assert fake.closed


def test_launch_browser_without_a_certificate_keeps_its_previous_signature_and_behaviour():
    """Workstation/local callers pass only headless=...; the default for the
    new keyword is None and the plain Browser is yielded (see source)."""
    import inspect

    parameters = inspect.signature(launch_browser).parameters
    assert parameters["headless"].default is False
    assert parameters["client_certificate"].default is None
    assert parameters["client_certificate"].kind is inspect.Parameter.KEYWORD_ONLY


def test_only_the_central_notification_service_passes_a_certificate():
    """No workstation, login, dry-run or execute path references the
    certificate-bearing launch."""
    repo = Path(__file__).resolve().parents[2]
    users = sorted(
        str(path.relative_to(repo)).replace("\\", "/")
        for path in (repo / "mcma").rglob("*.py")
        if "client_certificate=" in path.read_text(encoding="utf-8")
    )
    assert users == ["mcma/app/central_server.py", "mcma/notifications/service.py"]


# ------------------------- real Chromium, loopback ------------------------- #


def _serve_tls_once(context: ssl.SSLContext, seen: list):
    """A tiny HTTPS server on 127.0.0.1 that records the client certificate
    subject (or None) of each connection, answers 200 and keeps serving
    until stopped."""
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.2)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                raw, _ = listener.accept()
            except (TimeoutError, OSError):
                continue
            try:
                with context.wrap_socket(raw, server_side=True) as tls:
                    peer = tls.getpeercert()
                    seen.append(dict(x[0] for x in peer["subject"])["commonName"] if peer else None)
                    tls.recv(65536)
                    tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n"
                                b"Connection: close\r\n\r\nok")
            except (ssl.SSLError, OSError):
                seen.append("handshake-failed")

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return listener.getsockname()[1], stop, listener


@pytest.mark.egress_proof
@pytest.mark.requires_egress_isolation
def test_real_chromium_presents_the_certificate_only_to_the_bound_origin(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization

    ca = factory.make_ca()
    server_key, server_cert = factory.issue(ca, cn="127.0.0.1", eku=(factory.SERVER_AUTH,), san_ips=("127.0.0.1",))
    (tmp_path / "ca.pem").write_bytes(ca[1].public_bytes(serialization.Encoding.PEM))
    (tmp_path / "server.pem").write_bytes(
        server_cert.public_bytes(serialization.Encoding.PEM)
        + server_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption())
    )

    def server_context():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tmp_path / "server.pem")
        context.load_verify_locations(tmp_path / "ca.pem")
        context.verify_mode = ssl.CERT_OPTIONAL
        return context

    bound_seen, other_seen = [], []
    bound_port, stop_bound, bound_listener = _serve_tls_once(server_context(), bound_seen)
    other_port, stop_other, other_listener = _serve_tls_once(server_context(), other_seen)
    # The driver (Node) verifies the server; trust the throwaway CA there.
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", str(tmp_path / "ca.pem"))

    certificate = _certificate(origin=f"https://127.0.0.1:{bound_port}", cn="client-under-test")

    async def scenario():
        async with launch_browser(headless=True, client_certificate=certificate) as browser:
            assert isinstance(browser, ClientCertificateBrowser)
            context = await browser.new_context()
            page = await context.new_page()
            response = await page.goto(f"https://127.0.0.1:{bound_port}/")
            assert response is not None and response.status == 200
            try:
                await page.goto(f"https://127.0.0.1:{other_port}/")
            except Exception:
                pass   # a refusal is acceptable; presenting the certificate is not
            await context.close()

    try:
        asyncio.run(scenario())
    finally:
        stop_bound.set()
        stop_other.set()
        bound_listener.close()
        other_listener.close()
    assert "client-under-test" in bound_seen
    assert "client-under-test" not in other_seen


@pytest.mark.egress_proof
@pytest.mark.requires_egress_isolation
def test_real_chromium_refuses_to_start_with_an_unloadable_certificate():
    """The launch self-test: a bundle the driver cannot load (wrong
    passphrase here) fails at launch, with the fixed message."""
    certificate = _certificate()
    object.__setattr__(certificate, "_passphrase", "not-the-passphrase")

    async def scenario():
        async with launch_browser(headless=True, client_certificate=certificate):
            pass  # pragma: no cover - must not be reached

    with pytest.raises(ClientCertificateError, match="could not load"):
        asyncio.run(scenario())
