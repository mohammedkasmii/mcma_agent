"""
mcma.portal.final_endpoints -- the permanent, un-disableable final-endpoint
blocklist (INV-4, ADR-0004, SAFETY_MODEL.md §3).

This list can never be shortened, flagged off, or bypassed by any
capability, mode, or contract -- mcma.portal.contracts.evaluate_request
checks it unconditionally, before any contract is even considered.
`createDevisDet` is deliberately absent: it is a phantom in the recovered
baseline's own block list with no real portal counterpart
(docs/recovery/PORTAL_CONTRACT.md §8); it is still denied, but by
default-deny (no reviewed contract exists for it), not by this list.
"""

from __future__ import annotations

PERMANENTLY_BLOCKED_ENDPOINTS: tuple[str, ...] = (
    "garageModifierValDevis",
    "validerDevis",
    "deleteDevisDet",
    "expertCloturerMission",
    "cloturerMission",
    "enregistrerMission",
    "expertEnregistrerMission",
    "ajouterDocument",
    "deleteDocument",
    "cloturerTraitement",
)


def is_permanently_blocked(canonical_path: str) -> bool:
    """Substring match against the CANONICAL path (never the raw one), so a
    trailing slash, encoded separator, or duplicate-slash variant of a
    blocked path cannot slip through -- canonicalization already normalized
    those away, and this check runs after it."""
    return any(name in canonical_path for name in PERMANENTLY_BLOCKED_ENDPOINTS)
