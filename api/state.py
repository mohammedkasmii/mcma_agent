"""
api/state.py — Dashboard State & Employee Actions
==================================================
The delta feed the dashboard polls every 15 seconds, plus the single write
endpoint for employee work status.

BLUEPRINT §7.4, §9.1. Only rows whose changed_version exceeds `since` are
returned, so the payload stays small regardless of how many claims exist.
"""

from fastapi import APIRouter, HTTPException

from api.deps import get_repo
from api.schemas import EmployeeActionUpdate
from core.features import feature_status
from core.window import WINDOW

router = APIRouter(prefix="/api/v1", tags=["state"])

VALID_STATUSES = ("TODO", "IN_PROGRESS", "DONE", "WAITING")


@router.get("/state")
async def api_state(since: int = 0):
    """
    Delta feed. `version` is monotonic and must be echoed back on the next call.
    """
    repo = get_repo()
    state = repo.get_state(since=since)
    state["window"] = WINDOW.status()
    state["counts"] = repo.counts()
    state["features"] = feature_status()
    state["status"] = "success"
    return state


@router.post("/employee-actions")
async def api_set_employee_action(action: EmployeeActionUpdate):
    """
    Sets a claim's work status and note.

    This is the ONLY path that writes employee work state. The legacy
    /notification-actions endpoint wrote to logs/notification_actions.json with
    an unguarded read-modify-write; it was removed rather than left as a second,
    racy store that silently diverged from the database.
    """
    if action.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Statut invalide : {action.status}")

    repo = get_repo()
    result = repo.set_employee_action(
        claim_id=action.claim_id,
        status=action.status,
        note=action.note or "",
        updated_by=action.updated_by,
    )
    repo.audit(
        "EMPLOYEE_ACTION",
        actor=action.updated_by or "inconnu",
        claim_id=action.claim_id,
        details={"status": action.status},
    )
    return {"status": "success", **result}
