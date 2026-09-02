"""
mcma.notifications.rows -- the one translation from the real SinAuto
getAlerte payload into this application's canonical notification shape.

The portal answers with its own vocabulary (IdSinistre, ReferenceCie,
NomSocietaire, Police, Matricule), while staging and the claims table
speak the canonical one (idSinistre, reference, insured, police,
matricule_norm). Without this step every real row looked like a row with
no identity and went to unmatched_notifications -- technically fail-safe,
but it meant a working portal produced an empty work queue.

Pure: dict in, dict out, no I/O and no persistence. That is what lets the
mapping be tested against recorded shapes without a portal.

A row already in canonical form passes through unchanged. Tests and any
future reviewed feed therefore do not have to pretend to be the portal.

NOTHING IS INVENTED HERE. A row whose IdSinistre is absent or blank comes
back without an idSinistre, so staging routes it to the existing
unmatched-notification path rather than guessing an identity -- the one
thing that must never happen to a claim record.
"""

from __future__ import annotations

import re

# Portal key -> canonical key. Only the fields the claims model actually
# stores are mapped; DateSin/Nature/SortSin are deliberately left out
# because there is nowhere truthful to put them and carrying extra
# portal-supplied personal data with no consumer is not free.
_FIELD_MAP = (
    ("IdSinistre", "idSinistre"),
    ("ReferenceCie", "reference"),
    ("NomSocietaire", "insured"),
    ("Police", "police"),
    ("Matricule", "matricule_norm"),
)

# ReferenceCie arrives wrapped in markup on the real portal (the proven
# extractor strips it with the same expression). The tags are removed
# rather than escaped: what belongs in a claim record is the reference an
# employee reads, and markup in a database column only ever becomes a
# rendering problem later.
_TAG = re.compile(r"<[^>]+>")


def _clean(value) -> str | None:
    if value is None:
        return None
    text = _TAG.sub("", str(value)).strip()
    return text or None


def to_canonical_notification(row: dict) -> dict:
    """One portal row in the application's own vocabulary.

    Canonical keys already present win: a caller that has done the
    mapping is not second-guessed.
    """
    if not isinstance(row, dict):
        raise TypeError("a notification row must be an object")

    canonical: dict = {}
    for portal_key, canonical_key in _FIELD_MAP:
        existing = row.get(canonical_key)
        cleaned = _clean(existing if existing not in (None, "") else row.get(portal_key))
        if cleaned is not None:
            canonical[canonical_key] = cleaned
    return canonical
