"""
mcma.planning.registry — WorkflowRegistry (ADR-0002): workflow name → pure
plan builder. Unknown workflow names fail closed (KeyError); duplicate
registration is refused.
"""

from typing import Callable, Dict

from mcma.planning.plan import ProposedPlan, build_mission_normal_plan

PlanBuilder = Callable[[object], ProposedPlan]


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
    return registry
