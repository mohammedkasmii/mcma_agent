"""mcma.app.workstation_runner.protocol deliberately duplicates the server's
wire-protocol constants as literals (see protocol.py's module docstring) to
keep the fresh-process import-isolation guarantee. This test is the
tripwire for that duplication: it imports the REAL server registry module
and asserts every duplicated value is byte-for-byte identical. A failure
here means the client and server have drifted -- fix protocol.py, don't
import the registry module from the client."""

from mcma.app.runners import registry
from mcma.app.workstation_runner import protocol


def test_runner_account_ids_match_the_server():
    assert protocol.RUNNER_ACCOUNT_IDS == registry.RUNNER_ACCOUNT_IDS


def test_session_states_match_the_server():
    assert protocol.SESSION_STATES == registry.SESSION_STATES


def test_session_state_not_configured_is_a_real_server_session_state():
    assert protocol.SESSION_STATE_NOT_CONFIGURED in registry.SESSION_STATES


def test_runner_secret_prefix_matches_the_server():
    assert protocol.RUNNER_SECRET_PREFIX == registry.RUNNER_SECRET_PREFIX


def test_max_runner_secret_length_matches_the_server():
    assert protocol.MAX_RUNNER_SECRET_LENGTH == registry.MAX_RUNNER_SECRET_LENGTH


def test_protocol_version_is_supported_by_the_server():
    assert protocol.PROTOCOL_VERSION in registry.SUPPORTED_PROTOCOL_VERSIONS


def test_app_version_matches_the_servers_version_regex():
    assert registry._VERSION_RE.match(protocol.APP_VERSION)
