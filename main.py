"""
main.py — MCMA Local Notifications Service (write capability removed at INC-00)
===============================================================================
Local, loopback-only FastAPI service for the read-only notification dashboard.
The baseline dossier form-filling workflow and its API routes were permanently
removed at INC-00; no configuration, environment variable, or flag restores
them. The only future live-write path is the post-G5 VerifiedMissionWriter.
"""

import os
import sys
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright

from core.config import (
    AUTH_STATE_FILE,
    LOGS_DIR,
)
from browser.notifications import fetch_all_notifications

_INC00_CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = FastAPI(
    title="MCMA Notifications (contained)",
    description=(
        "Temporarily contained local/read-only notifications service. "
        "Baseline dossier filling was permanently removed at INC-00."
    ),
    version="2.0.0",
)


class NotificationActionUpdate(BaseModel):
    reference: str
    status: str  # "TODO", "IN_PROGRESS", "DONE", "WAITING"
    note: Optional[str] = ""


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "mcma-automation-agent", "version": "2.0.0"}


@app.post("/api/v1/auth/launch-login")
async def api_launch_login():
    """Launches visible browser on the host PC for login & SMS OTP renewal."""
    try:
        import subprocess
        subprocess.Popen([sys.executable, "auth_setup.py"])
        return {"status": "started", "message": "Fenêtre de connexion MCMA ouverte sur le serveur."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/notification-actions")
async def api_get_notification_actions():
    """Returns saved employee actions, notes, and statuses from logs/notification_actions.json."""
    path = os.path.join(LOGS_DIR, "notification_actions.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {"status": "success", "actions": json.load(f)}
        except Exception:
            pass
    return {"status": "success", "actions": {}}


@app.post("/api/v1/notification-actions")
async def api_update_notification_action(action: NotificationActionUpdate):
    """Saves or updates an employee action/status/note for a claim reference."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    path = os.path.join(LOGS_DIR, "notification_actions.json")
    current_actions = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                current_actions = json.load(f)
        except Exception:
            pass

    from datetime import datetime
    current_actions[action.reference] = {
        "status": action.status,
        "note": action.note,
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(current_actions, f, ensure_ascii=False, indent=2)
        return {"status": "success", "reference": action.reference, "action": current_actions[action.reference]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/cached-notifications")
async def api_get_cached_notifications():
    """Returns the latest extracted notifications from logs/mcma_notifications.json instantly without launching browser."""
    path = os.path.join(LOGS_DIR, "mcma_notifications.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {"status": "success", "data": json.load(f)}
        except Exception:
            pass
    return {"status": "empty", "data": None}


@app.get("/api/v1/notifications")
async def api_get_notifications(headless: bool = True):
    """Fetches all active notifications, categories, and datatables from MCMA."""
    if not os.path.exists(AUTH_STATE_FILE):
        raise HTTPException(status_code=401, detail="MCMA auth session not found. Please run auth_setup.py first.")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(storage_state=AUTH_STATE_FILE)
            page = await context.new_page()
            try:
                notifs = await fetch_all_notifications(page, headless=headless)
                # Also save to cache
                os.makedirs(LOGS_DIR, exist_ok=True)
                cache_path = os.path.join(LOGS_DIR, "mcma_notifications.json")
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(notifs, f, ensure_ascii=False, indent=2)
                return {"status": "success", "data": notifs}
            finally:
                await browser.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def process_workflow(data: dict) -> dict:
    """Permanently contained at INC-00: the baseline writer no longer exists."""
    raise RuntimeError(_INC00_CONTAINMENT_MSG)


if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 70)
    print("  🔔  MCMA SINISTRES — CENTRE DE NOTIFICATIONS (LOCAL UNIQUEMENT)")
    print("=" * 70)
    print("  💻  Accès sur ce PC : http://localhost:8000")
    print("=" * 70)
    print("  👉  Gardez cette fenêtre ouverte pour que le serveur reste actif.\n")

    uvicorn.run(app, host="127.0.0.1", port=8000)
