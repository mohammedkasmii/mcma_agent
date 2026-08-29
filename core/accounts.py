"""
core/accounts.py — Multi-Account Profiles
==========================================
The four portal account profiles from PROJECT_ARCHITECTURE_BLUEPRINT.md §3.

MAMDA and MCMA share the exact same web application and DOM structure. The
four-way split is purely a login-credential and portfolio distinction, never a
code-path distinction: one extractor, one mapper, one filler, parameterised by
account_id.

Each account keeps its own Playwright storage state under sessions/. The legacy
single-account file (mcma_auth_state.json) is adopted by DEFAULT_ACCOUNT_ID on
first run so the existing installation keeps working.
"""

import os
from typing import Dict, List, Optional

SESSIONS_DIR = "sessions"

#: The account that inherits the legacy mcma_auth_state.json session.
DEFAULT_ACCOUNT_ID = "mcma_oujda"

LEGACY_AUTH_STATE_FILE = "mcma_auth_state.json"

BASE_URL = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/"

ACCOUNTS: List[Dict[str, str]] = [
    {
        "account_id": "mcma_oujda",
        "entity": "MCMA",
        "portfolio": "Oujda",
        "display_name": "MCMA — Oujda",
        "base_url": BASE_URL,
    },
    {
        "account_id": "mamda_oujda",
        "entity": "MAMDA",
        "portfolio": "Oujda",
        "display_name": "MAMDA — Oujda",
        "base_url": BASE_URL,
    },
    {
        "account_id": "mcma_nador",
        "entity": "MCMA",
        "portfolio": "Nador",
        "display_name": "MCMA — Nador",
        "base_url": BASE_URL,
    },
    {
        "account_id": "mamda_nador",
        "entity": "MAMDA",
        "portfolio": "Nador",
        "display_name": "MAMDA — Nador",
        "base_url": BASE_URL,
    },
]

ACCOUNT_IDS = [a["account_id"] for a in ACCOUNTS]


def get_account(account_id: str) -> Optional[Dict[str, str]]:
    for acc in ACCOUNTS:
        if acc["account_id"] == account_id:
            return acc
    return None


def auth_state_path(account_id: str) -> str:
    """Path to this account's Playwright storage state."""
    return os.path.join(SESSIONS_DIR, f"{account_id}.json")


def resolve_auth_state_path(account_id: str) -> Optional[str]:
    """
    Returns an existing session file for this account, or None.

    Falls back to the legacy single-account file for DEFAULT_ACCOUNT_ID so an
    existing installation is not forced to re-authenticate on upgrade.
    """
    path = auth_state_path(account_id)
    if os.path.exists(path):
        return path
    if account_id == DEFAULT_ACCOUNT_ID and os.path.exists(LEGACY_AUTH_STATE_FILE):
        return LEGACY_AUTH_STATE_FILE
    return None


def ensure_sessions_dir() -> None:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
