"""
browser/mode_conventionne.py — Garage Conventionné writer DISABLED (INC-00)
===========================================================================
The baseline Garage Conventionné (PEC) row-writing workflow was permanently
removed at INC-00; both write entry points below refuse unconditionally
before any page interaction. The pure matching helpers (used by existing
read-only tests) are preserved unchanged.
"""

from typing import Optional, Tuple

from core.constants import RUBRIQUE_CATALOG, RUBRIQUE_MATCH_ALIASES
from core.utils import normalize_text
from core.logger import StructuredLogger


# Compatibility alias
GCLogger = StructuredLogger

_INC00_CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


def _match_single_rubrique(rub: dict, table_rows: list, used_indices: set) -> Tuple[Optional[dict], Optional[str]]:
    """Attempts to match a single rubrique against available Table 2 rows."""
    rub_id = str(rub.get("IdRubrique", "")).strip()
    rub_lib = rub.get("LibRubrique") or rub.get("_label") or RUBRIQUE_CATALOG.get(rub_id, "")
    norm_rub_lib = normalize_text(rub_lib)

    # 1. Exact normalized label match
    for row in table_rows:
        if row["index"] in used_indices:
            continue
        norm_row_lib = normalize_text(row["rubrique_label"])
        if norm_rub_lib and norm_rub_lib == norm_row_lib:
            return row, f"exact_label ('{norm_rub_lib}')"

    # 2. Known alias match for this IdRubrique
    known_aliases = RUBRIQUE_MATCH_ALIASES.get(rub_id, [])
    for row in table_rows:
        if row["index"] in used_indices:
            continue
        norm_row_lib = normalize_text(row["rubrique_label"])
        for alias in known_aliases:
            norm_alias = normalize_text(alias)
            if norm_alias and (norm_alias == norm_row_lib or norm_alias in norm_row_lib or norm_row_lib in norm_alias):
                return row, f"known_alias ('{alias}')"

    # 3. Substring inclusion match (min 4 chars)
    for row in table_rows:
        if row["index"] in used_indices:
            continue
        norm_row_lib = normalize_text(row["rubrique_label"])
        if len(norm_rub_lib) >= 4 and (norm_rub_lib in norm_row_lib or norm_row_lib in norm_rub_lib):
            return row, f"substring ('{norm_rub_lib}' ~ '{norm_row_lib}')"

    return None, None


def match_all_rubriques(rubriques: list, table_rows: list, logger: StructuredLogger) -> list:
    """Strict All-or-Nothing matching: every single rubrique must match exactly one row."""
    matches = []
    used_indices = set()
    unmatched = []

    for rub in rubriques:
        rub_id = str(rub.get("IdRubrique", "?"))
        rub_lib = rub.get("LibRubrique") or rub.get("_label") or RUBRIQUE_CATALOG.get(rub_id, "")

        row, method = _match_single_rubrique(rub, table_rows, used_indices)
        if row is not None:
            matches.append({
                "rubrique": rub,
                "target_label": row["rubrique_label"],
                "target_index": row["index"],
                "match_method": method,
            })
            used_indices.add(row["index"])
            logger.log("MATCH_RUBRIQUE", "OK",
                        f"Rubrique [{rub_id}] '{rub_lib}' -> Row '{row['rubrique_label']}' (via {method})")
        else:
            unmatched.append({"IdRubrique": rub_id, "LibRubrique": rub_lib})
            logger.log("MATCH_RUBRIQUE", "ERROR",
                        f"Rubrique [{rub_id}] '{rub_lib}' CANNOT be matched to any available Table 2 row!")

    if unmatched:
        logger.log("MATCH_ABORT", "ERROR",
                    f"All-or-Nothing Match Failed: {len(unmatched)}/{len(rubriques)} rubriques could not be matched. "
                    "Aborting workflow before touching any rows to prevent partial corruption.",
                    extra={
                        "unmatched_rubriques": unmatched,
                        "table_rows": [r["rubrique_label"] for r in table_rows],
                    })
        return []

    logger.log("MATCH_SUMMARY", "OK",
                f"All {len(matches)}/{len(rubriques)} rubriques successfully and uniquely matched to Table 2 rows.")
    return matches


async def _edit_single_row_dynamic(page, match: dict, logger: StructuredLogger = None) -> bool:
    """Permanently contained at INC-00: the baseline row editor no longer exists."""
    raise RuntimeError(_INC00_CONTAINMENT_MSG)


async def fill_garage_conventionne(page, data: dict, test_mode: bool = True, logger: StructuredLogger = None) -> dict:
    """Permanently contained at INC-00: the baseline writer no longer exists."""
    raise RuntimeError(_INC00_CONTAINMENT_MSG)


# Standard alias
fill_mode_conventionne = fill_garage_conventionne
