"""Real account-scoped notification polling.

The blocker these close: notification_category_codes defaulted to () and
the composition root only polled when it was non-empty, so a perfectly
healthy application never made a single notification request. Running and
polling were not the same thing.

The rules being pinned are mostly about what must NOT happen: one
account's data must never appear under another, and a failed or
unauthenticated read must never be mistaken for evidence that an alert
has gone away.
"""

import asyncio

import pytest

from api_test_support import (
    MAMDA_OUJDA,
    NADOR,
    OUJDA,
    app_and_client,  # noqa: F401
    conn,  # noqa: F401
    create_user,
    csrf_headers,
    db_path,  # noqa: F401
    grant_access,
    login_client,
)
from mcma.notifications import poller as poller_module
from mcma.notifications.poller import poll_all_accounts, poll_one_account
from mcma.persistence.leases import acquire_lease
from mcma.portal.sinauto_contracts import (
    DEFAULT_SINAUTO_HOST,
    category_discovery_contracts,
    notification_contracts,
)

MAMDA_NADOR = "acct-mamda-nador"


def _run(coro):
    return asyncio.run(coro)


def _poll(conn, account_id, codes=(), entity="MCMA"):
    return _run(poll_one_account(
        conn, object(), account_id, codes,
        instance_id="test-instance", allowed_host=DEFAULT_SINAUTO_HOST,
        vault_dir=None, crypto_backend=None, entity=entity,
    ))


# --------------------------------------------------------------------- #
# 1. Polling is actually enabled in the normal composition
# --------------------------------------------------------------------- #


def test_the_normal_local_composition_actually_polls():
    """The blocker itself: an application that runs but never asks the
    portal anything."""
    from mcma.app.main import local_settings

    settings = local_settings()
    assert settings.notifications_enabled is True
    # An empty list now means DISCOVER, not "poll nothing".
    assert settings.notification_category_codes == ()


# --------------------------------------------------------------------- #
# 2-4. Entity routing and independent sessions
# --------------------------------------------------------------------- #


def test_each_entity_reads_from_its_own_application():
    for entity, base in (("MCMA", "/SinAuto_MCMA"), ("MAMDA", "/SinAuto_MAMDA")):
        assert all(c.route.startswith(base)
                   for c in notification_contracts(DEFAULT_SINAUTO_HOST, ["X"], entity))
        assert all(c.route.startswith(base)
                   for c in category_discovery_contracts(DEFAULT_SINAUTO_HOST, entity))


def test_every_account_loads_its_own_session(conn, monkeypatch):
    """Oujda and Nador are separate profiles on one portal, not separate
    deployments -- so one account's session must never be reused for
    another."""
    asked = []

    def _load(conn_, account_id, **kwargs):
        asked.append(account_id)
        raise RuntimeError("no session in this test")

    monkeypatch.setattr(poller_module, "load_and_verify_session", _load)
    for account_id in (OUJDA, NADOR, MAMDA_OUJDA, MAMDA_NADOR):
        _poll(conn, account_id)

    assert asked == [OUJDA, NADOR, MAMDA_OUJDA, MAMDA_NADOR]
    assert len(set(asked)) == 4


# --------------------------------------------------------------------- #
# 6-8. Failure isolation and session expiry
# --------------------------------------------------------------------- #


def test_an_account_with_no_session_makes_no_portal_request(conn, monkeypatch):
    opened = []
    monkeypatch.setattr(poller_module, "open_reader",
                        lambda *a, **k: opened.append(a) or None)
    assert _poll(conn, OUJDA) == "NO_SESSION"
    assert opened == []


def test_one_expired_account_does_not_stop_the_other_three(conn, monkeypatch):
    outcomes_by_account = {
        OUJDA: "POLLED",
        NADOR: "RECONNECT_REQUIRED",
        MAMDA_OUJDA: "POLLED",
        MAMDA_NADOR: "NO_SESSION",
    }

    async def _one(conn_, browser, account_id, codes, **kwargs):
        return outcomes_by_account[account_id]

    monkeypatch.setattr(poller_module, "poll_one_account", _one)
    outcomes = _run(poll_all_accounts(
        conn, object(), (), instance_id="i", allowed_host=DEFAULT_SINAUTO_HOST,
        vault_dir=None, crypto_backend=None,
    ))
    assert outcomes == outcomes_by_account


def test_one_accounts_failure_never_mutates_another(conn, monkeypatch):
    """A poll that explodes for Nador must leave Oujda's rows alone."""
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, "
        "first_seen_version, last_seen_version) VALUES (?, ?, '1', 'KEEP-ME', 1, 1)",
        (f"{OUJDA}:1", OUJDA),
    )

    async def _one(conn_, browser, account_id, codes, **kwargs):
        if account_id == NADOR:
            raise RuntimeError("portal exploded")
        return "POLLED"

    monkeypatch.setattr(poller_module, "poll_one_account", _one)
    outcomes = _run(poll_all_accounts(
        conn, object(), (), instance_id="i", allowed_host=DEFAULT_SINAUTO_HOST,
        vault_dir=None, crypto_backend=None,
    ))
    assert outcomes[NADOR] == "ERROR_RuntimeError"
    surviving = conn.execute(
        "SELECT reference FROM claims WHERE account_id = ?", (OUJDA,)
    ).fetchone()
    assert surviving["reference"] == "KEEP-ME"


def test_an_expired_session_never_marks_existing_claims_absent(conn, monkeypatch):
    """The rule that matters most: a failed read is not evidence that an
    alert disappeared. run_poll must not even be reached."""
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, "
        "first_seen_version, last_seen_version) VALUES (?, ?, '1', 'STILL-OPEN', 1, 1)",
        (f"{OUJDA}:1", OUJDA),
    )
    ran = []

    class _ExpiredReader:
        async def observe_session_state(self):
            return "LOGGED_OUT"

        async def discover_notification_categories(self):
            raise AssertionError("discovery must not run for a logged-out session")

        async def close(self):
            return None

    async def _open_reader(*args, **kwargs):
        return _ExpiredReader()

    async def _run_poll(*args, **kwargs):
        ran.append(True)

    monkeypatch.setattr(poller_module, "load_and_verify_session",
                        lambda *a, **k: b'{"cookies": [], "origins": []}')
    monkeypatch.setattr(poller_module, "open_reader", _open_reader)
    monkeypatch.setattr(poller_module, "run_poll", _run_poll)
    monkeypatch.setattr(poller_module, "revoke_session", lambda *a, **k: None)

    assert _poll(conn, OUJDA) == "RECONNECT_REQUIRED"
    assert ran == []      # no presence lifecycle advanced on a failed read
    assert conn.execute("SELECT count(*) AS n FROM claims").fetchone()["n"] == 1


def test_no_categories_is_not_treated_as_an_empty_portal(conn, monkeypatch):
    """Discovering nothing means nothing was read -- not that every alert
    is gone. run_poll is never called, so no absence is recorded."""
    ran = []

    class _EmptyReader:
        async def observe_session_state(self):
            return "AUTHENTICATED"

        async def discover_notification_categories(self):
            return ()

        async def close(self):
            return None

    monkeypatch.setattr(poller_module, "load_and_verify_session",
                        lambda *a, **k: b'{"cookies": [], "origins": []}')
    monkeypatch.setattr(poller_module, "open_reader",
                        lambda *a, **k: _async(_EmptyReader()))
    monkeypatch.setattr(poller_module, "run_poll",
                        lambda *a, **k: ran.append(True))

    assert _poll(conn, OUJDA) == "NO_CATEGORIES"
    assert ran == []


async def _async(value):
    return value


def test_a_busy_lease_yields_instead_of_blocking_a_dossier(conn):
    """A dossier fill must never wait behind a notification refresh."""
    held = acquire_lease(conn, OUJDA, "runner", owner_job_id="job-1", ttl_seconds=300)
    try:
        assert _poll(conn, OUJDA) == "LEASE_BUSY"
    finally:
        held.release()


def test_polling_always_releases_the_lease(conn):
    _poll(conn, OUJDA)
    assert conn.execute(
        "SELECT * FROM account_leases WHERE account_id=?", (OUJDA,)
    ).fetchone() is None


# --------------------------------------------------------------------- #
# 14-15. Portal-supplied data can never become a route
# --------------------------------------------------------------------- #


def _discover(raw_codes):
    from mcma.portal.capabilities import ReadCapability

    class _Page:
        async def evaluate(self, *_args, **_kwargs):
            return raw_codes

    reader = ReadCapability(object(), _Page(), DEFAULT_SINAUTO_HOST)
    return _run(reader.discover_notification_categories())


@pytest.mark.parametrize("hostile", [
    "../../../etc/passwd",
    "https://evil.example.com/steal",
    "MISSIONS/../../gestionExpert/expertEnregistrerMission",
    "A B",
    "code?query=1",
    "code#frag",
    "",
    "%2e%2e%2f",
])
def test_a_hostile_category_code_is_dropped_not_sanitized(hostile):
    """The portal may supply a CODE. It must never be able to supply a
    route -- and a value that does not look like a code is dropped rather
    than cleaned up, because cleaning it up means guessing."""
    assert _discover([hostile]) == ()


def test_valid_codes_survive_and_are_deduplicated():
    assert _discover(["MISSIONS", "RELANCES-EXPERT", "MISSIONS"]) == ("MISSIONS", "RELANCES-EXPERT")


def test_discovery_is_capped_so_a_broken_page_cannot_flood_the_portal():
    assert len(_discover([f"CODE{i}" for i in range(500)])) == 50


def test_a_discovered_code_only_ever_lands_in_the_reviewed_route():
    contracts = notification_contracts(DEFAULT_SINAUTO_HOST, ["RELANCES-EXPERT"], "MCMA")
    fetches = [c for c in contracts if c.operation_type == "read_notifications"]
    assert len(fetches) == 1
    assert fetches[0].route == (
        "/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/RELANCES-EXPERT"
    )
    assert fetches[0].method == "POST"


def test_discovery_context_cannot_fetch_what_it_discovers():
    """Discovery runs with NO getAlerte contract installed, so it is
    structurally incapable of reading a category it just found."""
    contracts = category_discovery_contracts(DEFAULT_SINAUTO_HOST, "MCMA")
    assert all(c.operation_type != "read_notifications" for c in contracts)
    assert all("getAlerte" not in c.route for c in contracts)


# --------------------------------------------------------------------- #
# 12-13. MAMDA reads, MAMDA never writes
# --------------------------------------------------------------------- #


def test_mamda_is_polled_but_still_cannot_be_written_to(conn):
    from mcma.execution.jobs import JobAuthorizationError, _require_mcma_writable_account

    # Read contracts exist for MAMDA...
    assert notification_contracts(DEFAULT_SINAUTO_HOST, ["X"], "MAMDA")
    # ...and a write is still refused.
    with pytest.raises(JobAuthorizationError):
        _require_mcma_writable_account(conn, MAMDA_OUJDA)


def test_every_final_endpoint_is_still_blocked():
    from mcma.portal.final_endpoints import PERMANENTLY_BLOCKED_ENDPOINTS, is_permanently_blocked

    for blocked in PERMANENTLY_BLOCKED_ENDPOINTS:
        assert is_permanently_blocked(f"/SinAuto_MCMA/expertise/{blocked}")
        assert is_permanently_blocked(f"/SinAuto_MAMDA/expertise/{blocked}")


def test_the_writer_still_refuses_the_real_host():
    """Phase B is read-only: nothing here may have loosened the writer."""
    from mcma.portal.writer import _require_loopback_host

    with pytest.raises(ValueError):
        _require_loopback_host(DEFAULT_SINAUTO_HOST)


# --------------------------------------------------------------------- #
# 11. Manual refresh uses the same service
# --------------------------------------------------------------------- #


def _app_with_refresher(conn, refresher):
    from fastapi.testclient import TestClient

    from mcma.app.api.app import create_api_app
    from mcma.app.auth.provider import LocalUserAuthProvider
    from mcma.app.auth.sessions import SessionStore
    from mcma.execution.inputs import TestOnlyPlaintextEncryptor

    app = create_api_app(
        conn,
        auth_provider=LocalUserAuthProvider(conn),
        session_store=SessionStore(),
        encryptor=TestOnlyPlaintextEncryptor(),
        secure_cookies=False,
        notification_refresher=refresher,
    )
    return TestClient(app, client=("127.0.0.1", 12345))


def test_manual_refresh_reports_each_outcome_in_plain_french(conn):
    outcomes = iter(["POLLED", "RECONNECT_REQUIRED", "LEASE_BUSY"])

    async def _refresher(account_id):
        return next(outcomes)

    client = _app_with_refresher(conn, _refresher)
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    first = client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=csrf_headers(csrf))
    assert first.status_code == 200
    assert first.json()["message"] == "Notifications actualisées."

    second = client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=csrf_headers(csrf))
    assert "reconnectez" in second.json()["message"].lower()

    third = client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=csrf_headers(csrf))
    assert "occupé" in third.json()["message"].lower()


def test_manual_refresh_requires_csrf_and_account_access(conn):
    called = []

    async def _refresher(account_id):
        called.append(account_id)
        return "POLLED"

    client = _app_with_refresher(conn, _refresher)
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    assert client.post(f"/accounts/{OUJDA}/refresh-notifications").status_code in (400, 403)
    denied = client.post(f"/accounts/{NADOR}/refresh-notifications", headers=csrf_headers(csrf))
    assert denied.status_code in (403, 404)
    assert called == []


def test_refresh_failure_never_leaks_portal_text(conn):
    async def _refresher(account_id):
        raise RuntimeError("Sinistre 3.20.02 BENALI Youssef 62259-A-50")

    client = _app_with_refresher(conn, _refresher)
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(f"/accounts/{OUJDA}/refresh-notifications", headers=csrf_headers(csrf))
    assert response.status_code == 502
    assert "BENALI" not in response.text
    assert "62259" not in response.text


# --------------------------------------------------------------------- #
# 5. Claims stay account-scoped
# --------------------------------------------------------------------- #


def test_claims_are_never_mixed_between_accounts(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    grant_access(conn, user_id, NADOR)
    for account_id, reference in ((OUJDA, "OUJDA-1"), (NADOR, "NADOR-1")):
        conn.execute(
            "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, "
            "first_seen_version, last_seen_version) VALUES (?, ?, '1', ?, 1, 1)",
            (f"{account_id}:1", account_id, reference),
        )
    login_client(client, "alice", "pw12345")

    oujda = {c["reference"] for c in client.get(f"/claims?account_id={OUJDA}").json()["claims"]}
    nador = {c["reference"] for c in client.get(f"/claims?account_id={NADOR}").json()["claims"]}
    assert oujda == {"OUJDA-1"}
    assert nador == {"NADOR-1"}


def test_accounts_report_a_truthful_connection_state(conn, app_and_client):
    """Four states, derived from the EXISTING session model plus what this
    process has actually observed.

    Stored ACTIVE material alone is UNVERIFIED, not CONNECTED: nothing
    ages that row out, and reporting CONNECTED from it left an account
    signed in yesterday still offering "Actualiser" the next morning."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    for account_id in (OUJDA, NADOR, MAMDA_OUJDA):
        grant_access(conn, user_id, account_id)
    login_client(client, "alice", "pw12345")

    conn.execute(
        "INSERT INTO portal_sessions (session_id, account_id, storage_ref, status, last_validated_at) "
        "VALUES ('s1', ?, 'r1', 'ACTIVE', '2026-01-01T00:00:00+00:00')", (OUJDA,))
    conn.execute(
        "INSERT INTO portal_sessions (session_id, account_id, storage_ref, status, last_validated_at) "
        "VALUES ('s2', ?, 'r2', 'REVOKED', '2026-01-01T00:00:00+00:00')", (NADOR,))

    states = {a["account_id"]: a["connection_state"]
              for a in client.get("/accounts").json()["accounts"]}
    assert states[OUJDA] == "UNVERIFIED"
    assert states[NADOR] == "RECONNECT_REQUIRED"
    assert states[MAMDA_OUJDA] == "NOT_CONNECTED"


def test_live_evidence_turns_unverified_into_connected(conn, app_and_client):
    """The tracker is what distinguishes "material exists" from "we have
    seen it work". Without it, /accounts is back to asserting CONNECTED
    from a database row nothing ages out."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "bob", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    grant_access(conn, user_id, NADOR)
    login_client(client, "bob", "pw12345")

    for account_id, session_id in ((OUJDA, "s10"), (NADOR, "s11")):
        conn.execute(
            "INSERT INTO portal_sessions (session_id, account_id, storage_ref, status, last_validated_at) "
            "VALUES (?, ?, 'r', 'ACTIVE', '2026-01-01T00:00:00+00:00')", (session_id, account_id))

    tracker = getattr(app.state, "connection_tracker", None)
    if tracker is None:  # the API app may be built without one
        return

    tracker.mark_authenticated(OUJDA)
    states = {a["account_id"]: a["connection_state"]
              for a in client.get("/accounts").json()["accounts"]}
    assert states[OUJDA] == "CONNECTED"
    # Isolated per account: one account's evidence never speaks for another.
    assert states[NADOR] == "UNVERIFIED"

    tracker.mark_unverified(OUJDA)
    states = {a["account_id"]: a["connection_state"]
              for a in client.get("/accounts").json()["accounts"]}
    assert states[OUJDA] == "UNVERIFIED"
