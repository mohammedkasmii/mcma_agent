"""
mcma.planning.registry — WorkflowRegistry (ADR-0002): workflow name → pure
plan builder. Unknown workflow names fail closed (KeyError); duplicate
registration is refused.
"""

from typing import Callable, Dict

from mcma.domain.enums import RepairWorkflow
from mcma.planning.plan import ProposedPlan, build_mission_normal_plan, build_garage_conventionne_plan

PlanBuilder = Callable[[object], ProposedPlan]

# Pilot-integration correction (section 3): the one place a
# RepairWorkflow enum member (what mcma.planning.plan.detect_workflow()
# returns from typed evidence) maps to this registry's own workflow_name
# strings -- kept colocated with default_registry() so the two can never
# drift apart into two incompatible naming schemes.
WORKFLOW_NAME_BY_REPAIR_WORKFLOW: Dict[RepairWorkflow, str] = {
    RepairWorkflow.MODE_NORMAL: "mission_normal",
    RepairWorkflow.GARAGE_CONVENTIONNE: "garage_conventionne",
}


def workflow_name_for(repair_workflow: RepairWorkflow) -> str:
    try:
        return WORKFLOW_NAME_BY_REPAIR_WORKFLOW[repair_workflow]
    except KeyError as exc:
        raise KeyError(f"no registered workflow_name for {repair_workflow!r} — fail closed") from exc


class WorkflowRegistry:
    def __init__(self):
        self._builders: Dict[str, PlanBuilder] = {}

    def register(self, name: str, builder: PlanBuilder) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("workflow name must be non-empty")
        if name in self._builders:
            raise ValueError(f"workflow {name!r} already registered")
        self._builders[name] = builder

    def get(self, name: str) -> PlanBuilder:
        name = (name or "").strip()
        if name not in self._builders:
            raise KeyError(f"unknown workflow {name!r} — fail closed")
        return self._builders[name]

    def names(self) -> tuple:
        return tuple(sorted(self._builders))


def default_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register("mission_normal", build_mission_normal_plan)
    registry.register("garage_conventionne", build_garage_conventionne_plan)
    return registry
