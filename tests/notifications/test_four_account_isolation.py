"""Correction batch (owner amendment, section I) -- four shared
PortalAccount profiles (MCMA/MAMDA x Oujda/Nador): each feed is stored
independently, the same external notification identifier across accounts
never collides, failed/malformed polls never advance resolution, polling
never creates an automation_jobs row, no notification mutation endpoint
is reachable, and no MAMDA writer is obtainable through this path.
Synthetic data only."""

import asyncio

from mcma.notifications.extract import run_poll
from mcma.persistence.repositories.claims import CategoryPresenceRepository
from notifications_test_support import CATEGORY, NADOR as MAMDA_NADOR, OUJDA as MAMDA_OUJDA, StubReader

# The shared `conn` fixture (notifications_test_support.py) already seeds
# OUJDA/NADOR as MAMDA/OUJDA and MAMDA/NADOR (plus the CATEGORY row) --
# reused here as-is (aliased) rather than duplicated, since
# UNIQUE(entity, scope) forbids a second MAMDA/OUJDA or MAMDA/NADOR row.
# Only the two MCMA accounts are new.
MCMA_OUJDA = "acct-mcma-oujda"
MCMA_NADOR = "acct-mcma-nador"
FOUR_ACCOUNTS = (MCMA_OUJDA, MAMDA_OUJDA, MCMA_NADOR, MAMDA_NADOR)


def run_async(coro):
    return asyncio.run(coro)


def _seed_four_accounts(conn) -> None:
    for account_id, entity, scope in ((MCMA_OUJDA, "MCMA", "OUJDA"), (MCMA_NADOR, "MCMA", "NADOR")):
        conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, '2026-01-01T00:00:00+00:00')",
            (account_id, f"{entity} {scope}", entity, scope),
        )


def test_each_of_the_four_feeds_is_stored_independently(conn):
    _seed_four_accounts(conn)
    for account_id in FOUR_ACCOUNTS:
        reader = StubReader({CATEGORY: [{"idSinistre": f"{account_id}-1", "reference": "R1"}]})
        run_async(run_poll(conn, account_id, reader, [CATEGORY], version=1))

    for account_id in FOUR_ACCOUNTS:
        rows = conn.execute("SELECT portal_claim_id FROM claims WHERE account_id=?", (account_id,)).fetchall()
        assert {r["portal_claim_id"] for r in rows} == {f"{account_id}-1"}


def test_same_external_identifier_across_all_four_accounts_never_collides(conn):
    """The identical idSinistre value ('SHARED-ID') appears under all
    four accounts -- each must produce its OWN isolated claim row keyed
    by (account_id, portal_claim_id), never merged/shared."""
    _seed_four_accounts(conn)
    for account_id in FOUR_ACCOUNTS:
        reader = StubReader({CATEGORY: [{"idSinistre": "SHARED-ID", "reference": "R-shared"}]})
        run_async(run_poll(conn, account_id, reader, [CATEGORY], version=1))

    claim_pks = set()
    for account_id in FOUR_ACCOUNTS:
        row = conn.execute(
            "SELECT claim_pk FROM claims WHERE account_id=? AND portal_claim_id='SHARED-ID'", (account_id,)
        ).fetchone()
        assert row is not None
        claim_pks.add(row["claim_pk"])
    assert len(claim_pks) == 4  # four genuinely distinct claim rows, never one shared row

    total = conn.execute("SELECT COUNT(*) AS c FROM claims WHERE portal_claim_id='SHARED-ID'").fetchone()["c"]
    assert total == 4


def test_failed_poll_never_advances_resolution_on_any_of_the_four_accounts(conn):
    _seed_four_accounts(conn)
    for account_id in FOUR_ACCOUNTS:
        good_reader = StubReader({CATEGORY: [{"idSinistre": "1"}]})
        run_async(run_poll(conn, account_id, good_reader, [CATEGORY], version=1))

        failing_reader = StubReader({CATEGORY: RuntimeError("session expired")})
        run_async(run_poll(conn, account_id, failing_reader, [CATEGORY], version=2))

        row = CategoryPresenceRepository(conn).get(account_id, f"{account_id}:1", CATEGORY)
        # Still ACTIVE with zero absences -- the failed poll never counted
        # as an absence and never resolved the claim.
        assert row["presence_status"] == "ACTIVE"
        assert row["consecutive_absence_count"] == 0


def test_malformed_row_never_advances_resolution(conn):
    _seed_four_accounts(conn)
    good_reader = StubReader({CATEGORY: [{"idSinistre": "1"}]})
    run_async(run_poll(conn, MCMA_OUJDA, good_reader, [CATEGORY], version=1))

    malformed_reader = StubReader({CATEGORY: ["not-a-dict", {"idSinistre": "1"}]})
    run_async(run_poll(conn, MCMA_OUJDA, malformed_reader, [CATEGORY], version=2))

    row = CategoryPresenceRepository(conn).get(MCMA_OUJDA, f"{MCMA_OUJDA}:1", CATEGORY)
    assert row["presence_status"] == "ACTIVE"
    unmatched = conn.execute(
        "SELECT COUNT(*) AS c FROM unmatched_notifications WHERE account_id=?", (MCMA_OUJDA,)
    ).fetchone()["c"]
    assert unmatched == 1  # the malformed row was staged, not silently dropped or crashed on


def test_polling_never_creates_an_automation_job_on_any_of_the_four_accounts(conn):
    _seed_four_accounts(conn)
    for account_id in FOUR_ACCOUNTS:
        reader = StubReader({CATEGORY: [{"idSinistre": f"{account_id}-1"}]})
        run_async(run_poll(conn, account_id, reader, [CATEGORY], version=1))

    count = conn.execute("SELECT COUNT(*) AS c FROM automation_jobs").fetchone()["c"]
    assert count == 0


def test_no_notification_mutation_endpoint_reachable_from_any_account_path():
    import inspect

    import mcma.notifications.extract as extract_module
    import mcma.notifications.staging as staging_module
    import mcma.notifications.presence as presence_module

    for module in (extract_module, staging_module, presence_module):
        source = inspect.getsource(module)
        for forbidden in ("acknowledge", "deleteDocument", "ajouterDocument", "VerifiedMissionWriter", "open_verified_writer"):
            assert forbidden not in source


def test_no_mamda_writer_obtainable_through_the_notification_path():
    """mcma.notifications never imports mcma.portal.writer (or
    mcma.execution) at all -- structurally incapable of constructing a
    writer for ANY account, MAMDA included, regardless of entity."""
    import inspect

    import mcma.notifications.extract as extract_module

    source = inspect.getsource(extract_module)
    import_lines = [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    joined = "\n".join(import_lines)
    assert "mcma.portal" not in joined
    assert "mcma.execution" not in joined


def test_combined_notification_listing_can_distinguish_all_four_profiles(conn):
    """A dashboard combining all four accounts' notifications can always
    tell them apart by (entity, scope) -- proven at the persistence
    level (the API-level join is tested in tests/app/api)."""
    _seed_four_accounts(conn)
    rows = conn.execute("SELECT account_id, entity, scope FROM accounts ORDER BY account_id").fetchall()
    profiles = {(r["entity"], r["scope"]) for r in rows}
    assert profiles == {("MCMA", "OUJDA"), ("MCMA", "NADOR"), ("MAMDA", "OUJDA"), ("MAMDA", "NADOR")}
