"""The workstation's share of the supervised Mode Normal golden canary.

The runner has NO setting of its own that could enable the canary: it only
follows the execution profile the central server puts on an EXECUTE claim
envelope, and that key is accepted only as the one known value on an
EXECUTE envelope. DRY_RUN envelopes are unchanged."""

import inspect

import httpx
import pytest

from mcma.app.workstation_runner import app as runner_app
from mcma.app.workstation_runner import protocol
from mcma.app.workstation_runner.http_client import RegistryHttpClient, RegistryProtocolError
from mcma.planning import canary as planning_canary

ORIGIN = "https://central.example.local"
SECRET = "mcma_rs_" + "s" * 40
CLAIM_TOKEN = "mcma_ct_" + "t" * 40
PROFILE = "MODE_NORMAL_GOLDEN_CANARY"


def _client(body):
    return RegistryHttpClient(ORIGIN, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))


def _envelope(**overrides) -> dict:
    body = {
        "job_id": "job-1", "mode": "EXECUTE", "account_id": "acct-mcma-oujda",
        "workflow_name": "mission_normal", "input_hash": "h" * 64, "generation": 1,
        "lease_expires_at": "2026-01-01T00:02:00+00:00", "claim_token": CLAIM_TOKEN,
        "typed_input": {"claim_id": "C-1"},
    }
    body.update(overrides)
    return body


def test_profile_literal_matches_the_server():
    assert protocol.EXECUTION_PROFILE_MODE_NORMAL_GOLDEN_CANARY == planning_canary.EXECUTION_PROFILE_MODE_NORMAL_GOLDEN_CANARY


def test_execute_envelope_with_the_canary_profile_is_parsed():
    claimed = _client(_envelope(execution_profile=PROFILE)).claim_job(SECRET)
    assert claimed.execution_profile == PROFILE


def test_envelopes_without_a_profile_are_unchanged():
    assert _client(_envelope()).claim_job(SECRET).execution_profile is None
    assert _client(_envelope(mode="DRY_RUN")).claim_job(SECRET).execution_profile is None


@pytest.mark.parametrize("overrides", [
    {"mode": "DRY_RUN", "execution_profile": PROFILE},       # never on a DRY_RUN
    {"execution_profile": "GENERIC_LIVE_WRITE"},             # unknown profile
    {"execution_profile": None},
    {"execution_profile": PROFILE.lower()},
])
def test_any_other_profile_shape_is_a_protocol_violation(overrides):
    with pytest.raises(RegistryProtocolError):
        _client(_envelope(**overrides)).claim_job(SECRET)


def test_runner_config_has_no_canary_switch():
    from mcma.app.workstation_runner import config

    assert "canary" not in inspect.getsource(config).lower()


def test_composition_routes_only_the_canary_profile_to_the_canary_adapter():
    source = inspect.getsource(runner_app)
    assert "run_mode_normal_golden_canary" in source
    assert "EXECUTION_PROFILE_MODE_NORMAL_GOLDEN_CANARY" in source
    # The generic EXECUTE path still uses the loopback pilot host/contracts.
    assert "pilot_allowed_host(DEFAULT_PILOT_HOST)" in source
    assert "pilot_write_contracts(_execute_allowed_host)" in source
