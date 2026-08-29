"""
core/features.py — Feature Flags
=================================
Single source of truth for optional subsystems that are present in the codebase
but not active in production.

Currently gates:
  - FORM_FILLING: the Phase 2 automated expertise form filling agent
    (Mode Normal + Mode Conventionné). The code is complete and unit-tested,
    but is NOT authorised to drive the live MCMA portal yet. See
    PROJECT_ARCHITECTURE_BLUEPRINT.md §11 and §15.

To unlock a feature, set its environment variable before starting the server:

    Windows (PowerShell):   $env:MCMA_ENABLE_FORM_FILLING = "1"; python main.py
    Windows (cmd):          set MCMA_ENABLE_FORM_FILLING=1 && python main.py
    Bash:                   MCMA_ENABLE_FORM_FILLING=1 python main.py

No source edit is required to unlock, and no source edit can accidentally
unlock: the default is OFF and lives in exactly one place.
"""

import os

TRUTHY = {"1", "true", "yes", "on", "oui"}


def _env_flag(name: str, default: bool = False) -> bool:
    """Reads a boolean feature flag from the environment."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

#: Phase 2 automated expertise form filling agent. OFF by default.
FORM_FILLING_ENABLED: bool = _env_flag("MCMA_ENABLE_FORM_FILLING", default=False)


FORM_FILLING_DISABLED_MESSAGE = (
    "Le module de remplissage automatique des formulaires est désactivé. "
    "Cette fonctionnalité (Mode Normal / Mode Conventionné) n'est pas encore "
    "autorisée sur le portail MCMA/MAMDA. "
    "Le centre de notifications reste pleinement disponible."
)


class FeatureDisabledError(RuntimeError):
    """Raised when a disabled feature is invoked."""


def require_form_filling() -> None:
    """
    Guard for every entry point into the form filling agent.

    Raises:
        FeatureDisabledError: when the feature is not enabled.
    """
    if not FORM_FILLING_ENABLED:
        raise FeatureDisabledError(FORM_FILLING_DISABLED_MESSAGE)


def feature_status() -> dict:
    """Returns the current flag state, for /health and diagnostics."""
    return {"form_filling": FORM_FILLING_ENABLED}
