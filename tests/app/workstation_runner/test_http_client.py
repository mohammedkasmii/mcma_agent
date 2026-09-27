import datetime
import json
import ssl

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from mcma.app.workstation_runner.http_client import (
    RegistryConnectionError, RegistryHttpClient, RegistryProtocolError, RegistryUnauthorized,
    _build_ssl_context, _valid_account_ids,
)

ORIGIN = "https://central.example.local"


def _self_signed_ca_pem(common_name: str) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def _client(handler, **kwargs):
    return RegistryHttpClient(ORIGIN, transport=httpx.MockTransport(handler), **kwargs)


def test_enroll_success_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/runner/enroll"
        payload = json.loads(request.read())
        assert payload == {
            "pairing_code": "mcma_pc_abc", "runner_label": "Poste-1",
            "protocol_version": 1, "app_version": "1.0.0",
        }
        return httpx.Response(201, json={
            "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40,
            "runner_label": "Poste-1", "allowed_account_ids": ["acct-mcma-oujda"],
            "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
            "server_time": "2026-01-01T00:00:00+00:00",
        })

    client = _client(handler)
    result = client.enroll("mcma_pc_abc", workstation_label="Poste-1")
    assert result.runner_id == "a" * 32
    assert result.runner_secret == "mcma_rs_" + "b" * 40
    assert result.allowed_account_ids == ("acct-mcma-oujda",)
    assert result.heartbeat_interval_seconds == 10


def test_enroll_never_sends_pairing_code_in_url_or_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(201, json={
            "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40,
            "runner_label": "Poste-1", "allowed_account_ids": [],
            "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
            "server_time": "2026-01-01T00:00:00+00:00",
        })

    client = _client(handler)
    client.enroll("mcma_pc_super-secret", workstation_label="Poste-1")
    assert "super-secret" not in seen["url"]
    assert "super-secret" not in "".join(seen["headers"].values())
    assert "authorization" not in seen["headers"]


def test_enroll_non_201_raises_protocol_error():
    client = _client(lambda r: httpx.Response(400, json={"error": "PAIRING_CODE_INVALID"}))
    with pytest.raises(RegistryProtocolError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


def test_enroll_connection_failure_raises_connection_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(RegistryConnectionError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


@pytest.mark.parametrize("bad_response", [
    {"runner_id": "not-hex!!", "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
     "allowed_account_ids": [], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
     "server_time": "t"},
    {"runner_id": "a" * 32, "runner_secret": "no-prefix", "runner_label": "x",
     "allowed_account_ids": [], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
     "server_time": "t"},
    {"runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
     "allowed_account_ids": ["acct-mamda"], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
     "server_time": "t"},
    {"runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
     "allowed_account_ids": [], "heartbeat_interval_seconds": 0, "offline_after_seconds": 30,
     "server_time": "t"},
    {"runner_id": "a" * 32, "runner_secret": "mcma_rs_", "runner_label": "x",  # prefix with NO suffix
     "allowed_account_ids": [], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
     "server_time": "t"},
])
def test_enroll_rejects_out_of_bounds_response(bad_response):
    client = _client(lambda r: httpx.Response(201, json=bad_response))
    with pytest.raises(RegistryProtocolError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


def test_heartbeat_sends_bearer_header_and_defaults_to_an_empty_sessions_list():
    """RELEASE BLOCKER 3: Phase 1B-A has no browser sessions to report --
    the default `sessions=()` must produce an EMPTY sessions list, never a
    resend of allowed_account_ids as {"state": "NOT_CONFIGURED"} entries
    (the real registry rejects the whole heartbeat with ACCOUNT_NOT_ALLOWED
    the moment any of those accounts is no longer allowed)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={
            "status": "ACTIVE", "server_time": "t", "heartbeat_interval_seconds": 10,
            "offline_after_seconds": 30, "allowed_account_ids": ["acct-mcma-oujda"],
        })

    client = _client(handler)
    result = client.heartbeat("mcma_rs_" + "s" * 40)
    assert seen["auth"] == "Bearer mcma_rs_" + "s" * 40
    assert seen["body"]["sessions"] == []
    assert result.status == "ACTIVE"
    assert result.allowed_account_ids == ("acct-mcma-oujda",)  # informational only, never re-sent


def test_heartbeat_rejects_a_session_naming_an_unknown_account():
    client = _client(lambda r: httpx.Response(200, json={
        "status": "ACTIVE", "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
        "allowed_account_ids": [],
    }))
    with pytest.raises(ValueError):
        client.heartbeat("mcma_rs_" + "s" * 40, sessions=({"account_id": "acct-mamda", "state": "READY"},))


def test_enroll_rejects_a_non_object_json_body():
    """Regression: response.json() was passed straight to body.get(...)
    without checking it was actually a dict -- a 200/201 with a JSON array
    or scalar raised AttributeError instead of the documented
    RegistryProtocolError."""
    client = _client(lambda r: httpx.Response(201, json=["not", "an", "object"]))
    with pytest.raises(RegistryProtocolError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


def test_heartbeat_401_raises_unauthorized():
    client = _client(lambda r: httpx.Response(401, json={"error": "RUNNER_UNAUTHENTICATED"}))
    with pytest.raises(RegistryUnauthorized):
        client.heartbeat("mcma_rs_" + "s" * 40)


def test_enroll_does_not_persist_cookies_across_calls():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("cookie"))
        headers = {"Set-Cookie": "sid=abc; Path=/"} if len(calls) == 1 else {}
        return httpx.Response(201, json={
            "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
            "allowed_account_ids": [], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
            "server_time": "t",
        }, headers=headers)

    client = _client(handler)
    client.enroll("mcma_pc_x", workstation_label="Poste-1")
    client.enroll("mcma_pc_y", workstation_label="Poste-1")
    assert calls == [None, None]


def test_client_passes_an_explicit_sslcontext_not_verify_true_or_a_string(monkeypatch):
    """Regression: httpx's verify=True builds
    ssl.create_default_context(cafile=certifi.where()) -- certifi's bundled
    CA list, never the Windows CurrentUser/LocalMachine certificate store.
    A CA imported into the OS trust store would be silently ignored."""
    captured = {}
    original_init = httpx.Client.__init__

    def spy_init(self, *args, **kwargs):
        captured["verify"] = kwargs.get("verify")
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", spy_init)
    RegistryHttpClient(ORIGIN)
    assert isinstance(captured["verify"], ssl.SSLContext)


def test_build_ssl_context_without_ca_file_keeps_hostname_and_cert_verification():
    ctx = _build_ssl_context(None)
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_build_ssl_context_with_ca_file_loads_exactly_that_ca(tmp_path):
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(_self_signed_ca_pem("Test Runner CA"))
    ctx = _build_ssl_context(ca_path)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    loaded = ctx.get_ca_certs()
    assert any(
        any(rdn == (("commonName", "Test Runner CA"),) for rdn in cert["subject"])
        for cert in loaded
    )


def test_build_ssl_context_rejects_an_invalid_ca_file_with_a_fixed_message(tmp_path):
    bad_ca = tmp_path / "not-a-cert.pem"
    bad_ca.write_text("this is not a certificate")
    with pytest.raises(ValueError) as excinfo:
        _build_ssl_context(bad_ca)
    assert str(bad_ca) not in str(excinfo.value)  # never the filesystem path
    assert "not-a-cert" not in str(excinfo.value)


@pytest.mark.parametrize("value", [
    [{}],                                    # unhashable entry -- set(value) used to raise TypeError
    [[]],                                    # unhashable entry
    [None],                                  # wrong type, but hashable -- must still be rejected cleanly
    [1, 2],                                  # ints, hashable but not strings
    ["acct-mcma-oujda", {}],                 # mixed valid/invalid
    ["acct-mcma-oujda", "acct-mcma-oujda"],  # duplicate
    ["acct-mamda"],                          # well-formed string, but not an allowed account
    ["acct-mcma-oujda", "acct-mcma-nador", "acct-mcma-oujda"],  # too many + duplicate
    "acct-mcma-oujda",                       # not a list at all
    {"acct-mcma-oujda": True},               # not a list at all
])
def test_valid_account_ids_rejects_malformed_values_without_raising(value):
    """RELEASE FOLLOW-UP: the old implementation called set(value) BEFORE
    checking each entry was a string, so an unhashable entry (a dict or a
    list) raised a raw TypeError instead of being rejected cleanly."""
    assert _valid_account_ids(value) is None


@pytest.mark.parametrize("value", [
    [],
    ["acct-mcma-oujda"],
    ["acct-mcma-oujda", "acct-mcma-nador"],
])
def test_valid_account_ids_accepts_well_formed_values(value):
    assert _valid_account_ids(value) == tuple(value)


def test_enroll_response_with_malformed_account_ids_raises_protocol_error_not_typeerror():
    client = _client(lambda r: httpx.Response(201, json={
        "runner_id": "a" * 32, "runner_secret": "mcma_rs_" + "b" * 40, "runner_label": "x",
        "allowed_account_ids": [{}], "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
        "server_time": "t",
    }))
    with pytest.raises(RegistryProtocolError):
        client.enroll("mcma_pc_x", workstation_label="Poste-1")


def test_heartbeat_response_with_malformed_account_ids_raises_protocol_error_not_typeerror():
    """Heartbeat-level proof that a malformed allowed_account_ids in the
    server's response can never terminate the call with a raw TypeError."""
    client = _client(lambda r: httpx.Response(200, json={
        "status": "ACTIVE", "heartbeat_interval_seconds": 10, "offline_after_seconds": 30,
        "allowed_account_ids": [[]],
    }))
    with pytest.raises(RegistryProtocolError):
        client.heartbeat("mcma_rs_" + "s" * 40)


def test_client_disables_redirects():
    client = RegistryHttpClient(ORIGIN)
    assert client._client.follow_redirects is False


def test_client_disables_environment_proxy_trust():
    client = RegistryHttpClient(ORIGIN)
    assert client._client._trust_env is False


def test_client_rejects_non_https_origin():
    with pytest.raises(ValueError):
        RegistryHttpClient("http://central.example.local")


def test_client_rejects_ca_cert_that_does_not_exist(tmp_path):
    with pytest.raises(ValueError):
        RegistryHttpClient(ORIGIN, ca_cert_path=tmp_path / "missing.pem")


@pytest.mark.parametrize("bad_origin", [
    "https://central.example.local:99999",   # port out of range
    "https://central.example.local:notaport",
])
def test_client_rejects_malformed_port_without_raw_valueerror_leaking(bad_origin):
    """Regression: urlsplit(...).port raises ValueError lazily on an
    out-of-range or non-numeric port; that used to escape _validate_origin
    uncaught with Python's raw message instead of the client's own
    fixed-message ValueError."""
    with pytest.raises(ValueError):
        RegistryHttpClient(bad_origin)
