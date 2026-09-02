"""
mcma.notifications.extract -- read-only notification extraction through
ReadCapability, writing to persistence (INC-14, ADR-0006, INV-9).

Never issues a mutating request: every fetch goes through
ReadCapability.read_notifications(), which is itself read-only by
construction (mcma.portal.capabilities). This module never accepts or
constructs anything writer-shaped, and never calls any endpoint outside
ReadCapability's four-plus-one closed operations.

Account isolation is structural: every function here takes ONE
account_id and one ReadCapability instance opened for that ONE account's
own lease/session; nothing here accepts a "list of accounts" or shares a
reader/session/poll/claim across two accounts. Two different accounts
(e.g. one bound to the Oujda notification feed, another to Nador, even
when both are operated from the same office) are simply two independent
calls to run_poll() with two independent readers -- there is no code
path where one account's data could reach the other's rows (every
persistence write below is scoped by the account_id parameter, and the
schema's own composite FK/UNIQUE constraints reject any accidental
cross-account pairing at the DB layer, INC-10).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Sequence

from mcma.notifications.presence import apply_category_result
from mcma.notifications.rows import to_canonical_notification
from mcma.notifications.staging import stage_or_upsert_claim
from mcma.persistence.repositories.claims import (
    PollRunCategoriesRepository,
    PollRunsRepository,
    UnmatchedNotificationsRepository,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_poll(conn, account_id: str, reader, category_codes: Sequence[str], version: int) -> str:
    """Polls every given category CODE for this ONE account's reader,
    records a poll_runs row plus one poll_run_categories row per
    category, stages/upserts every notification seen, and applies the
    category-scoped presence lifecycle. Returns the poll_run_id.

    A category whose fetch raises is recorded FAILED for that category
    only -- it never aborts the other categories in the same run, and
    never raises out of run_poll() itself (a poll's own infrastructure
    failure is data, not an exception the caller must catch)."""
    poll_run_id = uuid.uuid4().hex
    started_at = _utcnow_iso()
    per_category_results = []
    overall_session_valid = True

    for category_code in category_codes:
        try:
            rows = await reader.read_notifications(category_code)
            per_category_results.append((category_code, "COMPLETE", True, rows))
        except Exception:
            per_category_results.append((category_code, "FAILED", False, ()))
            overall_session_valid = False

    overall_status = (
        "COMPLETE"
        if all(status == "COMPLETE" for _, status, _, _ in per_category_results)
        else ("PARTIAL" if any(status == "COMPLETE" for _, status, _, _ in per_category_results) else "FAILED")
    )

    PollRunsRepository(conn).create(
        poll_run_id, account_id, started_at, overall_status, session_valid=overall_session_valid,
        completed_at=_utcnow_iso(),
    )

    for category_code, status, session_valid, rows in per_category_results:
        PollRunCategoriesRepository(conn).create(
            poll_run_id, category_code, status, session_valid=session_valid, completed_at=_utcnow_iso(),
            rows_seen=len(rows) if status == "COMPLETE" else None,
        )

        seen_claim_pks = set()
        for notification in rows:
            try:
                if not isinstance(notification, dict):
                    raise TypeError("notification row is not an object")
                # The portal speaks IdSinistre/ReferenceCie/...; staging
                # speaks idSinistre/reference/.... Translating here, once,
                # is what stops every real row from looking identity-less
                # and landing in unmatched_notifications.
                claim_pk = stage_or_upsert_claim(
                    conn, account_id, to_canonical_notification(notification), version
                )
            except Exception:
                # A single malformed row is staged as an opaque unmatched
                # record and skipped -- it must never abort the whole
                # poll (run_poll's documented never-raises contract) or
                # silently drop evidence.
                UnmatchedNotificationsRepository(conn).create(
                    uuid.uuid4().hex,
                    account_id,
                    raw_payload=json.dumps({"malformed": True, "raw": repr(notification)[:500]}),
                    seen_at=_utcnow_iso(),
                )
                continue
            if claim_pk is not None:
                seen_claim_pks.add(claim_pk)

        if status != "COMPLETE" or not session_valid:
            continue  # never touch presence for a partial/failed/invalid category

        # Every claim previously observed under this account+category is
        # either re-affirmed present (seen this run) or counted absent.
        existing = conn.execute(
            "SELECT claim_pk FROM category_presence WHERE account_id = ? AND category_code = ?",
            (account_id, category_code),
        ).fetchall()
        known_claim_pks = {row["claim_pk"] for row in existing} | seen_claim_pks
        for claim_pk in known_claim_pks:
            apply_category_result(
                conn, account_id, claim_pk, category_code,
                poll_run_id=poll_run_id, category_status=status, session_valid=session_valid,
                observed_present=claim_pk in seen_claim_pks,
            )

    return poll_run_id
