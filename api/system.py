"""
api/system.py — Health & Feature Reporting
===========================================
"""

from fastapi import APIRouter

from core.features import feature_status
from core.window import WINDOW

router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check():
    """Liveness probe. Also reports which optional subsystems are active."""
    return {
        "status": "ok",
        "service": "mcma-operations-hub",
        "version": "3.0.0",
        "features": feature_status(),
        "window": WINDOW.status(),
    }


@router.get("/api/v1/features")
async def api_features():
    """Lets the dashboard hide controls for disabled subsystems."""
    return {"status": "success", "features": feature_status()}
