"""Notification freshness over the API: GET /claims reports it per category
membership, POST /claims/{claim_pk}/notifications/seen clears it.

The mark-seen route is a local state change like the tracking action, so
it carries the same guards: authentication, CSRF, notifications:update,
and access decided by the CLAIM's own account. It never touches the
employee's workflow status. Synthetic data only."""

from api_test_support import (
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


def _add_claim(conn, account_id, portal_claim_id, reference):
    claim_pk = f"{account_id}:{portal_claim_id}"
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, first_seen_version, "
        "last_seen_version) VALUES (?, ?, ?, ?, 1, 1)",
        (claim_pk, account_id, portal_claim_id, reference),
    )
    return claim_pk


def _add_presence(conn, account_id, claim_pk, code, label, *, unread, present=True):
    conn.execute("INSERT OR IGNORE INTO categories (code_alerte, label) VALUES (?, ?)", (code, label))
    conn.execute(
        "INSERT INTO category_presence (account_id, claim_pk, category_code, present, presence_status, "
        "since_version, unread, appeared_poll_version, appeared_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, 1, '2026-01-10T08:00:00+00:00')",
        (account_id, claim_pk, code, int(present), "ACTIVE" if present else "RESOLVED_ON_PORTAL", int(unread)),
    )


def _unread(conn, claim_pk, code):
    return conn.execute(
        "SELECT unread FROM category_presence WHERE claim_pk = ? AND category_code = ?", (claim_pk, code)
    ).fetchone()["unread"]


def _operator(conn, client, *accounts):
    user_id = create_user(conn, "alice", "pw12345", "operator")
    for account_id in accounts:
        grant_access(conn, user_id, account_id)
    return login_client(client, "alice", "pw12345")


def _seen_path(claim_pk):
    return f"/claims/{claim_pk}/notifications/seen"


# --------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------- #


def test_claims_report_freshness_per_active_membership(conn, app_and_client):
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", "Alerte A", unread=True)
    _add_presence(conn, OUJDA, claim_pk, "CAT_B", "Alerte B", unread=False)
    _add_presence(conn, OUJDA, claim_pk, "CAT_GONE", "Alerte partie", unread=True, present=False)
    _operator(conn, client, OUJDA)

    claim = client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]

    # The existing field is unchanged: active labels only.
    assert sorted(claim["categories"]) == ["Alerte A", "Alerte B"]
    by_label = {entry["category"]: entry for entry in claim["notifications"]}
    assert set(by_label) == {"Alerte A", "Alerte B"}
    assert by_label["Alerte A"]["unread"] is True
    assert by_label["Alerte B"]["unread"] is False
    assert by_label["Alerte A"]["appeared_at"] == "2026-01-10T08:00:00+00:00"
    # Only what the employee needs -- no portal category code.
    assert set(by_label["Alerte A"]) == {"category", "unread", "appeared_at", "seen_at"}


def test_a_claim_with_no_active_membership_has_no_notifications(conn, app_and_client):
    _, client, _ = app_and_client
    _add_claim(conn, OUJDA, "699001", "SIN-1")
    _operator(conn, client, OUJDA)

    claim = client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]
    assert claim["categories"] == []
    assert claim["notifications"] == []


# --------------------------------------------------------------------- #
# Marking seen
# --------------------------------------------------------------------- #


def test_marking_seen_clears_active_unread_and_is_idempotent(conn, app_and_client):
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", "Alerte A", unread=True)
    _add_presence(conn, OUJDA, claim_pk, "CAT_B", "Alerte B", unread=True)
    _add_presence(conn, OUJDA, claim_pk, "CAT_GONE", "Alerte partie", unread=True, present=False)
    csrf = _operator(conn, client, OUJDA)

    first = client.post(_seen_path(claim_pk), headers=csrf_headers(csrf))
    assert first.status_code == 200, first.text
    assert first.json() == {"claim_pk": claim_pk, "marked_seen": 2}
    seen_at = conn.execute(
        "SELECT seen_at FROM category_presence WHERE claim_pk = ? AND category_code = 'CAT_A'", (claim_pk,)
    ).fetchone()["seen_at"]
    assert seen_at is not None

    again = client.post(_seen_path(claim_pk), headers=csrf_headers(csrf))
    assert again.status_code == 200
    assert again.json()["marked_seen"] == 0
    # A repeat keeps the first seen_at; an inactive membership is untouched.
    assert conn.execute(
        "SELECT seen_at FROM category_presence WHERE claim_pk = ? AND category_code = 'CAT_A'", (claim_pk,)
    ).fetchone()["seen_at"] == seen_at
    assert _unread(conn, claim_pk, "CAT_GONE") == 1

    listed = client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]
    assert all(entry["unread"] is False for entry in listed["notifications"])


def test_marking_seen_never_changes_the_workflow_status(conn, app_and_client):
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", "Alerte A", unread=True)
    csrf = _operator(conn, client, OUJDA)

    client.post(_seen_path(claim_pk), headers=csrf_headers(csrf))
    assert conn.execute("SELECT count(*) AS n FROM employee_actions").fetchone()["n"] == 0
    assert client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]["status"] == "NEW"

    client.post(f"/claims/{claim_pk}/action", json={"status": "WAITING"}, headers=csrf_headers(csrf))
    _add_presence(conn, OUJDA, claim_pk, "CAT_B", "Alerte B", unread=True)
    client.post(_seen_path(claim_pk), headers=csrf_headers(csrf))
    assert client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]["status"] == "WAITING"


def test_marking_one_account_leaves_another_untouched(conn, app_and_client):
    """Same external id on Oujda and Nador; the employee can see both. Only
    the claim's own account is updated, whatever the client sends."""
    _, client, _ = app_and_client
    oujda_pk = _add_claim(conn, OUJDA, "SAME", "SIN-O")
    nador_pk = _add_claim(conn, NADOR, "SAME", "SIN-N")
    _add_presence(conn, OUJDA, oujda_pk, "CAT_A", "Alerte A", unread=True)
    _add_presence(conn, NADOR, nador_pk, "CAT_A", "Alerte A", unread=True)
    csrf = _operator(conn, client, OUJDA, NADOR)

    response = client.post(
        f"{_seen_path(oujda_pk)}?account_id={NADOR}", json={"account_id": NADOR}, headers=csrf_headers(csrf)
    )
    assert response.status_code == 200
    assert _unread(conn, oujda_pk, "CAT_A") == 0
    assert _unread(conn, nador_pk, "CAT_A") == 1
    nador = client.get(f"/claims?account_id={NADOR}").json()["claims"][0]
    assert nador["notifications"][0]["unread"] is True


# --------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------- #


def test_marking_seen_requires_authentication(conn, app_and_client):
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", "Alerte A", unread=True)

    assert client.post(_seen_path(claim_pk)).status_code == 401
    assert _unread(conn, claim_pk, "CAT_A") == 1


def test_marking_seen_requires_csrf(conn, app_and_client):
    _, client, _ = app_and_client
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", "Alerte A", unread=True)
    _operator(conn, client, OUJDA)

    response = client.post(_seen_path(claim_pk))
    assert response.status_code in (400, 403)
    assert _unread(conn, claim_pk, "CAT_A") == 1


def test_marking_seen_requires_the_update_permission(conn, app_and_client):
    _, client, _ = app_and_client
    user_id = create_user(conn, "vic", "pw12345", "viewer")
    grant_access(conn, user_id, OUJDA)
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    _add_presence(conn, OUJDA, claim_pk, "CAT_A", "Alerte A", unread=True)
    csrf = login_client(client, "vic", "pw12345")

    assert client.post(_seen_path(claim_pk), headers=csrf_headers(csrf)).status_code == 403
    assert _unread(conn, claim_pk, "CAT_A") == 1


def test_marking_seen_on_an_inaccessible_account_is_refused(conn, app_and_client):
    _, client, _ = app_and_client
    other_pk = _add_claim(conn, NADOR, "699002", "NOT-MINE")
    _add_presence(conn, NADOR, other_pk, "CAT_A", "Alerte A", unread=True)
    csrf = _operator(conn, client, OUJDA)

    response = client.post(_seen_path(other_pk), headers=csrf_headers(csrf))
    assert response.status_code in (403, 404)
    assert _unread(conn, other_pk, "CAT_A") == 1


def test_marking_seen_on_an_unknown_claim_is_a_404(conn, app_and_client):
    _, client, _ = app_and_client
    csrf = _operator(conn, client, OUJDA)
    assert client.post(_seen_path("does-not-exist"), headers=csrf_headers(csrf)).status_code == 404
