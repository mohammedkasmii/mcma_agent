"""An empty alert list means one of two completely different things.

An authenticated account with no open alerts is normal. A session that
silently expired and redirected to a login page produces exactly the same
"no category links" -- and reporting that as NO_CATEGORIES tells the
employee everything is fine while their notifications quietly stop
arriving.

These tests pin the three-way distinction and, just as importantly, that
none of the failure paths ever touches claim presence.
"""

import asyncio

import pytest

from api_test_support import (
    MAMDA_OUJDA,
    NADOR,
    OUJDA,
    conn,  # noqa: F401
    db_path,  # noqa: F401
)
from mcma.notifications import poller as poller_module
from mcma.portal.capabilities import ReadCapability
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST

MAMDA_NADOR = "acct-mamda-nador"


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# The probe itself
# --------------------------------------------------------------------- #


class _StatePage:
    def __init__(self, state):
        self._state = state

    async def evaluate(self, *_args, **_kwargs):
        if isinstance(self._state, Exception):
            raise self._state
        return self._state


def _observe(state):
    reader = ReadCapability(object(), _StatePage(state), DEFAULT_SINAUTO_HOST)
    return _run(reader.observe_session_state())


def test_positive_markers_alone_mean_authenticated():
    assert _observe({"logged_in": True, "logged_out": False}) == "AUTHENTICATED"


@pytest.mark.parametrize("evidence", [
    {"logged_in": False, "logged_out": True},   # login URL / inputs / expert_.phtml
])
def test_recovered_logged_out_evidence_means_logged_out(evidence):
    assert _observe(evidence) == "LOGGED_OUT"


def test_no_evidence_either_way_is_indeterminate():
    assert _observe({"logged_in": False, "logged_out": False}) == "INDETERMINATE"


def test_contradictory_evidence_fails_closed():
    """Guessing AUTHENTICATED hides an expired session; guessing
    LOGGED_OUT revokes a working one. Neither is worth a guess."""
    assert _observe({"logged_in": True, "logged_out": True}) == "INDETERMINATE"


def test_a_page_that_cannot_be_probed_is_indeterminate():
    assert _observe(RuntimeError("page gone")) == "INDETERMINATE"
    assert _observe("not a dict") == "INDETERMINATE"


# --------------------------------------------------------------------- #
# The poll flow
# --------------------------------------------------------------------- #


class _Reader:
    """Scripted session states, one per observe call, plus the codes
    discovery returns."""

    def __init__(self, states, codes=(), discover_error=None):
        self._states = list(states)
        self._codes = codes
        self._discover_error = discover_error
        self.discovered = 0
        self.closed = False

    async def observe_session_state(self):
        return self._states.pop(0) if self._states else "AUTHENTICATED"

    async def discover_notification_categories(self):
        self.discovered += 1
        if self._discover_error is not None:
            raise self._discover_error
        return self._codes

    async def close(self):
        self.closed = True


def _poll_with(conn, monkeypatch, reader, account_id=OUJDA, revoked=None):
    monkeypatch.setattr(poller_module, "load_and_verify_session",
                        lambda *a, **k: b'{"cookies": [], "origins": []}')

    async def _open_reader(*args, **kwargs):
        return reader

    monkeypatch.setattr(poller_module, "open_reader", _open_reader)
    monkeypatch.setattr(poller_module, "run_poll", _forbidden_run_poll)
    if revoked is not None:
        monkeypatch.setattr(poller_module, "revoke_session",
                            lambda conn_, acct, **k: revoked.append(acct))
    return _run(poller_module.poll_one_account(
        conn, object(), account_id, (),
        instance_id="i", allowed_host=DEFAULT_SINAUTO_HOST,
        vault_dir=None, crypto_backend=None, entity="MCMA",
    ))


async def _forbidden_run_poll(*_args, **_kwargs):
    raise AssertionError(
        "run_poll must never be reached on a failed/empty read -- it would "
        "advance the presence lifecycle on evidence that does not exist"
    )


def test_authenticated_with_no_alerts_is_no_categories(conn, monkeypatch):
    revoked = []
    reader = _Reader(["AUTHENTICATED", "AUTHENTICATED"], codes=())
    assert _poll_with(conn, monkeypatch, reader, revoked=revoked) == "NO_CATEGORIES"
    assert revoked == []          # a quiet account is not an expired one
    assert reader.closed is True


def test_a_logged_out_session_is_reconnect_required_and_is_revoked(conn, monkeypatch):
    revoked = []
    reader = _Reader(["LOGGED_OUT"])
    assert _poll_with(conn, monkeypatch, reader, revoked=revoked) == "RECONNECT_REQUIRED"
    assert revoked == [OUJDA]
    # Discovery never ran: there was nothing authenticated to discover.
    assert reader.discovered == 0


def test_an_indeterminate_page_never_revokes_the_session(conn, monkeypatch):
    """A network blip must not log the employee out of an account that is
    probably still perfectly valid."""
    revoked = []
    reader = _Reader(["INDETERMINATE"])
    assert _poll_with(conn, monkeypatch, reader, revoked=revoked) == "PORTAL_UNAVAILABLE"
    assert revoked == []


def test_a_session_that_expires_during_the_alert_read_is_caught(conn, monkeypatch):
    """Valid when the landing page opened, expired by the time the alert
    list came back -- which is exactly when an empty result is most
    misleading. Hence the second probe."""
    revoked = []
    reader = _Reader(["AUTHENTICATED", "LOGGED_OUT"], codes=())
    assert _poll_with(conn, monkeypatch, reader, revoked=revoked) == "RECONNECT_REQUIRED"
    assert revoked == [OUJDA]
    assert reader.discovered == 1


def test_a_session_that_becomes_indeterminate_mid_read_does_not_revoke(conn, monkeypatch):
    revoked = []
    reader = _Reader(["AUTHENTICATED", "INDETERMINATE"], codes=())
    assert _poll_with(conn, monkeypatch, reader, revoked=revoked) == "PORTAL_UNAVAILABLE"
    assert revoked == []


def test_a_read_failure_is_never_treated_as_expiry(conn, monkeypatch):
    """Requirement: do not revoke on arbitrary category failure. A network
    error is not evidence about authentication."""
    revoked = []
    reader = _Reader(["AUTHENTICATED"], discover_error=RuntimeError("connection reset"))
    assert _poll_with(conn, monkeypatch, reader, revoked=revoked) == "PORTAL_UNAVAILABLE"
    assert revoked == []


def test_categories_found_still_proceeds_to_the_fetch_phase(conn, monkeypatch):
    """The happy path must not have been broken by the extra probes: with
    codes present, run_poll IS reached."""
    monkeypatch.setattr(poller_module, "load_and_verify_session",
                        lambda *a, **k: b'{"cookies": [], "origins": []}')
    reader = _Reader(["AUTHENTICATED"], codes=("MISSIONS",))
    readers = [reader, _Reader([])]

    async def _open_reader(*args, **kwargs):
        return readers.pop(0)

    ran = []

    async def _run_poll(conn_, account_id, rdr, codes, version):
        ran.append((account_id, tuple(codes)))
        # run_poll reports (poll_run_id, overall_status): reaching it is
        # not the same as having read anything.
        return "poll-run-1", "COMPLETE"

    monkeypatch.setattr(poller_module, "open_reader", _open_reader)
    monkeypatch.setattr(poller_module, "run_poll", _run_poll)

    outcome = _run(poller_module.poll_one_account(
        conn, object(), OUJDA, (), instance_id="i", allowed_host=DEFAULT_SINAUTO_HOST,
        vault_dir=None, crypto_backend=None, entity="MCMA",
    ))
    assert outcome == "POLLED"
    assert ran == [(OUJDA, ("MISSIONS",))]


# --------------------------------------------------------------------- #
# Presence is never advanced by a failure
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("states,error,expected", [
    (["LOGGED_OUT"], None, "RECONNECT_REQUIRED"),
    (["INDETERMINATE"], None, "PORTAL_UNAVAILABLE"),
    (["AUTHENTICATED", "LOGGED_OUT"], None, "RECONNECT_REQUIRED"),
    (["AUTHENTICATED", "INDETERMINATE"], None, "PORTAL_UNAVAILABLE"),
    (["AUTHENTICATED", "AUTHENTICATED"], None, "NO_CATEGORIES"),
    (["AUTHENTICATED"], RuntimeError("boom"), "PORTAL_UNAVAILABLE"),
])
def test_no_failure_path_ever_advances_presence(conn, monkeypatch, states, error, expected):
    """_forbidden_run_poll raises if reached. None of these outcomes may
    call run_poll with an empty dataset, because that would let a failed
    read resolve real, still-open claims."""
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, "
        "first_seen_version, last_seen_version) VALUES (?, ?, '1', 'STILL-OPEN', 1, 1)",
        (f"{OUJDA}:1", OUJDA),
    )
    reader = _Reader(states, codes=(), discover_error=error)
    monkeypatch.setattr(poller_module, "revoke_session", lambda *a, **k: None)
    assert _poll_with(conn, monkeypatch, reader) == expected
    surviving = conn.execute(
        "SELECT reference FROM claims WHERE account_id = ?", (OUJDA,)
    ).fetchone()
    assert surviving["reference"] == "STILL-OPEN"


# --------------------------------------------------------------------- #
# Account isolation
# --------------------------------------------------------------------- #


def test_one_expired_account_revokes_only_its_own_session(conn, monkeypatch):
    revoked = []
    readers = {
        OUJDA: _Reader(["LOGGED_OUT"]),
        NADOR: _Reader(["AUTHENTICATED", "AUTHENTICATED"], codes=()),
        MAMDA_OUJDA: _Reader(["AUTHENTICATED", "AUTHENTICATED"], codes=()),
        MAMDA_NADOR: _Reader(["INDETERMINATE"]),
    }
    monkeypatch.setattr(poller_module, "load_and_verify_session",
                        lambda *a, **k: b'{"cookies": [], "origins": []}')
    monkeypatch.setattr(poller_module, "run_poll", _forbidden_run_poll)
    monkeypatch.setattr(poller_module, "revoke_session",
                        lambda conn_, acct, **k: revoked.append(acct))

    outcomes = {}
    for account_id, reader in readers.items():
        async def _open_reader(*args, _r=reader, **kwargs):
            return _r

        monkeypatch.setattr(poller_module, "open_reader", _open_reader)
        outcomes[account_id] = _run(poller_module.poll_one_account(
            conn, object(), account_id, (), instance_id="i",
            allowed_host=DEFAULT_SINAUTO_HOST, vault_dir=None,
            crypto_backend=None, entity="MCMA",
        ))

    assert outcomes[OUJDA] == "RECONNECT_REQUIRED"
    assert outcomes[NADOR] == "NO_CATEGORIES"
    assert outcomes[MAMDA_OUJDA] == "NO_CATEGORIES"
    assert outcomes[MAMDA_NADOR] == "PORTAL_UNAVAILABLE"
    # ONLY the expired account's session was revoked.
    assert revoked == [OUJDA]


# --------------------------------------------------------------------- #
# Hostile hrefs
# --------------------------------------------------------------------- #
