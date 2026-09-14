"""
mcma.notifications.presence -- the category-scoped three-poll lifecycle
(INC-14, ADR-0006, DATA_MODEL.md §3, decision #8, correction #1).

A presence transition for (account_id, claim_pk, category_code) happens
ONLY when THAT exact category's poll_run_categories row is
status='COMPLETE' AND session_valid=1. A PARTIAL/FAILED/invalid fetch of
a category never touches its counter and never affects any OTHER
category. Idempotent: reprocessing the same poll_run_id for a category
that was already applied is a no-op (correction SR-6) -- "three
consecutive" means three DISTINCT complete polls, tracked via
last_complete_poll_version (here: the poll_run's own SQLite rowid, a
free monotonic integer requiring no schema change).

Freshness ("Nouveau" / "Vu", migration 0004) rides on the same rule and
the same membership. The first complete, valid poll of a category for an
account is its baseline: what that poll observes is existing work. After
it, a membership is NEW (unread) when a complete poll observes it for the
first time, or when it comes back after the resolution lifecycle
completed (RESOLVED_ON_PORTAL). Coming back from MISSING_PENDING_
CONFIRMATION is the same appearance, so an ordinary refresh never makes a
seen notification new again. A partial/failed/invalid poll neither
establishes a baseline nor changes freshness. Freshness is never the
employee's workflow status (employee_actions) and never changes it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcma.persistence.repositories.claims import CategoryBaselinesRepository, CategoryPresenceRepository

RESOLVE_AFTER_CONSECUTIVE_ABSENCES = 3


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _poll_run_version(conn, poll_run_id: str) -> int:
    row = conn.execute("SELECT rowid AS v FROM poll_runs WHERE poll_run_id = ?", (poll_run_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown poll_run_id: {poll_run_id!r}")
    return row["v"]


def establish_category_baseline(conn, account_id: str, category_code: str, *, poll_run_id: str) -> int:
    """Records this poll as the category's freshness baseline unless one
    exists, and returns the baseline's poll version. The caller passes only
    a COMPLETE, valid-session category poll -- and passes every one,
    including a poll that returned no rows: an empty first sync is still a
    baseline, and what appears after it is new."""
    return CategoryBaselinesRepository(conn).ensure(
        account_id, category_code, _poll_run_version(conn, poll_run_id), _utcnow_iso()
    )


def apply_category_result(
    conn,
    account_id: str,
    claim_pk: str,
    category_code: str,
    *,
    poll_run_id: str,
    category_status: str,
    session_valid: bool,
    observed_present: bool,
) -> None:
    """Applies ONE category's poll outcome for ONE claim. Never mixes
    another category's evidence in (the caller invokes this once per
    (claim, category) pair it observed or expected)."""
    presence_repo = CategoryPresenceRepository(conn)
    poll_version = _poll_run_version(conn, poll_run_id)

    row = presence_repo.get(account_id, claim_pk, category_code)
    if row is None:
        presence_repo.ensure_row(account_id, claim_pk, category_code, since_version=poll_version)
        row = presence_repo.get(account_id, claim_pk, category_code)

    if category_status != "COMPLETE" or not session_valid:
        return  # PARTIAL/FAILED/invalid session -- counter and freshness untouched

    if row["last_complete_poll_version"] is not None and poll_version <= row["last_complete_poll_version"]:
        return  # idempotent replay of an already-applied (or older) poll

    baseline_version = establish_category_baseline(conn, account_id, category_code, poll_run_id=poll_run_id)

    if observed_present:
        if row["appeared_poll_version"] is None or row["presence_status"] == "RESOLVED_ON_PORTAL":
            # A new appearance. Only the baseline poll itself is exempt:
            # what it observes was already there before anyone looked.
            presence_repo.start_appearance(
                account_id,
                claim_pk,
                category_code,
                poll_version=poll_version,
                unread=baseline_version < poll_version,
                appeared_at=_utcnow_iso(),
            )
        presence_repo.update_lifecycle(
            account_id,
            claim_pk,
            category_code,
            present=True,
            presence_status="ACTIVE",
            consecutive_absence_count=0,
            last_complete_poll_version=poll_version,
            last_seen_poll_run_id=poll_run_id,
        )
        return

    new_count = row["consecutive_absence_count"] + 1
    new_status = (
        "RESOLVED_ON_PORTAL" if new_count >= RESOLVE_AFTER_CONSECUTIVE_ABSENCES else "MISSING_PENDING_CONFIRMATION"
    )
    presence_repo.update_lifecycle(
        account_id,
        claim_pk,
        category_code,
        present=False,
        presence_status=new_status,
        consecutive_absence_count=new_count,
        last_complete_poll_version=poll_version,
        last_seen_poll_run_id=poll_run_id,
    )
