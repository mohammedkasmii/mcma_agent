"""
mcma.notifications.staging -- idSinistre-less notifications go to
unmatched_notifications, NEVER into claims (INC-14, decision #10,
DATA_MODEL.md §3).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from mcma.persistence.repositories.claims import ClaimsRepository, UnmatchedNotificationsRepository


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stage_or_upsert_claim(conn, account_id: str, notification: dict, version: int):
    """Returns the claim_pk if the notification carried a mandatory
    idSinistre (upserted into claims); returns None if it lacked one (the
    notification is staged into unmatched_notifications instead --
    structurally never reaching claims). A missing mandatory identity is
    staged, never guessed."""
    id_sinistre = notification.get("idSinistre")
    if not id_sinistre:
        UnmatchedNotificationsRepository(conn).create(
            uuid.uuid4().hex,
            account_id,
            raw_payload=json.dumps(notification, sort_keys=True),
            seen_at=_utcnow_iso(),
            reference=notification.get("reference"),
        )
        return None

    claim_pk = f"{account_id}:{id_sinistre}"
    return ClaimsRepository(conn).upsert(
        claim_pk,
        account_id,
        str(id_sinistre),
        version,
        reference=notification.get("reference"),
        insured=notification.get("insured"),
        police=notification.get("police"),
        matricule_norm=notification.get("matricule_norm"),
    )
