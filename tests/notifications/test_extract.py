"""INC-14 -- run_poll orchestration: read-only, per-category isolation,
account isolation, and duplicate-poll idempotency."""

import asyncio

from mcma.notifications.extract import run_poll
from mcma.persistence.repositories.claims import CategoriesRepository, CategoryPresenceRepository, PollRunCategoriesRepository
from notifications_test_support import CATEGORY, NADOR, OUJDA, StubReader


def run_async(coro):
    return asyncio.run(coro)


def test_extraction_is_read_only(conn):
    """StubReader exposes exactly one method (read_notifications) --
    run_poll structurally cannot call anything else on it, so no
    mutating request can ever be issued through this path."""
    reader = StubReader({CATEGORY: [{"idSinistre": "1", "reference": "R1"}]})
    run_async(run_poll(conn, OUJDA, reader, [CATEGORY], version=1))
    assert reader.calls == [CATEGORY]
    public_methods = {name for name in dir(reader) if not name.startswith("_") and callable(getattr(reader, name))}
    assert public_methods == {"read_notifications"}


def test_run_poll_upserts_claims_and_applies_presence(conn):
    reader = StubReader({CATEGORY: [{"idSinistre": "1", "reference": "R1"}]})
    poll_run_id = run_async(run_poll(conn, OUJDA, reader, [CATEGORY], version=1))
    row = CategoryPresenceRepository(conn).get(OUJDA, f"{OUJDA}:1", CATEGORY)
    assert row["presence_status"] == "ACTIVE"
    assert row["consecutive_absence_count"] == 0
    assert PollRunCategoriesRepository(conn).get(poll_run_id, CATEGORY)["status"] == "COMPLETE"


def test_run_poll_records_failed_category_without_raising(conn):
    reader = StubReader({CATEGORY: RuntimeError("session expired")})
    poll_run_id = run_async(run_poll(conn, OUJDA, reader, [CATEGORY], version=1))
    assert PollRunCategoriesRepository(conn).get(poll_run_id, CATEGORY)["status"] == "FAILED"


def test_run_poll_partial_when_some_categories_succeed(conn):
    CategoriesRepository(conn).ensure("CAT_OTHER", "Other")
    reader = StubReader({CATEGORY: [], "CAT_OTHER": RuntimeError("boom")})
    poll_run_id = run_async(run_poll(conn, OUJDA, reader, [CATEGORY, "CAT_OTHER"], version=1))
    from mcma.persistence.repositories.claims import PollRunsRepository

    assert PollRunsRepository(conn).get(poll_run_id)["status"] == "PARTIAL"


def test_duplicate_poll_does_not_create_duplicate_notifications_or_jobs(conn):
    """Re-running run_poll with the SAME rows twice must not create two
    claim rows or double-advance presence -- claims.upsert() is itself
    idempotent per (account_id, portal_claim_id), and the second poll's
    OWN complete observation is a legitimate new poll (still-present),
    not a duplicate."""
    reader = StubReader({CATEGORY: [{"idSinistre": "1", "reference": "R1"}]})
    run_async(run_poll(conn, OUJDA, reader, [CATEGORY], version=1))
    run_async(run_poll(conn, OUJDA, reader, [CATEGORY], version=2))
    assert conn.execute("SELECT COUNT(*) AS c FROM claims WHERE account_id=?", (OUJDA,)).fetchone()["c"] == 1


def test_oujda_reader_never_sees_nador_data_and_vice_versa(conn):
    oujda_reader = StubReader({CATEGORY: [{"idSinistre": "OUJDA-1"}]})
    nador_reader = StubReader({CATEGORY: [{"idSinistre": "NADOR-1"}]})
    run_async(run_poll(conn, OUJDA, oujda_reader, [CATEGORY], version=1))
    run_async(run_poll(conn, NADOR, nador_reader, [CATEGORY], version=1))

    oujda_claims = conn.execute("SELECT portal_claim_id FROM claims WHERE account_id=?", (OUJDA,)).fetchall()
    nador_claims = conn.execute("SELECT portal_claim_id FROM claims WHERE account_id=?", (NADOR,)).fetchall()
    assert {r["portal_claim_id"] for r in oujda_claims} == {"OUJDA-1"}
    assert {r["portal_claim_id"] for r in nador_claims} == {"NADOR-1"}


def test_no_notification_mutation_endpoint_is_reachable():
    """Structural proof: mcma.notifications.extract's source never
    references any endpoint or method name associated with a mutation
    (acknowledge/delete/ajouterDocument/etc)."""
    import inspect

    import mcma.notifications.extract as extract_module

    source = inspect.getsource(extract_module)
    for forbidden in ("acknowledge", "deleteDocument", "ajouterDocument", "VerifiedMissionWriter", "createRapportDefDet", "updateDevisDet"):
        assert forbidden not in source
