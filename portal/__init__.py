"""
portal package — everything that talks to the MCMA/MAMDA portal.

fetch.py      raw alert-row extraction; raises rather than returning [] (§8.2)
extractor.py  category-scoped outcomes: SUCCESS / EMPTY / FAILED (§8.2)
poller.py     scheduled multi-account poller, operating-window aware (§5, §10)
auth.py       per-account OTP login (§6)
"""

from portal.fetch import fetch_category_rows, CategoryFetchError
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
    "fetch_category_rows",
    "CategoryFetchError",
    "CategoryResult",
    "AccountPollResult",
    "poll_account",
    "to_legacy_payload",
    "SUCCESS",
    "EMPTY",
    "FAILED",
]
