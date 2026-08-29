"""
workflows package — long-running business orchestrations.

Distinct from api/, which only translates HTTP to calls into here.
"""

from workflows.fill_dossier import process_workflow

__all__ = ["process_workflow"]
