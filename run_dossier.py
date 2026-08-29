"""
run_dossier.py — DISABLED (INC-00 baseline containment)
=======================================================
The baseline dossier form-filling automation was permanently removed at
INC-00. Running this script only raises the refusal below; it never reads
input folders, never launches a browser, and cannot be re-enabled through
CLI arguments, environment variables, or configuration.
"""

_INC00_CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


def main():
    raise SystemExit(_INC00_CONTAINMENT_MSG)


if __name__ == "__main__":
    main()
