"""Notification freshness ("Nouveau" / "Vu", migration 0004) through the
real poll path: run_poll + a stub reader, synthetic data only.

Freshness is tracked per (account_id, claim_pk, category_code). The first
complete poll of a category is its baseline -- existing work, never new;
after it a membership is new when first observed, or when it returns
after the resolution lifecycle completed. Failed/partial polls change
nothing."""

import asyncio

from mcma.notifications.extract import run_poll
from mcma.notifications.presence import apply_category_result
from mcma.persistence.repositories.claims import (
    CategoriesRepository,
    CategoryBaselinesRepository,
    CategoryPresenceRepository,
    ClaimsRepository,
    PollRunsRepository,
)
from notifications_test_support import CATEGORY, NADOR, OUJDA, StubReader

OTHER = "CAT_OTHER"


def _n(portal_claim_id: str) -> dict:
    return {"idSinistre": portal_claim_id, "reference": f"R-{portal_claim_id}"}


def _poll(conn, account_id: str, results: dict) -> str:
    """One poll of exactly the categories named in `results`; a value that
    is an Exception makes that category's read fail."""
    reader = StubReader(results)
    poll_run_id, _status = asyncio.run(run_poll(conn, account_id, reader, list(results), version=1))
    return poll_run_id


def _presence(conn, account_id: str, portal_claim_id: str, category: str = CATEGORY):
    claim = ClaimsRepository(conn).get_by_portal_claim_id(account_id, portal_claim_id)
    assert claim is not None
    return CategoryPresenceRepository(conn).get(account_id, claim["claim_pk"], category)


def _claim_pk(conn, account_id: str, portal_claim_id: str) -> str:
    return ClaimsRepository(conn).get_by_portal_claim_id(account_id, portal_claim_id)["claim_pk"]


def _mark_seen(conn, account_id: str, portal_claim_id: str) -> int:
    return CategoryPresenceRepository(conn).mark_seen_for_claim(
        account_id, _claim_pk(conn, account_id, portal_claim_id), seen_at="2026-02-01T10:00:00+00:00"
    )


# --------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------- #


def test_first_complete_poll_is_a_seen_baseline(conn):
    _poll(conn, OUJDA, {CATEGORY: [_n("A"), _n("B")]})

    for portal_id in ("A", "B"):
        row = _presence(conn, OUJDA, portal_id)
        assert row["unread"] == 0
        assert row["appeared_poll_version"] is not None  # recorded as having appeared
    assert CategoryBaselinesRepository(conn).get(OUJDA, CATEGORY) is not None


def test_membership_appearing_after_the_baseline_is_new(conn):
    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})
    _poll(conn, OUJDA, {CATEGORY: [_n("A"), _n("B")]})

    assert _presence(conn, OUJDA, "A")["unread"] == 0
    new = _presence(conn, OUJDA, "B")
    assert new["unread"] == 1
    assert new["appeared_at"] is not None
    assert new["seen_at"] is None


def test_an_empty_first_complete_poll_is_still_a_baseline(conn):
    _poll(conn, OUJDA, {CATEGORY: []})
    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})

    assert _presence(conn, OUJDA, "A")["unread"] == 1


# --------------------------------------------------------------------- #
# Failed / partial polls
# --------------------------------------------------------------------- #


def test_a_failed_poll_establishes_no_baseline(conn):
    _poll(conn, OUJDA, {CATEGORY: RuntimeError("portal down")})
    assert CategoryBaselinesRepository(conn).get(OUJDA, CATEGORY) is None

    # The first COMPLETE poll is therefore still the baseline.
    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})
    assert _presence(conn, OUJDA, "A")["unread"] == 0


def test_failed_and_partial_polls_never_change_freshness(conn):
    CategoriesRepository(conn).ensure(OTHER, "Other category")
    _poll(conn, OUJDA, {CATEGORY: [_n("A")], OTHER: []})
    _poll(conn, OUJDA, {CATEGORY: [_n("A"), _n("B")], OTHER: []})
    _mark_seen(conn, OUJDA, "A")  # A was never new; B is new
    before = {pid: dict(_presence(conn, OUJDA, pid)) for pid in ("A", "B")}

    # Whole poll failed, then a PARTIAL one where CATEGORY failed while OTHER
    # completed with a row that would otherwise be new.
    _poll(conn, OUJDA, {CATEGORY: RuntimeError("down"), OTHER: RuntimeError("down")})
    _poll(conn, OUJDA, {CATEGORY: RuntimeError("down"), OTHER: [_n("C")]})

    for pid in ("A", "B"):
        assert dict(_presence(conn, OUJDA, pid)) == before[pid]
    # The category that DID complete progressed independently.
    assert _presence(conn, OUJDA, "C", OTHER)["unread"] == 1


def test_a_new_row_first_seen_in_a_failed_category_is_not_classified(conn):
    """Evidence from a failed read never reaches presence, so it can never
    make anything new; the membership is classified by the next complete
    poll that actually observes it."""
    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})
    _poll(conn, OUJDA, {CATEGORY: RuntimeError("down")})
    assert ClaimsRepository(conn).get_by_portal_claim_id(OUJDA, "B") is None

    _poll(conn, OUJDA, {CATEGORY: [_n("A"), _n("B")]})
    assert _presence(conn, OUJDA, "B")["unread"] == 1


# --------------------------------------------------------------------- #
# Seen survives; resolution resets
# --------------------------------------------------------------------- #


def test_seen_state_survives_later_refreshes(conn):
    _poll(conn, OUJDA, {CATEGORY: []})
    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})
    assert _mark_seen(conn, OUJDA, "A") == 1
    seen_at = _presence(conn, OUJDA, "A")["seen_at"]

    for _ in range(3):
        _poll(conn, OUJDA, {CATEGORY: [_n("A")]})

    row = _presence(conn, OUJDA, "A")
    assert row["unread"] == 0
    assert row["seen_at"] == seen_at


def test_briefly_missing_then_back_is_the_same_appearance(conn):
    """MISSING_PENDING_CONFIRMATION coming back is an ordinary refresh: a
    seen notification stays seen, an unseen one stays new."""
    _poll(conn, OUJDA, {CATEGORY: []})
    _poll(conn, OUJDA, {CATEGORY: [_n("SEEN"), _n("UNSEEN")]})
    _mark_seen(conn, OUJDA, "SEEN")

    _poll(conn, OUJDA, {CATEGORY: []})  # one absence: pending, not resolved
    assert _presence(conn, OUJDA, "SEEN")["presence_status"] == "MISSING_PENDING_CONFIRMATION"
    _poll(conn, OUJDA, {CATEGORY: [_n("SEEN"), _n("UNSEEN")]})

    assert _presence(conn, OUJDA, "SEEN")["unread"] == 0
    assert _presence(conn, OUJDA, "UNSEEN")["unread"] == 1


def test_a_resolved_notification_that_reappears_is_new_again(conn):
    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})  # baseline: seen
    first_appearance = _presence(conn, OUJDA, "A")["appeared_poll_version"]
    for _ in range(3):
        _poll(conn, OUJDA, {CATEGORY: []})
    assert _presence(conn, OUJDA, "A")["presence_status"] == "RESOLVED_ON_PORTAL"

    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})

    row = _presence(conn, OUJDA, "A")
    assert row["presence_status"] == "ACTIVE"
    assert row["unread"] == 1
    assert row["seen_at"] is None
    assert row["appeared_poll_version"] > first_appearance


def test_replaying_an_applied_poll_does_not_change_freshness(conn):
    _poll(conn, OUJDA, {CATEGORY: []})
    poll_run_id = _poll(conn, OUJDA, {CATEGORY: [_n("A")]})
    _mark_seen(conn, OUJDA, "A")

    apply_category_result(
        conn, OUJDA, _claim_pk(conn, OUJDA, "A"), CATEGORY, poll_run_id=poll_run_id,
        category_status="COMPLETE", session_valid=True, observed_present=True,
    )
    assert _presence(conn, OUJDA, "A")["unread"] == 0


def test_mark_seen_only_touches_active_unread_memberships(conn):
    _poll(conn, OUJDA, {CATEGORY: []})
    _poll(conn, OUJDA, {CATEGORY: [_n("A")]})
    _poll(conn, OUJDA, {CATEGORY: []})  # A now absent (present=0) but still unread

    assert _mark_seen(conn, OUJDA, "A") == 0
    assert _presence(conn, OUJDA, "A")["unread"] == 1


# --------------------------------------------------------------------- #
# Scope: category and account
# --------------------------------------------------------------------- #


def test_the_same_dossier_in_two_categories_is_tracked_independently(conn):
    CategoriesRepository(conn).ensure(OTHER, "Other category")
    _poll(conn, OUJDA, {CATEGORY: [_n("A")], OTHER: []})
    _poll(conn, OUJDA, {CATEGORY: [_n("A")], OTHER: [_n("A")]})

    assert _presence(conn, OUJDA, "A", CATEGORY)["unread"] == 0  # baseline membership
    assert _presence(conn, OUJDA, "A", OTHER)["unread"] == 1  # new membership


def test_baselines_and_freshness_never_cross_accounts(conn):
    """Oujda having a baseline says nothing about Nador: Nador's first
    complete poll is its OWN baseline, and marking one account's dossier
    seen leaves the other's identical external id alone."""
    _poll(conn, OUJDA, {CATEGORY: []})
    _poll(conn, NADOR, {CATEGORY: [_n("SAME")]})  # Nador's baseline
    _poll(conn, OUJDA, {CATEGORY: [_n("SAME")]})  # new for Oujda
    _poll(conn, NADOR, {CATEGORY: [_n("SAME"), _n("N2")]})

    assert _presence(conn, NADOR, "SAME")["unread"] == 0
    assert _presence(conn, NADOR, "N2")["unread"] == 1
    assert _presence(conn, OUJDA, "SAME")["unread"] == 1

    _mark_seen(conn, OUJDA, "SAME")
    assert _presence(conn, OUJDA, "SAME")["unread"] == 0
    assert _presence(conn, NADOR, "N2")["unread"] == 1


def test_direct_apply_without_a_complete_poll_never_marks_new(conn):
    """The lifecycle entry point itself refuses to classify on a partial or
    invalid category outcome, whatever the caller passes."""
    ClaimsRepository(conn).upsert("claim-x", OUJDA, "X", 1)
    PollRunsRepository(conn).create("p-base", OUJDA, "2026-01-01T00:00:00+00:00", "COMPLETE", True)
    apply_category_result(
        conn, OUJDA, "claim-x", CATEGORY, poll_run_id="p-base", category_status="COMPLETE",
        session_valid=True, observed_present=False,
    )
    PollRunsRepository(conn).create("p-partial", OUJDA, "2026-01-01T00:00:00+00:00", "PARTIAL", True)
    for status, valid in (("PARTIAL", True), ("FAILED", False), ("COMPLETE", False)):
        apply_category_result(
            conn, OUJDA, "claim-x", CATEGORY, poll_run_id="p-partial", category_status=status,
            session_valid=valid, observed_present=True,
        )
        assert CategoryPresenceRepository(conn).get(OUJDA, "claim-x", CATEGORY)["unread"] == 0
