"""The employee's working list: claims per account, with a status and a
note the employee keeps here because SinAuto gives them nowhere to.

Account isolation is the property under test throughout -- one office
holds four accounts on one portal, so "can Oujda see Nador's claims" is
not a theoretical question here.
"""

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


def _add_claim(conn, account_id, portal_claim_id, reference, insured=None, matricule=None):
    claim_pk = f"{account_id}:{portal_claim_id}"
    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, insured, "
        "police, matricule_norm, first_seen_version, last_seen_version) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?, 1, 1)",
        (claim_pk, account_id, portal_claim_id, reference, insured, matricule),
    )
    return claim_pk


# --------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------- #


def test_claims_are_listed_for_the_selected_account(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    _add_claim(conn, OUJDA, "699001", "SIN-2026-004182", insured="BENALI Youssef", matricule="77001C3")
    login_client(client, "alice", "pw12345")

    response = client.get(f"/claims?account_id={OUJDA}")
    assert response.status_code == 200
    claims = response.json()["claims"]
    assert len(claims) == 1
    assert claims[0]["reference"] == "SIN-2026-004182"
    assert claims[0]["insured"] == "BENALI Youssef"
    # Account labelling travels with the row so the list can always say
    # whose claim this is.
    assert claims[0]["account_entity"] == "MCMA"
    assert claims[0]["account_scope"] == "OUJDA"


def test_a_claim_with_no_action_yet_reads_as_new(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    _add_claim(conn, OUJDA, "699001", "SIN-1")
    login_client(client, "alice", "pw12345")

    claim = client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]
    assert claim["status"] == "NEW"
    assert claim["note"] is None


def test_claims_from_another_account_are_never_listed(conn, app_and_client):
    """Four accounts on one portal: an employee granted Oujda must never
    see Nador's or MAMDA's claims, with or without an explicit
    account_id."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    _add_claim(conn, OUJDA, "699001", "MINE")
    _add_claim(conn, NADOR, "699002", "NOT-MINE")
    _add_claim(conn, MAMDA_OUJDA, "699003", "ALSO-NOT-MINE")
    login_client(client, "alice", "pw12345")

    references = {c["reference"] for c in client.get("/claims").json()["claims"]}
    assert references == {"MINE"}

    denied = client.get(f"/claims?account_id={NADOR}")
    assert denied.status_code in (403, 404)


def test_mamda_claims_are_listed_because_notifications_are_read_only_work(conn, app_and_client):
    """MAMDA accounts cannot be WRITTEN to, but their notifications are
    exactly the work an employee needs to track -- the read-only rule is
    about form filling, not about visibility."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, MAMDA_OUJDA)
    _add_claim(conn, MAMDA_OUJDA, "699003", "MAMDA-CLAIM")
    login_client(client, "alice", "pw12345")

    claims = client.get(f"/claims?account_id={MAMDA_OUJDA}").json()["claims"]
    assert [c["reference"] for c in claims] == ["MAMDA-CLAIM"]
    assert claims[0]["account_entity"] == "MAMDA"


# --------------------------------------------------------------------- #
# Recording status and notes
# --------------------------------------------------------------------- #


def test_employee_can_set_a_status_and_note_and_read_it_back(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    csrf = login_client(client, "alice", "pw12345")

    saved = client.post(
        f"/claims/{claim_pk}/action",
        json={"status": "WAITING", "note": "Client not reachable, called twice"},
        headers=csrf_headers(csrf),
    )
    assert saved.status_code == 200, saved.text

    claim = client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]
    assert claim["status"] == "WAITING"
    assert claim["note"] == "Client not reachable, called twice"


def test_history_is_appended_never_overwritten(conn, app_and_client):
    """A correction adds a row rather than replacing one, so who said
    what and when survives -- the list shows the latest, the trail keeps
    the rest."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    csrf = login_client(client, "alice", "pw12345")

    client.post(f"/claims/{claim_pk}/action", json={"status": "IN_PROGRESS", "note": "first"},
                headers=csrf_headers(csrf))
    client.post(f"/claims/{claim_pk}/action", json={"status": "DONE", "note": "second"},
                headers=csrf_headers(csrf))

    rows = conn.execute(
        "SELECT status, note, version, actor_user_id FROM employee_actions "
        "WHERE claim_pk = ? ORDER BY version", (claim_pk,)
    ).fetchall()
    assert [r["status"] for r in rows] == ["IN_PROGRESS", "DONE"]
    assert [r["version"] for r in rows] == [1, 2]
    # The actor is the authenticated user, never anything the client sent.
    assert {r["actor_user_id"] for r in rows} == {user_id}

    claim = client.get(f"/claims?account_id={OUJDA}").json()["claims"][0]
    assert claim["status"] == "DONE"
    assert claim["note"] == "second"


def test_an_unknown_status_is_rejected(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(f"/claims/{claim_pk}/action", json={"status": "SOMETHING_ELSE"},
                           headers=csrf_headers(csrf))
    assert response.status_code == 400
    assert conn.execute("SELECT count(*) AS n FROM employee_actions").fetchone()["n"] == 0


def test_an_over_long_note_is_rejected(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(f"/claims/{claim_pk}/action", json={"status": "DONE", "note": "x" * 2001},
                           headers=csrf_headers(csrf))
    assert response.status_code == 400


def test_cannot_annotate_a_claim_on_an_account_you_cannot_access(conn, app_and_client):
    """Access is decided by the CLAIM's own account, never by anything the
    caller supplies."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    other_pk = _add_claim(conn, NADOR, "699002", "NOT-MINE")
    csrf = login_client(client, "alice", "pw12345")

    response = client.post(f"/claims/{other_pk}/action", json={"status": "DONE", "note": "sneaky"},
                           headers=csrf_headers(csrf))
    assert response.status_code in (403, 404)
    assert conn.execute("SELECT count(*) AS n FROM employee_actions").fetchone()["n"] == 0


def test_annotating_an_unknown_claim_is_a_404(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    csrf = login_client(client, "alice", "pw12345")

    response = client.post("/claims/does-not-exist/action", json={"status": "DONE"},
                           headers=csrf_headers(csrf))
    assert response.status_code == 404


def test_saving_requires_csrf(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    login_client(client, "alice", "pw12345")

    response = client.post(f"/claims/{claim_pk}/action", json={"status": "DONE"})
    assert response.status_code in (400, 403)
    assert conn.execute("SELECT count(*) AS n FROM employee_actions").fetchone()["n"] == 0


def test_a_viewer_can_read_claims_but_not_annotate_them(conn, app_and_client):
    app, client, _ = app_and_client
    user_id = create_user(conn, "vic", "pw12345", "viewer")
    grant_access(conn, user_id, OUJDA)
    claim_pk = _add_claim(conn, OUJDA, "699001", "SIN-1")
    csrf = login_client(client, "vic", "pw12345")

    assert client.get(f"/claims?account_id={OUJDA}").status_code == 200
    denied = client.post(f"/claims/{claim_pk}/action", json={"status": "DONE"},
                         headers=csrf_headers(csrf))
    assert denied.status_code == 403


def test_claims_require_authentication(conn, app_and_client):
    app, client, _ = app_and_client
    assert client.get("/claims").status_code == 401
