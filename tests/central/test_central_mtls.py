"""Central server x SinAuto mTLS: the certificate is loaded once at startup,
fails closed, and reaches the notification browser launch -- and nothing
else. The local composition's notification service is unchanged."""

import asyncio
import datetime as dt
import logging

import pytest

import mcma.notifications.service as service_module
from central_test_support import FakeLauncher, central_settings
from client_cert_factory import TEST_PASSPHRASE, issue, make_ca, pack, write_owner_only
from mcma.app.central_server import create_central_server
from mcma.core.central_config import CentralConfigurationError
from mcma.core.client_certificate import SinautoClientCertificate
from mcma.notifications.service import NotificationService


def _server(tmp_path, monkeypatch, **overrides):
    fake = FakeLauncher()
    monkeypatch.setattr(service_module, "launch_browser", fake)
    return create_central_server(central_settings(tmp_path, **overrides), _test_only_portable_mutex=True), fake


def test_the_notification_browser_is_launched_with_the_certificate(tmp_path, monkeypatch):
    server, fake = _server(tmp_path, monkeypatch)
    try:
        asyncio.run(server.notification_service.start())
        (certificate,) = fake.client_certificates
        assert isinstance(certificate, SinautoClientCertificate)
        assert certificate.origin == "https://sinauto.mamda-mcma.ma"
        assert fake.launches[0].headless is True
    finally:
        asyncio.run(server.notification_service.stop())
        server.close()


def test_every_relaunch_carries_the_certificate(tmp_path, monkeypatch):
    fake = FakeLauncher(fail_times=1)
    monkeypatch.setattr(service_module, "launch_browser", fake)
    server = create_central_server(central_settings(tmp_path), _test_only_portable_mutex=True)
    try:
        service = server.notification_service
        asyncio.run(service.start())                       # fails once (DEGRADED)
        asyncio.run(service.poll_if_due(service_module.BROWSER_RETRY_SECONDS))   # relaunch
        assert len(fake.client_certificates) == 2
        assert all(c is not None and c.origin == "https://sinauto.mamda-mcma.ma" for c in fake.client_certificates)
    finally:
        asyncio.run(server.notification_service.stop())
        server.close()


def test_the_local_notification_service_launch_is_unchanged(tmp_path, monkeypatch):
    """No certificate -> launch_browser(headless=True) exactly as before; a
    launcher with the OLD signature (headless only) still works."""
    calls = []

    class _Ctx:
        async def __aenter__(self):
            class _B:
                def is_connected(self):
                    return True
            return _B()

        async def __aexit__(self, *exc):
            return None

    def old_signature_launcher(*, headless=False):
        calls.append(headless)
        return _Ctx()

    monkeypatch.setattr(service_module, "launch_browser", old_signature_launcher)
    service = NotificationService(None, central_settings(tmp_path), crypto_backend=None)
    asyncio.run(service.start())
    assert calls == [True]
    asyncio.run(service.stop())


def _refused(tmp_path, monkeypatch, **overrides):
    fake = FakeLauncher()
    monkeypatch.setattr(service_module, "launch_browser", fake)
    with pytest.raises(CentralConfigurationError) as info:
        create_central_server(central_settings(tmp_path, **overrides), _test_only_portable_mutex=True)
    assert fake.launches == []
    return " | ".join(info.value.problems), info.value


def test_a_missing_bundle_refuses_startup(tmp_path, monkeypatch):
    problems, _ = _refused(tmp_path, monkeypatch, sinauto_client_pfx_path=tmp_path / "absent.p12")
    assert "client certificate bundle not found" in problems


def test_a_wrong_passphrase_refuses_startup_without_leaking_it(tmp_path, monkeypatch, caplog):
    wrong = "a-wrong-passphrase-123"
    secret = tmp_path / "wrong.pass"
    write_owner_only(secret, wrong.encode())
    with caplog.at_level(logging.DEBUG):
        problems, exc = _refused(tmp_path, monkeypatch, sinauto_client_passphrase_path=secret)
    assert "could not be opened" in problems
    for text in (problems, repr(exc), caplog.text):
        assert wrong not in text and TEST_PASSPHRASE not in text
    assert exc.__cause__ is None


def test_an_expired_certificate_refuses_startup(tmp_path, monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    key, cert = issue(make_ca(), not_before=now - dt.timedelta(days=9), not_after=now - dt.timedelta(days=1))
    pfx = write_owner_only(tmp_path / "expired.p12", pack(key, cert))
    problems, _ = _refused(tmp_path, monkeypatch, sinauto_client_pfx_path=pfx)
    assert "expired" in problems


@pytest.mark.parametrize(("name", "value"), [
    ("DEBUG", "pw:protocol"), ("DEBUG", "pw:channel,pw:api"), ("HTTPS_PROXY", "http://proxy:3128"),
    ("https_proxy", "http://proxy:3128"), ("ALL_PROXY", "socks5://proxy:1080"),
])
def test_environment_that_would_leak_or_divert_refuses_startup(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    problems, _ = _refused(tmp_path, monkeypatch)
    assert name in problems and value not in problems


def test_a_refused_start_acquires_nothing(tmp_path, monkeypatch):
    """The certificate is checked before the instance lock: a fixed
    configuration starts immediately afterwards."""
    _refused(tmp_path, monkeypatch, sinauto_client_pfx_path=tmp_path / "absent.p12")
    server, _ = _server(tmp_path, monkeypatch)
    server.close()


def test_startup_logs_only_public_metadata(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        server, _ = _server(tmp_path, monkeypatch)
    server.close()
    assert "SinAuto client certificate loaded for https://sinauto.mamda-mcma.ma" in caplog.text
    assert TEST_PASSPHRASE not in caplog.text


def test_an_expiring_certificate_is_warned_about(tmp_path, monkeypatch, caplog):
    now = dt.datetime.now(dt.timezone.utc)
    key, cert = issue(make_ca(), not_after=now + dt.timedelta(days=5))
    pfx = write_owner_only(tmp_path / "soon.p12", pack(key, cert))
    with caplog.at_level(logging.WARNING):
        server, _ = _server(tmp_path, monkeypatch, sinauto_client_pfx_path=pfx)
    server.close()
    assert "expires on" in caplog.text and TEST_PASSPHRASE not in caplog.text


def test_a_refused_client_certificate_is_logged_as_a_fixed_reason(caplog):
    from mcma.notifications.poller import _log_unavailable

    class PortalError(Exception):
        pass

    with caplog.at_level(logging.WARNING):
        _log_unavailable("discovery reader could not open", exc=PortalError(
            "page.goto: net::ERR_BAD_SSL_CLIENT_AUTH_CERT at https://sinauto.mamda-mcma.ma/SinAuto_MCMA/?u=jdoe"))
        _log_unavailable("discovery reader could not open", exc=PortalError("net::ERR_TIMED_OUT jdoe"))
    assert "the portal rejected the TLS client certificate" in caplog.text
    assert "PortalError" in caplog.text
    assert "jdoe" not in caplog.text
