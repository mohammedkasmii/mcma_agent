"""
mcma.domain.normalize — the single shared normalizer feeding every matcher
(DOMAIN_MODEL §3): strip accents (œ→oe), lowercase, collapse punctuation,
hyphens and repeated whitespace. Pure and idempotent.
"""

import re
import unicodedata
from typing import Optional

_LIGATURES = {"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE"}


def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    s = str(text)
    for src, dst in _LIGATURES.items():
        s = s.replace(src, dst)
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", ascii_text).lower()
    return " ".join(cleaned.split())
