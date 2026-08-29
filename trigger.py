"""
trigger.py — DISABLED (INC-00 baseline containment)
===================================================
The baseline HTTP smoke script that posted a test dossier payload to the
fill API was permanently removed at INC-00. This module refuses on
import/execution and performs no HTTP call.
"""

_INC00_CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)

raise SystemExit(_INC00_CONTAINMENT_MSG)
