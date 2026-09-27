"""(1) The admin PAGE (/administration/users) and the admin API
(/admin/users) no longer collide, proved with the REAL API app plus
mount_frontend. (2) The /events stream ends when the session or the user is
gone, without ever refreshing the session's idle timer."""

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_test_support import (  # noqa: F401
    NADOR, OUJDA, conn, create_user, csrf_headers, db_path, grant_access, login_client,
)
from mcma.app.api.app import create_api_app
from mcma.app.auth.provider import LocalUserAuthProvider
from mcma.app.auth.sessions import SESSION_COOKIE_NAME, SessionStore
from mcma.app.frontend import SPA_ROUTES, mount_frontend
from mcma.app.sse import SESSION_ENDED_EVENT, stream_events
from mcma.execution.inputs import TestOnlyPlaintextEncryptor

PASSWORD = "correct horse battery"
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture()
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text('<!doctype html><html lang="fr"><body><div id="root"></div></body></html>', encoding="utf-8")
    (root / "favicon.ico").write_bytes(b"ico")
    return root


def _real_app(conn, dist=None, store=None):
    store = store or SessionStore()
    app = create_api_app(conn, auth_provider=LocalUserAuthProvider(conn), session_store=store,
                         encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=True)
    if dist is not None:
        mount_frontend(app, dist_dir=dist)          # the same order the composition root uses
    return app, store


def _client(app):
    return TestClient(app, base_url="https://testserver", client=("203.0.113.9", 4000))


# ------------------------------ route collision ------------------------------------ #


def test_the_admin_page_and_the_admin_api_have_different_addresses():
    assert "/administration/users" in SPA_ROUTES and "/admin/users" not in SPA_ROUTES


def test_the_page_serves_index_html_and_the_api_stays_json_on_the_real_app(conn, dist):
    create_user(conn, "boss", PASSWORD, "admin")
    app, _ = _real_app(conn, dist)
    client = _client(app)

    # A refresh of the administrator page, unauthenticated or not, is the SPA.
    for _ in range(2):
        page = client.get("/administration/users")
        assert page.status_code == 200 and 'id="root"' in page.text
        assert page.headers["content-type"].startswith("text/html")

    # The API on the old address is untouched: 401 JSON without a session ...
    unauthenticated = client.get("/admin/users")
    assert unauthenticated.status_code == 401 and unauthenticated.json()["error"] == "UNAUTHENTICATED"
    assert 'id="root"' not in unauthenticated.text

    # ... and the authenticated JSON API with one.
    login_client(client, "boss", PASSWORD)
    api = client.get("/admin/users")
    assert api.status_code == 200 and api.headers["content-type"].startswith("application/json")
    assert [u["username"] for u in api.json()["users"]] == ["boss"]
    assert client.get("/administration/users").text.count('id="root"') == 1        # still the page after login


def test_every_declared_spa_route_is_reachable_on_the_real_app(conn, dist):
    app, _ = _real_app(conn, dist)
    client = _client(app)
    for template in SPA_ROUTES:
        address = template.replace("{account_id}", "acct-1").replace("{claim_pk}", "c1").replace("{job_id}", "j1")
        response = client.get(address)
        assert response.status_code == 200 and 'id="root"' in response.text, address


def test_no_spa_route_shadows_a_real_api_route(conn, dist):
    """Generic guard: a SPA path that is also an API GET path would be served
    by the API (registered first). None may."""
    app, _ = _real_app(conn, dist)
    api_paths = {
        (route.path, method)
        for route in app.routes if getattr(route, "endpoint", None) is not None
        and route.endpoint.__module__.startswith("mcma.app.api")
        for method in getattr(route, "methods", ()) if method == "GET"
    }
    api_get_paths = {path for path, _ in api_paths}
    assert not api_get_paths & set(SPA_ROUTES), api_get_paths & set(SPA_ROUTES)


def test_the_frontend_page_route_differs_from_the_api_path_in_the_sources():
    routes_ts = (REPO / "frontend/src/shared/utils/routes.ts").read_text(encoding="utf-8")
    api_ts = (REPO / "frontend/src/shared/api/adminUsers.ts").read_text(encoding="utf-8")
    assert 'adminUsers: "/administration/users"' in routes_ts
    assert '"/admin/users' in api_ts and '"/administration' not in api_ts       # data still comes from /admin/users


# ------------------------------ session-aware event stream ---------------------------- #


def _consume(client, path="/events", *, timeout=20.0):
    """Reads the SSE stream on a helper thread until the server ends it.
    Returns (event_names, finished)."""
    result = {"events": [], "done": False}

    def run():
        with client.stream("GET", path) as response:
            result["status"] = response.status_code
            current = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    current = line.split(":", 1)[1].strip()
                    result["events"].append(current)
        result["done"] = True

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return result, thread, timeout


def _finish(result, thread, timeout):
    thread.join(timeout)
    return result["events"], result["done"]


def _open_stream(conn, *, idle=None):
    uid = create_user(conn, "emp", PASSWORD, "operator")
    grant_access(conn, uid, OUJDA)
    store = SessionStore() if idle is None else SessionStore(idle_timeout_seconds=idle)
    app, store = _real_app(conn, store=store)
    client = _client(app)
    csrf = login_client(client, "emp", PASSWORD)
    return client, store, uid, csrf


def test_deactivating_the_user_terminates_an_established_stream(conn):
    client, store, uid, _ = _open_stream(conn)
    result, thread, timeout = _consume(client)
    time.sleep(0.4)
    assert thread.is_alive() and result["done"] is False                       # established and running
    conn.execute("UPDATE users SET active = 0 WHERE user_id = ?", (uid,))
    events, done = _finish(result, thread, timeout)
    assert done and events[-1] == SESSION_ENDED_EVENT


def test_session_invalidation_by_password_reset_terminates_the_affected_stream_only(conn):
    client, store, uid, _ = _open_stream(conn)
    other_uid = create_user(conn, "other", PASSWORD, "operator")
    grant_access(conn, other_uid, NADOR)
    other = _client(_real_app(conn, store=store)[0])
    login_client(other, "other", PASSWORD)
    mine, my_thread, timeout = _consume(client)
    theirs, their_thread, _ = _consume(other)
    time.sleep(0.4)
    store.invalidate_user(uid)                                                  # what an admin password reset does
    events, done = _finish(mine, my_thread, timeout)
    assert done and events[-1] == SESSION_ENDED_EVENT
    assert their_thread.is_alive() and theirs["done"] is False                  # the other employee is unaffected
    store.invalidate_user(other_uid)
    assert _finish(theirs, their_thread, timeout)[1] is True


def test_logout_terminates_the_stream(conn):
    client, store, uid, csrf = _open_stream(conn)
    result, thread, timeout = _consume(client)
    time.sleep(0.4)
    other_tab = _client(_real_app(conn, store=store)[0])
    other_tab.cookies.set(SESSION_COOKIE_NAME, client.cookies.get(SESSION_COOKIE_NAME))
    other_tab.cookies.set("mcma_csrf", csrf)
    assert other_tab.post("/auth/logout", headers=csrf_headers(csrf)).status_code == 200
    events, done = _finish(result, thread, timeout)
    assert done and events[-1] == SESSION_ENDED_EVENT


def test_an_open_stream_cannot_keep_an_idle_session_alive(conn):
    """No other request is made after the stream opens: the idle timer keeps
    running (the stream only PEEKS), so the session expires and the stream ends."""
    client, store, uid, _ = _open_stream(conn, idle=1)
    result, thread, timeout = _consume(client)
    events, done = _finish(result, thread, timeout)
    assert done and events[-1] == SESSION_ENDED_EVENT
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert store.peek(token) is None


def test_a_connect_without_a_session_is_401_json_not_a_stream(conn):
    app, _ = _real_app(conn)
    response = _client(app).get("/events")
    assert response.status_code == 401 and response.json()["error"] == "UNAUTHENTICATED"


# ---------------------------- peek never refreshes last_seen_at -------------------------- #


def test_peek_does_not_touch_last_seen_at_but_validate_does():
    store = SessionStore()
    token = store.create("u")
    before = store._sessions[token].last_seen_at
    time.sleep(0.02)
    assert store.peek(token) == "u" and store._sessions[token].last_seen_at == before
    assert store.validate(token) == "u" and store._sessions[token].last_seen_at > before


def test_peek_reports_expired_sessions_as_gone_and_never_resurrects_them():
    store = SessionStore(idle_timeout_seconds=0)
    token = store.create("u")
    time.sleep(0.02)
    assert store.peek(token) is None and store.peek(token) is None
    assert store.validate(token) is None


def test_the_stream_generator_polling_leaves_last_seen_at_untouched():
    store = SessionStore()
    token = store.create("u")
    frozen = store._sessions[token].last_seen_at

    class Authorizer:
        def visible_accounts(self, principal):
            return set()

        def is_authorized(self, principal, account_id):
            return True

    from mcma.persistence.db import open_database
    import tempfile

    connection = open_database(Path(tempfile.mkdtemp()) / "s.sqlite3")

    async def run():
        async def no_sleep(_):
            return None

        events = []
        async for event in stream_events(connection, object(), Authorizer(), max_iterations=25, sleep=no_sleep,
                                         is_session_live=lambda: store.peek(token) == "u"):
            events.append(event)
        return events

    assert asyncio.run(run()) == []
    assert store._sessions[token].last_seen_at == frozen


def test_stream_generator_sends_session_ended_then_stops_when_liveness_flips():
    calls = {"n": 0}

    class Authorizer:
        def visible_accounts(self, principal):
            return set()

        def is_authorized(self, principal, account_id):
            return True

    from mcma.persistence.db import open_database
    import tempfile

    connection = open_database(Path(tempfile.mkdtemp()) / "s2.sqlite3")

    def live():
        calls["n"] += 1
        return calls["n"] < 3

    async def run():
        async def no_sleep(_):
            return None

        return [e async for e in stream_events(connection, object(), Authorizer(), sleep=no_sleep, is_session_live=live)]

    events = asyncio.run(run())
    assert events == [{"event": SESSION_ENDED_EVENT, "data": "{}"}]
    assert json.loads(events[0]["data"]) == {}


def test_a_stream_that_starts_dead_ends_immediately():
    class Authorizer:
        def visible_accounts(self, principal):
            return set()

        def is_authorized(self, principal, account_id):
            return True

    from mcma.persistence.db import open_database
    import tempfile

    connection = open_database(Path(tempfile.mkdtemp()) / "s3.sqlite3")

    async def run():
        return [e async for e in stream_events(connection, object(), Authorizer(), is_session_live=lambda: False)]

    assert asyncio.run(run()) == [{"event": SESSION_ENDED_EVENT, "data": "{}"}]


# ------------------- runner admin page vs runner API (collision regression) ------------------- #


def test_the_runner_admin_page_and_the_runner_api_do_not_collide_on_the_real_app(conn, dist):
    create_user(conn, "boss", PASSWORD, "admin")
    app = create_api_app(conn, auth_provider=LocalUserAuthProvider(conn), session_store=SessionStore(),
                         encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=True, runner_registry=True)
    mount_frontend(app, dist_dir=dist)
    client = _client(app)
    assert "/administration/runners" in SPA_ROUTES and "/admin/runners" not in SPA_ROUTES
    page = client.get("/administration/runners")                          # a browser refresh of the page
    assert page.status_code == 200 and 'id="root"' in page.text
    assert client.get("/admin/runners").status_code == 401                # the API stays the API
    login_client(client, "boss", PASSWORD)
    api = client.get("/admin/runners")
    assert api.status_code == 200 and api.headers["content-type"].startswith("application/json")
    assert client.get("/administration/runners").text.count('id="root"') == 1
    api_get = {r.path for r in app.routes if hasattr(r, "methods") and "GET" in r.methods
               and getattr(r, "endpoint", None) and r.endpoint.__module__.startswith("mcma.app.api")}
    assert not api_get & set(SPA_ROUTES)


def test_the_frontend_runner_page_route_differs_from_its_api_paths():
    routes_ts = (REPO / "frontend/src/shared/utils/routes.ts").read_text(encoding="utf-8")
    api_ts = (REPO / "frontend/src/shared/api/runners.ts").read_text(encoding="utf-8")
    assert 'adminRunners: "/administration/runners"' in routes_ts
    assert '"/admin/runners' in api_ts and '"/runner-status' in api_ts and "/administration" not in api_ts
