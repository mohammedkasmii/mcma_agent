"""INC-14 -- category-scoped three-poll lifecycle, exactly per
DATA_MODEL.md §3."""

from mcma.notifications.presence import apply_category_result
from mcma.persistence.repositories.claims import CategoriesRepository, CategoryPresenceRepository
from notifications_test_support import CATEGORY, NADOR, OUJDA, new_poll_run, seed_claim


def test_absence_increments_only_when_that_category_complete_and_valid(conn):
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    new_poll_run(conn, OUJDA, "poll-1")
    apply_category_result(
        conn, OUJDA, "claim-1", CATEGORY, poll_run_id="poll-1", category_status="COMPLETE",
        session_valid=True, observed_present=False,
    )
    row = CategoryPresenceRepository(conn).get(OUJDA, "claim-1", CATEGORY)
    assert row["consecutive_absence_count"] == 1
    assert row["presence_status"] == "MISSING_PENDING_CONFIRMATION"


def test_partial_or_failed_category_does_not_touch_counter(conn):
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    new_poll_run(conn, OUJDA, "poll-1")
    for status, session_valid in (("PARTIAL", True), ("FAILED", False), ("COMPLETE", False)):
        apply_category_result(
            conn, OUJDA, "claim-1", CATEGORY, poll_run_id="poll-1", category_status=status,
            session_valid=session_valid, observed_present=False,
        )
        row = CategoryPresenceRepository(conn).get(OUJDA, "claim-1", CATEGORY)
        assert row["consecutive_absence_count"] == 0
        assert row["presence_status"] == "ACTIVE"


def test_other_category_failure_never_affects_this_category(conn):
    CategoriesRepository(conn).ensure("CAT_OTHER", "Other category")
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    new_poll_run(conn, OUJDA, "poll-1")
    apply_category_result(
        conn, OUJDA, "claim-1", "CAT_OTHER", poll_run_id="poll-1", category_status="FAILED",
        session_valid=False, observed_present=False,
    )
    apply_category_result(
        conn, OUJDA, "claim-1", CATEGORY, poll_run_id="poll-1", category_status="COMPLETE",
        session_valid=True, observed_present=False,
    )
    assert CategoryPresenceRepository(conn).get(OUJDA, "claim-1", "CAT_OTHER")["consecutive_absence_count"] == 0
    assert CategoryPresenceRepository(conn).get(OUJDA, "claim-1", CATEGORY)["consecutive_absence_count"] == 1


def test_three_consecutive_complete_absences_resolve_on_portal(conn):
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    for i in range(1, 4):
        poll_id = f"poll-{i}"
        new_poll_run(conn, OUJDA, poll_id)
        apply_category_result(
            conn, OUJDA, "claim-1", CATEGORY, poll_run_id=poll_id, category_status="COMPLETE",
            session_valid=True, observed_present=False,
        )
    row = CategoryPresenceRepository(conn).get(OUJDA, "claim-1", CATEGORY)
    assert row["consecutive_absence_count"] == 3
    assert row["presence_status"] == "RESOLVED_ON_PORTAL"


def test_reappearance_resets_to_active(conn):
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    new_poll_run(conn, OUJDA, "poll-1")
    apply_category_result(
        conn, OUJDA, "claim-1", CATEGORY, poll_run_id="poll-1", category_status="COMPLETE",
        session_valid=True, observed_present=False,
    )
    new_poll_run(conn, OUJDA, "poll-2")
    apply_category_result(
        conn, OUJDA, "claim-1", CATEGORY, poll_run_id="poll-2", category_status="COMPLETE",
        session_valid=True, observed_present=True,
    )
    row = CategoryPresenceRepository(conn).get(OUJDA, "claim-1", CATEGORY)
    assert row["consecutive_absence_count"] == 0
    assert row["presence_status"] == "ACTIVE"


def test_reapplying_same_poll_run_is_idempotent(conn):
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    new_poll_run(conn, OUJDA, "poll-1")
    apply_category_result(
        conn, OUJDA, "claim-1", CATEGORY, poll_run_id="poll-1", category_status="COMPLETE",
        session_valid=True, observed_present=False,
    )
    # Re-processing the SAME poll_run_id must not double-advance.
    apply_category_result(
        conn, OUJDA, "claim-1", CATEGORY, poll_run_id="poll-1", category_status="COMPLETE",
        session_valid=True, observed_present=False,
    )
    row = CategoryPresenceRepository(conn).get(OUJDA, "claim-1", CATEGORY)
    assert row["consecutive_absence_count"] == 1


def test_oujda_and_nador_category_presence_are_fully_isolated(conn):
    """The same portal_claim_id under two different accounts must never
    share a category_presence row or influence each other's counter."""
    seed_claim(conn, OUJDA, "claim-oujda", "IDS-SAME")
    seed_claim(conn, NADOR, "claim-nador", "IDS-SAME")  # same external id, different account
    new_poll_run(conn, OUJDA, "poll-oujda-1")
    new_poll_run(conn, NADOR, "poll-nador-1")

    apply_category_result(
        conn, OUJDA, "claim-oujda", CATEGORY, poll_run_id="poll-oujda-1", category_status="COMPLETE",
        session_valid=True, observed_present=False,
    )
    nador_row = CategoryPresenceRepository(conn).get(NADOR, "claim-nador", CATEGORY)
    assert nador_row is None  # Nador untouched by Oujda's absence

    apply_category_result(
        conn, NADOR, "claim-nador", CATEGORY, poll_run_id="poll-nador-1", category_status="COMPLETE",
        session_valid=True, observed_present=True,
    )
    oujda_row = CategoryPresenceRepository(conn).get(OUJDA, "claim-oujda", CATEGORY)
    assert oujda_row["consecutive_absence_count"] == 1  # unaffected by Nador's presence
