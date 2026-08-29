"""
browser/mode_normal.py — Mode Normal writer DISABLED (INC-00 baseline containment)
==================================================================================
The baseline Mode Normal row-writing workflow (row creation, checkmark clicks,
forced charge-mutuelle writes) was permanently removed at INC-00. The entry
point below refuses unconditionally before any page interaction.
"""

_INC00_CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


async def fill_mode_normal(page, data: dict, logger=None) -> dict:
    """Permanently contained at INC-00: the baseline writer no longer exists."""
    raise RuntimeError(_INC00_CONTAINMENT_MSG)
