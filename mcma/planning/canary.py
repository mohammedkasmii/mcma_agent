"""
mcma.planning.canary -- the ONE plan-level eligibility rule for the
supervised Mode Normal golden canary (docs/implementation/execution/
MODE_NORMAL_GOLDEN_CANARY.md).

Pure: a function of a ProposedPlan only. The central API (creation), the
central dispatcher (start) and the workstation runner (immediately before
opening a browser) all call this same function, so the three layers can
never disagree about which plans a canary may write.

A plan is canary-eligible only when ALL of these hold:
  - its workflow is exactly MODE_NORMAL (never Garage Conventionne/PEC);
  - it has no NeedsReview and is writeable (non-empty);
  - every row's rubrique has an agency-confirmed Mode Normal TVA profile
    (mcma.domain.rubriques.MODE_NORMAL_TVA_RATES: 1, 2, 3, 7, 8, 12, 16, 28).

The result is a fixed reason code (never free text derived from the
dossier), or None when eligible.
"""

from typing import Optional

from mcma.domain.enums import RepairWorkflow
from mcma.domain.rubriques import MODE_NORMAL_TVA_RATES

# The registry name of the only workflow the canary may execute.
MODE_NORMAL_CANARY_WORKFLOW_NAME = "mission_normal"

# The wire value naming this execution profile (claim envelope). Kept here,
# beside the rule it names; the workstation runner keeps a byte-identical
# literal (its package may not import server code).
EXECUTION_PROFILE_MODE_NORMAL_GOLDEN_CANARY = "MODE_NORMAL_GOLDEN_CANARY"

CANARY_RUBRIQUE_VALUES = frozenset(r.value for r in MODE_NORMAL_TVA_RATES)

REFUSAL_WRONG_WORKFLOW = "CANARY_WORKFLOW_NOT_MODE_NORMAL"
REFUSAL_NEEDS_REVIEW = "CANARY_PLAN_NEEDS_REVIEW"
REFUSAL_NOT_WRITEABLE = "CANARY_PLAN_NOT_WRITEABLE"
REFUSAL_UNPROFILED_RUBRIQUE = "CANARY_RUBRIQUE_OUTSIDE_TVA_PROFILE"


def mode_normal_canary_refusal(plan) -> Optional[str]:
    """None when `plan` may be executed by the canary, else a fixed reason
    code. Checks are ordered so the most fundamental refusal is reported."""
    if getattr(plan, "repair_workflow", None) is not RepairWorkflow.MODE_NORMAL:
        return REFUSAL_WRONG_WORKFLOW
    if plan.needs_review:
        return REFUSAL_NEEDS_REVIEW
    if not plan.is_writeable or not plan.steps:
        return REFUSAL_NOT_WRITEABLE
    if any(step.rubrique_id.value not in CANARY_RUBRIQUE_VALUES for step in plan.steps):
        return REFUSAL_UNPROFILED_RUBRIQUE
    return None
