"""
tests/test_operations_hub.py — Phase 1 Operations Hub
=====================================================
Covers the database, the lifecycle state machine, the operating window, and the
delta API.

The most important tests here are the §8.2 ones: a category that FAILED must
never advance the lifecycle. Getting that wrong archives the agency's whole
queue after three ticks.
"""

import os
import tempfile
from datetime import datetime, time, timedelta

import pytest

from core.window import OperatingWindow, TZ, using_fallback_timezone
from db.repository import Repository, MISSING_POLLS_BEFORE_ARCHIVE
from portal.extractor import CategoryResult, AccountPollResult, SUCCESS, EMPTY, FAILED

ACC = "mcma_oujda"
CAT = "CAT-1"


@pytest.fixture
def repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    r = Repository(path)
    r.upsert_account(ACC, "MCMA", "Oujda", "MCMA — Oujda", "https://example/")
    yield r
    r.close()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


def _items(*refs):
    return [{"reference": r, "societaire": f"SOC {r}", "matricule": "12345-A-7",
             "date_survenance": "19/06/2025 00:00"} for r in refs]


# ---------------------------------------------------------------------------
# Persistence basics
# ---------------------------------------------------------------------------

def test_claims_are_scoped_by_account_and_category(repo):
    """Two accounts may legitimately surface the same reference (§7.2)."""
    repo.upsert_account("mamda_oujda", "MAMDA", "Oujda", "MAMDA — Oujda", "https://example/")
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1"))
    repo.upsert_claims_for_category("mamda_oujda", CAT, "Missions", _items("R-1"))

    a = repo.find_claim(ACC, CAT, "R-1")
    b = repo.find_claim("mamda_oujda", CAT, "R-1")
    assert a["id"] != b["id"], "same reference on two accounts must not collide"


def test_reingest_is_idempotent(repo):
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1", "R-2"))
    new, seen = repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1", "R-2"))
    assert (new, seen) == (0, 2)


def test_employee_note_survives_reingest(repo):
    """The whole point of the dual lifecycle: portal data refreshes, notes persist."""
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1"))
    claim = repo.find_claim(ACC, CAT, "R-1")
    repo.set_employee_action(claim["id"], "DONE", "devis saisi", "ayman")

    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1"))

    row = repo.conn.execute(
        "SELECT employee_status, note, updated_by FROM employee_actions WHERE claim_id=?",
        (claim["id"],),
    ).fetchone()
    assert row["employee_status"] == "DONE"
    assert row["note"] == "devis saisi"
    assert row["updated_by"] == "ayman"


def test_date_normalised_to_iso_and_raw_kept(repo):
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1"))
    claim = repo.find_claim(ACC, CAT, "R-1")
    assert claim["date_survenance"].startswith("2025-06-19")
    assert claim["date_survenance_raw"] == "19/06/2025 00:00"


# ---------------------------------------------------------------------------
# Lifecycle state machine (§8)
# ---------------------------------------------------------------------------

def test_missing_claim_needs_three_polls_to_archive(repo):
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1", "R-2"))

    for expected in ("MISSING_PENDING_CONFIRMATION", "MISSING_PENDING_CONFIRMATION"):
        repo.reconcile_category(ACC, CAT, ["R-1"])
        assert repo.find_claim(ACC, CAT, "R-2")["portal_presence"] == expected

    repo.reconcile_category(ACC, CAT, ["R-1"])
    assert repo.find_claim(ACC, CAT, "R-2")["portal_presence"] == "RESOLVED_ON_PORTAL"
    assert repo.find_claim(ACC, CAT, "R-1")["portal_presence"] == "ACTIVE"


def test_reappearing_claim_resets_the_counter(repo):
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1", "R-2"))
    repo.reconcile_category(ACC, CAT, ["R-1"])
    repo.reconcile_category(ACC, CAT, ["R-1"])
    assert repo.find_claim(ACC, CAT, "R-2")["consecutive_missing_polls"] == 2

    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1", "R-2"))
    claim = repo.find_claim(ACC, CAT, "R-2")
    assert claim["consecutive_missing_polls"] == 0
    assert claim["portal_presence"] == "ACTIVE"


def test_archived_claim_keeps_its_note(repo):
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1"))
    claim = repo.find_claim(ACC, CAT, "R-1")
    repo.set_employee_action(claim["id"], "DONE", "traité et archivé", "ayman")

    for _ in range(MISSING_POLLS_BEFORE_ARCHIVE):
        repo.reconcile_category(ACC, CAT, [])

    assert repo.find_claim(ACC, CAT, "R-1")["portal_presence"] == "RESOLVED_ON_PORTAL"
    row = repo.conn.execute(
        "SELECT note FROM employee_actions WHERE claim_id=?", (claim["id"],)
    ).fetchone()
    assert row["note"] == "traité et archivé"


# ---------------------------------------------------------------------------
# §8.2 — the defect this whole design exists to prevent
# ---------------------------------------------------------------------------

def test_failed_category_may_not_reconcile():
    """A FAILED category must be ineligible for lifecycle advancement."""
    failed = CategoryResult(code=CAT, name="Missions", outcome=FAILED, error="timeout")
    assert failed.may_reconcile is False


def test_empty_and_success_categories_may_reconcile():
    """An EMPTY category answered honestly: nothing there. It may archive."""
    assert CategoryResult(code=CAT, name="M", outcome=EMPTY).may_reconcile is True
    assert CategoryResult(code=CAT, name="M", outcome=SUCCESS,
                          items=_items("R-1")).may_reconcile is True


def test_account_outcome_is_partial_when_any_category_failed():
    result = AccountPollResult(
        account_id=ACC,
        outcome="PARTIAL",
        categories=[
            CategoryResult(code="A", name="A", outcome=SUCCESS, items=_items("R-1")),
            CategoryResult(code="B", name="B", outcome=FAILED, error="boom"),
        ],
    )
    assert len(result.failed_categories) == 1
    assert result.total_alerts == 1


def test_skipping_a_failed_category_leaves_claims_untouched(repo):
    """
    End-to-end guard: simulate a poll where the category failed. The poller must
    skip reconciliation entirely, so nothing drifts towards archived.
    """
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1", "R-2"))
    failed = CategoryResult(code=CAT, name="Missions", outcome=FAILED, error="timeout")

    for _ in range(5):
        if failed.may_reconcile:                      # the poller's guard
            repo.reconcile_category(ACC, CAT, [])

    for ref in ("R-1", "R-2"):
        claim = repo.find_claim(ACC, CAT, ref)
        assert claim["portal_presence"] == "ACTIVE"
        assert claim["consecutive_missing_polls"] == 0


def test_poll_run_records_category_outcomes(repo):
    run_id = repo.start_poll_run(ACC)
    repo.record_category_outcome(run_id, "A", "Cat A", SUCCESS, alerts_seen=3)
    repo.record_category_outcome(run_id, "B", "Cat B", FAILED, error="timeout")
    repo.finish_poll_run(run_id, "PARTIAL")

    rows = {r["category_code"]: r["outcome"] for r in repo.conn.execute(
        "SELECT category_code, outcome FROM poll_run_categories WHERE poll_run_id=?", (run_id,))}
    assert rows == {"A": SUCCESS, "B": FAILED}

    acc = repo.get_account(ACC)
    assert acc["last_poll_outcome"] == "PARTIAL"
    assert acc["last_successful_poll_at"] is not None


def test_failed_poll_does_not_stamp_last_successful_poll(repo):
    run_id = repo.start_poll_run(ACC)
    repo.finish_poll_run(run_id, "AUTH_FAILED", error="expired")
    assert repo.get_account(ACC)["last_successful_poll_at"] is None


# ---------------------------------------------------------------------------
# Delta feed (§7.4)
# ---------------------------------------------------------------------------

def test_state_returns_only_changed_rows(repo):
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1", "R-2"))
    first = repo.get_state(since=0)
    assert len(first["claims"]) == 2

    assert repo.get_state(since=first["version"])["claims"] == []

    claim = repo.find_claim(ACC, CAT, "R-1")
    repo.set_employee_action(claim["id"], "DONE", "fini", "ayman")

    delta = repo.get_state(since=first["version"])
    assert len(delta["claims"]) == 1
    assert delta["claims"][0]["reference"] == "R-1"
    assert delta["claims"][0]["employee_status"] == "DONE"


def test_version_is_monotonic(repo):
    versions = []
    for ref in ("R-1", "R-2", "R-3"):
        repo.upsert_claims_for_category(ACC, CAT, "Missions", _items(ref))
        versions.append(repo.get_state()["version"])
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)


def test_archived_claims_are_reported_separately(repo):
    repo.upsert_claims_for_category(ACC, CAT, "Missions", _items("R-1"))
    baseline = repo.get_state()["version"]
    for _ in range(MISSING_POLLS_BEFORE_ARCHIVE):
        repo.reconcile_category(ACC, CAT, [])

    state = repo.get_state(since=baseline)
    assert len(state["archived"]) == 1
    assert state["claims"] == []


# ---------------------------------------------------------------------------
# Operating window (§5)
# ---------------------------------------------------------------------------

@pytest.fixture
def window():
    return OperatingWindow(
        start=time(7, 45), end=time(18, 0), days={0, 1, 2, 3, 4, 5},
        poll_interval_minutes=5, session_warning=time(17, 0),
    )


def _at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_window_open_during_business_hours(window):
    assert window.is_open(_at(2026, 8, 26, 10, 0)) is True      # Wednesday


def test_window_closed_after_18h(window):
    """The whole reason the poller exists on a clock — no overnight archiving."""
    assert window.is_open(_at(2026, 8, 26, 18, 1)) is False
    assert window.is_open(_at(2026, 8, 26, 23, 30)) is False
    assert window.is_open(_at(2026, 8, 27, 3, 0)) is False


def test_window_closed_before_opening(window):
    assert window.is_open(_at(2026, 8, 26, 7, 44)) is False
    assert window.is_open(_at(2026, 8, 26, 7, 45)) is True


def test_window_closed_on_sunday(window):
    assert window.is_open(_at(2026, 8, 30, 10, 0)) is False      # Sunday


def test_session_warning_fires_in_the_last_hour(window):
    assert window.should_warn_sessions(_at(2026, 8, 26, 16, 59)) is False
    assert window.should_warn_sessions(_at(2026, 8, 26, 17, 30)) is True
    assert window.should_warn_sessions(_at(2026, 8, 26, 18, 1)) is False


def test_next_open_skips_closed_days(window):
    nxt = window.next_open(_at(2026, 8, 29, 19, 0))             # Saturday evening
    assert nxt.weekday() == 0                                   # -> Monday
    assert nxt.hour == 7 and nxt.minute == 45


def test_real_timezone_is_available():
    """
    tzdata must be installed: Morocco drops to UTC+0 during Ramadan, so a fixed
    offset would silently shift the window by an hour once a year.
    """
    assert not using_fallback_timezone(), "install tzdata (see requirements.txt)"


def test_status_payload_when_closed(window):
    status = window.status(_at(2026, 8, 26, 20, 0))
    assert status["open"] is False
    assert "next_open" in status
    assert "fermé" in status["message"]
