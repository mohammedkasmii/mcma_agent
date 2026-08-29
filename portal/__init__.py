"""
portal package — everything that talks to the MCMA/MAMDA portal.

extractor.py  category-scoped alert extraction with discriminated outcomes (§8.2)
poller.py     scheduled multi-account poller, operating-window aware (§5, §10)
auth.py       per-account OTP login (§6)
"""

from portal.extractor import (
    CategoryResult,
    AccountPollResult,
    poll_account,
    to_legacy_payload,
    SUCCESS,
    EMPTY,
    FAILED,
)

__all__ = [
    "CategoryResult",
    "AccountPollResult",
    "poll_account",
    "to_legacy_payload",
    "SUCCESS",
    "EMPTY",
    "FAILED",
]
