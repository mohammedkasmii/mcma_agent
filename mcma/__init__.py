"""MCMA dossier preparation agent.

The package deliberately separates dossier interpretation, planning, browser
integration, and workflow execution.  Browser code is imported lazily so the
mapping and safety layers can be tested without Playwright installed.
"""

from .domain.models import RubricMode

__all__ = ["RubricMode"]
