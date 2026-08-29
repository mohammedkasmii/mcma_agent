"""
main.py — MCMA Automation API Server & Workflow Orchestrator
============================================================
FastAPI service and main automation orchestrator for filling MCMA insurance dossiers.
Coordinates navigation, form filling, mode routing (Normal vs Conventionné), and review pausing.
"""

import os
import sys
import json
import asyncio
import contextlib
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright

from core.config import (
    TEST_MODE,
    BASE_URL,
    AUTH_STATE_FILE,
    TEMP_DIR,
    LOGS_DIR,
)
from core.accounts import ACCOUNTS, ACCOUNT_IDS, resolve_auth_state_path
from core.window import WINDOW
from db.repository import Repository
from portal import auth as portal_auth
from portal.poller import poller_loop, poll_one_account, poll_all_accounts, account_lock
from core.features import (
    FORM_FILLING_ENABLED,
    FORM_FILLING_DISABLED_MESSAGE,
    FeatureDisabledError,
    feature_status,
    require_form_filling,
)
from core.logger import StructuredLogger
from mapper.wexia_mapper import WexiaToDossierMapper
from browser.safety_interceptor import install_safety_policy
from browser.mission_navigator import search_and_open_mission
from browser.form_filler import fill_main_form
from browser.mode_normal import fill_mode_normal
from browser.mode_conventionne import fill_mode_conventionne
from browser.notifications import fetch_all_notifications

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = FastAPI(
    title="MCMA RPA Automation Agent",
    description="Automated filing of expertise reports, garage devis, and notifications on MCMA portal.",
    version="3.0.0",
)

# ---------------------------------------------------------------------------
# Shared state: one repository and one background poller per process.
# ---------------------------------------------------------------------------
repo: Optional[Repository] = None
_poller_task: Optional[asyncio.Task] = None
_poller_stop: Optional[asyncio.Event] = None


def get_repo() -> Repository:
    """Lazily opens the database. Also used by tests to force initialisation."""
    global repo
    if repo is None:
        repo = Repository()
        for acc in ACCOUNTS:
            repo.upsert_account(
                account_id=acc["account_id"],
                entity=acc["entity"],
                portfolio=acc["portfolio"],
                display_name=acc["display_name"],
                base_url=acc["base_url"],
            )
    return repo


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Starts the background poller on boot and stops it cleanly on shutdown."""
    global _poller_task, _poller_stop
    get_repo()
    poller_disabled = os.environ.get(
        "MCMA_DISABLE_POLLER", ""
    ).strip().lower() in {"1", "true", "yes"}
    if poller_disabled:
        print("[i] Poller désactivé (MCMA_DISABLE_POLLER).")
    else:
        _poller_stop = asyncio.Event()
        _poller_task = asyncio.create_task(poller_loop(get_repo(), _poller_stop))

    yield

    if _poller_stop is not None:
        _poller_stop.set()
    if _poller_task is not None:
        _poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _poller_task
    if repo is not None:
        repo.close()


app.router.lifespan_context = lifespan


class FillDossierRequest(BaseModel):
    payload: Dict[str, Any]


class EmployeeActionUpdate(BaseModel):
    claim_id: int
    status: str
    note: Optional[str] = ""
    updated_by: Optional[str] = None


class WexiaDossierRequest(BaseModel):
    wexia_payload: Dict[str, Any]
    explicit_chiffrage_id: Optional[str] = None


class NotificationActionUpdate(BaseModel):
    reference: str
    status: str  # "TODO", "IN_PROGRESS", "DONE", "WAITING"
    note: Optional[str] = ""


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "mcma-automation-agent",
        "version": "2.0.0",
        "features": feature_status(),
    }


@app.get("/api/v1/features")
async def api_features():
    """Reports which optional subsystems are active, so the UI can hide disabled ones."""
    return {"status": "success", "features": feature_status()}


# ===========================================================================
# Operations Hub — multi-account state, accounts, login, refresh
# ===========================================================================


@app.get("/api/v1/state")
async def api_state(since: int = 0):
    """
    Delta feed polled by the dashboard every 15 seconds (§9.1).

    Returns only rows whose changed_version exceeds `since`, so the payload stays
    small no matter how many claims exist. `version` is monotonic and must be
    echoed back on the next call.
    """
    r = get_repo()
    state = r.get_state(since=since)
    state["window"] = WINDOW.status()
    state["counts"] = r.counts()
    state["features"] = feature_status()
    state["status"] = "success"
    return state


@app.get("/api/v1/accounts")
async def api_accounts():
    """The four account cards: identity, session health, and last successful poll."""
    r = get_repo()
    accounts = r.list_accounts(only_enabled=False)
    for acc in accounts:
        acc["has_session"] = bool(resolve_auth_state_path(acc["account_id"]))
        acc["login_in_flight"] = portal_auth.is_login_in_flight(acc["account_id"])
    return {
        "status": "success",
        "accounts": accounts,
        "window": WINDOW.status(),
        "warn_sessions": WINDOW.should_warn_sessions(),
    }


@app.post("/api/v1/accounts/{account_id}/login")
async def api_account_login(account_id: str):
    """
    Opens a visible login window ON THE SERVER for one account (§6).

    Refuses outside the operating window with a clear message, so nobody
    concludes the system is broken when the portal is simply closed.
    """
    if account_id not in ACCOUNT_IDS:
        raise HTTPException(status_code=404, detail=f"Compte inconnu : {account_id}")
    r = get_repo()
    try:
        result = await portal_auth.interactive_login(account_id)
    except portal_auth.LoginRefused as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result["success"]:
        r.set_session_health(account_id, "HEALTHY", validated=True)
        r.audit("ACCOUNT_LOGIN", actor="employee", account_id=account_id)
    else:
        r.set_session_health(account_id, "EXPIRED", error=result["message"])
    return {"status": "success" if result["success"] else "failed", **result}


@app.post("/api/v1/accounts/{account_id}/validate")
async def api_account_validate(account_id: str):
    """Headless session check — used by the start-of-shift validation."""
    if account_id not in ACCOUNT_IDS:
        raise HTTPException(status_code=404, detail=f"Compte inconnu : {account_id}")
    r = get_repo()
    result = await portal_auth.validate_session(account_id)
    r.set_session_health(
        account_id, result["health"],
        error=None if result["valid"] else result["message"],
        validated=result["valid"],
    )
    return {"status": "success", **result}


@app.post("/api/v1/refresh")
async def api_refresh(account_id: Optional[str] = None):
    """
    Manual refresh, on top of the automatic 5-minute poll.

    Unlike the old on-demand endpoint this reuses the poller's per-account lock,
    so repeated clicks queue behind each other instead of spawning a browser
    per click.
    """
    r = get_repo()
    if not WINDOW.is_open():
        raise HTTPException(status_code=409, detail=WINDOW.status().get(
            "message", "Portail fermé."))
    if account_id:
        if account_id not in ACCOUNT_IDS:
            raise HTTPException(status_code=404, detail=f"Compte inconnu : {account_id}")
        results = [await poll_one_account(r, account_id)]
    else:
        results = await poll_all_accounts(r)
    return {"status": "success", "results": results, "version": r.get_state()["version"]}


@app.post("/api/v1/employee-actions")
async def api_set_employee_action(action: EmployeeActionUpdate):
    """Sets a claim's work status and note, attributed to the employee's name."""
    if action.status not in ("TODO", "IN_PROGRESS", "DONE", "WAITING"):
        raise HTTPException(status_code=400, detail=f"Statut invalide : {action.status}")
    r = get_repo()
    result = r.set_employee_action(
        claim_id=action.claim_id,
        status=action.status,
        note=action.note or "",
        updated_by=action.updated_by,
    )
    r.audit("EMPLOYEE_ACTION", actor=action.updated_by or "inconnu",
            claim_id=action.claim_id, details={"status": action.status})
    return {"status": "success", **result}


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


@app.post("/api/v1/fill-dossier")
async def api_fill_dossier(req: FillDossierRequest):
    """
    Fills a dossier using pre-mapped MCMA payload contract.
    DISABLED: gated behind the FORM_FILLING feature flag (see core/features.py).
    """
    if not FORM_FILLING_ENABLED:
        raise HTTPException(status_code=503, detail=FORM_FILLING_DISABLED_MESSAGE)
    try:
        result = await process_workflow(req.payload)
        return {"status": "success", "result": result}
    except FeatureDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/fill-dossier-from-wexia")
async def api_fill_dossier_from_wexia(req: WexiaDossierRequest):
    """
    Translates raw Wexia JSON and executes MCMA filling.
    DISABLED: gated behind the FORM_FILLING feature flag (see core/features.py).
    """
    if not FORM_FILLING_ENABLED:
        raise HTTPException(status_code=503, detail=FORM_FILLING_DISABLED_MESSAGE)
    try:
        mapper = WexiaToDossierMapper()
        payload = mapper.map(req.wexia_payload, explicit_chiffrage_id=req.explicit_chiffrage_id)
        result = await process_workflow(payload)
        return {"status": "success", "result": result, "mapped_payload": payload}
    except FeatureDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/map-wexia-dossier")
async def api_map_wexia_dossier(req: WexiaDossierRequest):
    """
    Translates raw Wexia JSON into the MCMA payload contract WITHOUT touching a browser.
    Remains available while form filling is disabled: it is a pure, offline transformation.
    """
    try:
        mapper = WexiaToDossierMapper()
        payload = mapper.map(req.wexia_payload, explicit_chiffrage_id=req.explicit_chiffrage_id)
        return {"status": "success", "mapped_payload": payload}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def process_workflow(data: dict) -> dict:
    """
    Main workflow orchestrator:
      1. Launches browser with saved auth session.
      2. Installs safety route blockers if TEST_MODE is active.
      3. Searches and opens the target mission.
      4. Fills header text fields, select options, and checkboxes.
      5. Routes to Mode Normal or Garage Conventionné engine.
      6. Pauses browser for human visual review (zero final submissions).

    Innermost guard for the FORM_FILLING feature flag. Every caller — the HTTP API,
    run_dossier.py, and any future entry point — passes through here, so a disabled
    feature cannot reach a browser regardless of how it was invoked.
    """
    require_form_filling()

    os.makedirs(TEMP_DIR, exist_ok=True)

    if not os.path.exists(AUTH_STATE_FILE):
        raise FileNotFoundError(
            f"Auth file '{AUTH_STATE_FILE}' not found. Please run 'python auth_setup.py' first."
        )

    matricule = data.get("matricule", "")
    dossier_ref = data.get("dossier_reference", "")
    mode_reparation = data.get("mode_reparation", "normal")
    text_fields = data.get("text_fields", {})
    select_fields = data.get("select_fields", {})
    checkboxes = data.get("checkboxes", {})
    rubriques = data.get("rubriques", [])

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=AUTH_STATE_FILE)
        page = await context.new_page()

        try:
            # 1. Safety Interception (Network Level)
            await install_safety_policy(page, enabled=TEST_MODE)

            # 2. Search & Open Mission
            await search_and_open_mission(page, matricule=matricule, dossier_ref=dossier_ref)

            # 3. Fill Header Form Fields
            await fill_main_form(page, text_fields, select_fields, checkboxes)

            # 4. Mode Validation against MCMA live DOM
            has_table2 = await page.locator("#DevisDetTableVal, #blocDevisValide").count() > 0
            if mode_reparation == "conventionne" and not has_table2:
                print("\n    ⚠️  MODE WARNING: JSON specified 'conventionne', but Table 2 (#DevisDetTableVal) is not in DOM.")
                has_normal = await page.locator("#VehRepareI, #MontantReparation, #tableRapportDet").count() > 0
                if has_normal:
                    print("    ℹ️  Falling back to Mode Normal based on live DOM state.")
                    mode_reparation = "normal"

            # 5. Route Line Items (Rubriques)
            if mode_reparation == "conventionne":
                mode_result = await fill_mode_conventionne(page, data, test_mode=TEST_MODE)
            else:
                mode_result = await fill_mode_normal(page, data)

            print(f"    [Execution Result] {mode_result.get('status', '').upper()}: {mode_result.get('message', '')}")

            # 6. Safety Pause for Human Verification
            print("\n" + "=" * 75)
            print("  ⏸️  AUTOMATION COMPLETE — BROWSER PAUSED FOR YOUR INSPECTION")
            print("  👀  All fields, dropdowns, and rubriques have been populated on screen.")
            print("  🛡️  Zero final submissions were made (#DEVISDET_Btn and #Enregistrer are untouched).")
            print("  👉  Please review everything in the browser.")
            print("  👉  When finished, press 'Resume' in Playwright inspector or close the browser.")
            print("=" * 75 + "\n")

            await page.pause()
            await browser.close()

            return {
                "status": "success",
                "message": "Dossier filled and paused for human inspection (no submissions made).",
                "mode": mode_reparation,
                "mode_result": mode_result,
            }

        except Exception as e:
            await browser.close()
            return {"status": "failed", "error": str(e)}


if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    import socket

    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass

    print("\n" + "=" * 70)
    print("  🔔  MCMA SINISTRES — CENTRE DE NOTIFICATIONS & ACTIONS")
    print("=" * 70)
    print(f"  💻  Accès sur ce PC          : http://localhost:8000")
    print(f"  👥  Accès pour vos collègues : http://{local_ip}:8000")
    print("=" * 70)
    print("  👉  Gardez cette fenêtre ouverte pour que le serveur reste actif.\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)