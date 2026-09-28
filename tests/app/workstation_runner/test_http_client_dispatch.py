"""Windows client extension for workstation job dispatch (Phase 1C-A):
RegistryHttpClient.claim_job()/renew_job()/release_job(). No polling worker
or execution handler here -- see http_client.py's own module docstring.
Mirrors test_http_client.py's MockTransport conventions."""

import json

import httpx
import pytest

from mcma.app.workstation_runner.http_client import (
    ClaimedJob, RegistryClaimNotFound, RegistryConnectionError, RegistryHttpClient, RegistryProtocolError,
    RegistryUnauthorized, ReleaseResult, RenewResult,
)

ORIGIN = "https://central.example.local"
SECRET = "mcma_rs_" + "s" * 40
CLAIM_TOKEN = "mcma_ct_" + "t" * 40


def _client(handler, **kwargs):
    return RegistryHttpClient(ORIGIN, transport=httpx.MockTransport(handler), **kwargs)


def _envelope(**overrides) -> dict:
    body = {
        "job_id": "job-1", "mode": "DRY_RUN", "account_id": "acct-mcma-oujda",
        "workflow_name": "RENOUVELLEMENT_CONTRAT", "input_hash": "h" * 64, "generation": 1,
        "lease_expires_at": "2026-01-01T00:02:00+00:00", "claim_token": CLAIM_TOKEN,
        "typed_input": {"claim_id": "C-1"},
    }
    body.update(overrides)
    return body


# ---------------------------------------- claim ---------------------------------------- #


def test_claim_job_sends_only_protocol_and_app_version_with_bearer_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=_envelope())

    client = _client(handler)
    client.claim_job(SECRET)
    assert seen["path"] == "/runner/jobs/claim"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"] == {"protocol_version": 1, "app_version": "1.0.0"}


def test_claim_job_parses_a_valid_envelope():
    client = _client(lambda r: httpx.Response(200, json=_envelope()))
    result = client.claim_job(SECRET)
    assert isinstance(result, ClaimedJob)
    assert result.job_id == "job-1"
    assert result.mode == "DRY_RUN"
    assert result.account_id == "acct-mcma-oujda"
    assert result.generation == 1
    assert result.claim_token == CLAIM_TOKEN
    assert result.typed_input == {"claim_id": "C-1"}


def test_claim_job_204_means_no_eligible_work():
    client = _client(lambda r: httpx.Response(204))
    assert client.claim_job(SECRET) is None


def test_claim_job_401_raises_unauthorized():
    client = _client(lambda r: httpx.Response(401, json={"error": "RUNNER_UNAUTHENTICATED"}))
    with pytest.raises(RegistryUnauthorized):
        client.claim_job(SECRET)


def test_claim_job_connection_failure_raises_connection_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(RegistryConnectionError):
        client.claim_job(SECRET)


@pytest.mark.parametrize("overrides", [
    {"mode": "SOMETHING_ELSE"},
    {"account_id": "acct-mamda-oujda"},
    {"generation": 0},
    {"generation": "1"},
    {"claim_token": "no-prefix"},
    {"claim_token": "mcma_ct_"},                 # bare prefix, no suffix
    {"typed_input": "not-an-object"},
    {"typed_input": ["not", "an", "object"]},
    {"job_id": ""},
    {"lease_expires_at": ""},
])
def test_claim_job_rejects_out_of_bounds_fields(overrides):
    client = _client(lambda r: httpx.Response(200, json=_envelope(**overrides)))
    with pytest.raises(RegistryProtocolError):
        client.claim_job(SECRET)


def test_claim_job_rejects_a_response_with_an_extra_field():
    body = _envelope()
    body["unexpected"] = "value"
    client = _client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(RegistryProtocolError):
        client.claim_job(SECRET)


def test_claim_job_rejects_a_response_missing_a_field():
    body = _envelope()
    del body["claim_token"]
    client = _client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(RegistryProtocolError):
        client.claim_job(SECRET)


def test_claim_job_rejects_a_deeply_nested_typed_input():
    nested = {}
    cursor = nested
    for _ in range(50):
        cursor["next"] = {}
        cursor = cursor["next"]
    client = _client(lambda r: httpx.Response(200, json=_envelope(typed_input=nested)))
    with pytest.raises(RegistryProtocolError):
        client.claim_job(SECRET)


def test_claim_job_rejects_an_oversized_response():
    huge = _envelope(typed_input={"padding": "x" * 300_000})
    client = _client(lambda r: httpx.Response(200, json=huge))
    with pytest.raises(RegistryProtocolError):
        client.claim_job(SECRET)


def test_claimed_job_repr_and_str_never_reveal_the_claim_token_or_typed_input():
    client = _client(lambda r: httpx.Response(200, json=_envelope(typed_input={"secret_field": "SENSITIVE-VALUE"})))
    result = client.claim_job(SECRET)
    assert CLAIM_TOKEN not in repr(result)
    assert CLAIM_TOKEN not in str(result)
    assert "SENSITIVE-VALUE" not in repr(result)
    assert "SENSITIVE-VALUE" not in str(result)


def test_claim_job_never_sends_the_bearer_secret_anywhere_but_the_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert SECRET not in str(request.url)
        return httpx.Response(200, json=_envelope())

    client = _client(handler)
    client.claim_job(SECRET)


# ---------------------------------------- renew ---------------------------------------- #


def test_renew_job_sends_only_claim_token_and_generation_with_bearer_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"lease_expires_at": "2026-01-01T00:04:00+00:00", "server_time": "2026-01-01T00:02:00+00:00"})

    client = _client(handler)
    result = client.renew_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1)
    assert seen["path"] == "/runner/jobs/job-1/renew"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"] == {"claim_token": CLAIM_TOKEN, "generation": 1}
    assert isinstance(result, RenewResult)
    assert result.lease_expires_at == "2026-01-01T00:04:00+00:00"


def test_renew_job_404_raises_claim_not_found():
    client = _client(lambda r: httpx.Response(404, json={"error": "CLAIM_NOT_FOUND"}))
    with pytest.raises(RegistryClaimNotFound):
        client.renew_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1)


def test_renew_job_401_raises_unauthorized():
    client = _client(lambda r: httpx.Response(401, json={"error": "RUNNER_UNAUTHENTICATED"}))
    with pytest.raises(RegistryUnauthorized):
        client.renew_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1)


@pytest.mark.parametrize("body", [
    {"lease_expires_at": "t"},                                  # missing server_time
    {"lease_expires_at": "t", "server_time": "t", "extra": 1},  # unknown field
    {"lease_expires_at": "", "server_time": "t"},               # empty string
])
def test_renew_job_rejects_malformed_responses(body):
    client = _client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(RegistryProtocolError):
        client.renew_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1)


def test_renew_job_connection_failure_raises_connection_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(RegistryConnectionError):
        client.renew_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1)


# --------------------------------------- release --------------------------------------- #


def test_release_job_sends_only_claim_token_generation_and_reason_code():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"status": "RELEASED", "server_time": "2026-01-01T00:02:00+00:00"})

    client = _client(handler)
    result = client.release_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1, reason_code="RUNNER_SHUTDOWN")
    assert seen["path"] == "/runner/jobs/job-1/release"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"] == {"claim_token": CLAIM_TOKEN, "generation": 1, "reason_code": "RUNNER_SHUTDOWN"}
    assert isinstance(result, ReleaseResult)
    assert result.status == "RELEASED"


def test_release_job_rejects_a_reason_code_outside_the_fixed_set_without_a_network_call():
    def handler(request: httpx.Request):
        raise AssertionError("must never reach the network with an invalid reason_code")

    client = _client(handler)
    with pytest.raises(ValueError):
        client.release_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1, reason_code="MADE_UP_REASON")


def test_release_job_404_raises_claim_not_found():
    client = _client(lambda r: httpx.Response(404, json={"error": "CLAIM_NOT_FOUND"}))
    with pytest.raises(RegistryClaimNotFound):
        client.release_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1, reason_code="RUNNER_SHUTDOWN")


def test_release_job_rejects_a_response_whose_status_is_not_released():
    client = _client(lambda r: httpx.Response(200, json={"status": "SOMETHING_ELSE", "server_time": "t"}))
    with pytest.raises(RegistryProtocolError):
        client.release_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1, reason_code="RUNNER_SHUTDOWN")


def test_release_job_connection_failure_raises_connection_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler)
    with pytest.raises(RegistryConnectionError):
        client.release_job(SECRET, job_id="job-1", claim_token=CLAIM_TOKEN, generation=1, reason_code="RUNNER_SHUTDOWN")
