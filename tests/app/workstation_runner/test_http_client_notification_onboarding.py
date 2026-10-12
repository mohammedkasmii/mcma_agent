"""RegistryHttpClient's notification-onboarding transport: claim / renew /
complete / fail. Strict closed response shapes, size bounds, fixed typed
errors. MockTransport only -- never a real network."""

import json

import httpx
import pytest

from mcma.app.workstation_runner.http_client import (
    ClaimedOnboarding, OnboardingCompleteResult, OnboardingFailResult, OnboardingRenewResult,
    RegistryAccountBusy, RegistryClaimNotFound, RegistryConnectionError, RegistryHttpClient, RegistryProtocolError,
    RegistrySessionRejected, RegistryUnauthorized,
)

ORIGIN = "https://central.example.local"
SECRET = "mcma_rs_" + "s" * 40
TOKEN = "mcma_ot_" + "t" * 40
REQUEST_ID = "a" * 32


def _client(handler):
    return RegistryHttpClient(ORIGIN, transport=httpx.MockTransport(handler))


def _claim_body(**overrides) -> dict:
    body = {
        "request_id": REQUEST_ID, "account_id": "acct-mamda-nador", "generation": 2, "claim_token": TOKEN,
        "lease_expires_at": "2026-01-01T00:01:00+00:00", "expires_at": "2026-01-01T00:05:00+00:00",
        "server_time": "2026-01-01T00:00:00+00:00",
    }
    body.update(overrides)
    return body


STATE = {"cookies": [], "origins": []}


# ------------------------------------------- claim ------------------------------------------- #


def test_claim_sends_only_versions_with_bearer_and_parses_all_four_accounts():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=_claim_body())

    result = _client(handler).claim_notification_onboarding(SECRET)
    assert seen["path"] == "/runner/notification-onboarding/claim"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"] == {"protocol_version": 1, "app_version": "1.0.0"}
    assert isinstance(result, ClaimedOnboarding)
    assert result.account_id == "acct-mamda-nador" and result.generation == 2
    assert TOKEN not in repr(result)  # claim token never reaches repr/log


@pytest.mark.parametrize("account", ["acct-mcma-oujda", "acct-mcma-nador", "acct-mamda-oujda", "acct-mamda-nador"])
def test_claim_accepts_each_canonical_notification_account(account):
    client = _client(lambda r: httpx.Response(200, json=_claim_body(account_id=account)))
    assert client.claim_notification_onboarding(SECRET).account_id == account


def test_claim_204_means_nothing_pending():
    assert _client(lambda r: httpx.Response(204)).claim_notification_onboarding(SECRET) is None


@pytest.mark.parametrize("override", [
    {"account_id": "acct-other"}, {"account_id": 5}, {"request_id": "xyz"}, {"request_id": "A" * 32},
    {"generation": 0}, {"generation": True}, {"claim_token": "mcma_ct_" + "t" * 40}, {"claim_token": "mcma_ot_"},
    {"claim_token": "mcma_ot_" + "t" * 300}, {"lease_expires_at": ""}, {"expires_at": 5}, {"server_time": None},
])
def test_claim_rejects_malformed_fields(override):
    client = _client(lambda r: httpx.Response(200, json=_claim_body(**override)))
    with pytest.raises(RegistryProtocolError):
        client.claim_notification_onboarding(SECRET)


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_claim_rejects_unknown_or_missing_fields(mutation):
    body = _claim_body()
    if mutation == "extra":
        body["extra"] = 1
    else:
        del body["expires_at"]
    with pytest.raises(RegistryProtocolError):
        _client(lambda r: httpx.Response(200, json=body)).claim_notification_onboarding(SECRET)


def test_claim_401_unauthorized_and_transport_failure():
    with pytest.raises(RegistryUnauthorized):
        _client(lambda r: httpx.Response(401, json={"error": "RUNNER_UNAUTHENTICATED"})).claim_notification_onboarding(SECRET)

    def boom(request):
        raise httpx.ConnectError("secret detail")

    with pytest.raises(RegistryConnectionError) as info:
        _client(boom).claim_notification_onboarding(SECRET)
    assert "secret detail" not in str(info.value)


def test_claim_response_too_large_is_refused():
    big = _claim_body(request_id=REQUEST_ID)
    big["pad"] = "x" * 300_000
    with pytest.raises(RegistryProtocolError):
        _client(lambda r: httpx.Response(200, json=big)).claim_notification_onboarding(SECRET)


# ------------------------------------------- renew -------------------------------------------- #


def test_renew_sends_phase_and_parses_closed_shape():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"lease_expires_at": "t1", "server_time": "t0", "cancel_requested": False})

    result = _client(handler).renew_notification_onboarding(
        SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=2, phase="WAITING_FOR_LOGIN",
    )
    assert seen["path"] == f"/runner/notification-onboarding/{REQUEST_ID}/renew"
    assert seen["body"] == {"claim_token": TOKEN, "generation": 2, "phase": "WAITING_FOR_LOGIN"}
    assert result == OnboardingRenewResult(lease_expires_at="t1", server_time="t0", cancel_requested=False)


@pytest.mark.parametrize("body", [
    {"lease_expires_at": "t1", "server_time": "t0"},
    {"lease_expires_at": "t1", "server_time": "t0", "cancel_requested": "no"},
    {"lease_expires_at": "t1", "server_time": "t0", "cancel_requested": False, "x": 1},
])
def test_renew_rejects_bad_shape(body):
    with pytest.raises(RegistryProtocolError):
        _client(lambda r: httpx.Response(200, json=body)).renew_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, phase="WINDOW_OPENED",
        )


def test_renew_rejects_unknown_phase_without_sending_and_bad_request_id():
    def handler(request):
        raise AssertionError("must not send")

    c = _client(handler)
    with pytest.raises(ValueError):
        c.renew_notification_onboarding(SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, phase="X")
    with pytest.raises(ValueError):
        c.renew_notification_onboarding(
            SECRET, request_id="../jobs", claim_token=TOKEN, generation=1, phase="WINDOW_OPENED",
        )


def test_renew_404_claim_not_found_is_typed():
    client = _client(lambda r: httpx.Response(404, json={"error": "CLAIM_NOT_FOUND"}))
    with pytest.raises(RegistryClaimNotFound):
        client.renew_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, phase="WINDOW_OPENED",
        )


# ------------------------------------------ complete ------------------------------------------ #


def test_complete_uploads_storage_state_once_serialized_over_bearer():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"status": "SUCCEEDED", "server_time": "t"})

    state = {"cookies": [{"name": "a", "value": "COOKIE-MARKER"}], "origins": []}
    result = _client(handler).complete_notification_onboarding(
        SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=3, storage_state=state,
    )
    assert seen["path"] == f"/runner/notification-onboarding/{REQUEST_ID}/complete"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"] == {"claim_token": TOKEN, "generation": 3, "storage_state": state}
    assert result == OnboardingCompleteResult(status="SUCCEEDED", server_time="t")


def test_complete_refuses_oversized_state_before_any_network_call():
    def handler(request):
        raise AssertionError("must not send")

    state = {"cookies": [{"name": "a", "value": "v" * 600_000}], "origins": []}
    with pytest.raises(RegistryProtocolError):
        _client(handler).complete_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, storage_state=state,
        )


def test_complete_refuses_non_finite_and_non_dict_state_without_echoing_it():
    def handler(request):
        raise AssertionError("must not send")

    c = _client(handler)
    with pytest.raises(RegistryProtocolError) as info:
        c.complete_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1,
            storage_state={"cookies": [{"expires": float("nan"), "value": "SECRET-MARKER"}]},
        )
    assert "SECRET-MARKER" not in str(info.value)
    with pytest.raises(RegistryProtocolError):
        c.complete_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, storage_state="not a dict",
        )


@pytest.mark.parametrize("status,error,exc", [
    (409, "ACCOUNT_BUSY", RegistryAccountBusy),
    (422, "SESSION_REJECTED", RegistrySessionRejected),
    (404, "CLAIM_NOT_FOUND", RegistryClaimNotFound),
    (401, "RUNNER_UNAUTHENTICATED", RegistryUnauthorized),
])
def test_complete_maps_fixed_error_codes(status, error, exc):
    client = _client(lambda r: httpx.Response(status, json={"error": error}))
    with pytest.raises(exc):
        client.complete_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, storage_state=STATE,
        )


def test_complete_other_status_is_a_generic_protocol_error_and_bad_status_value_rejected():
    c = _client(lambda r: httpx.Response(500, json={"error": "X"}))
    with pytest.raises(RegistryProtocolError):
        c.complete_notification_onboarding(SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, storage_state=STATE)
    c = _client(lambda r: httpx.Response(200, json={"status": "FAILED", "server_time": "t"}))
    with pytest.raises(RegistryProtocolError):
        c.complete_notification_onboarding(SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, storage_state=STATE)


# -------------------------------------------- fail -------------------------------------------- #


@pytest.mark.parametrize("reason", [
    "LOGIN_TIMED_OUT", "LOGIN_WINDOW_CLOSED", "LOGIN_PAGE_UNREACHABLE", "UPLOAD_FAILED", "RUNNER_SHUTDOWN",
    "CANCELLED", "INTERNAL_ERROR", "RUNNER_BUSY",
])
def test_fail_sends_closed_reason_and_parses(reason):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"status": "CANCELLED", "server_time": "t"})

    result = _client(handler).fail_notification_onboarding(
        SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, reason_code=reason,
    )
    assert seen["body"] == {"claim_token": TOKEN, "generation": 1, "reason_code": reason}
    assert result == OnboardingFailResult(status="CANCELLED", server_time="t")


def test_fail_rejects_free_text_reason_client_side_and_bad_status_server_side():
    def handler(request):
        raise AssertionError("must not send")

    with pytest.raises(ValueError):
        _client(handler).fail_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, reason_code="free text",
        )
    c = _client(lambda r: httpx.Response(200, json={"status": "SUCCEEDED", "server_time": "t"}))
    with pytest.raises(RegistryProtocolError):
        c.fail_notification_onboarding(
            SECRET, request_id=REQUEST_ID, claim_token=TOKEN, generation=1, reason_code="INTERNAL_ERROR",
        )
