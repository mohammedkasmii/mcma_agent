"""
main.py — MCMA Automation API Server & Workflow Orchestrator
============================================================
FastAPI service and main automation orchestrator for filling MCMA insurance dossiers.
Coordinates navigation, form filling, mode routing (Normal vs Conventionné), and review pausing.
"""

import os
import sys
import json
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
    version="2.0.0",
)


class FillDossierRequest(BaseModel):
    payload: Dict[str, Any]


class WexiaDossierRequest(BaseModel):
    wexia_payload: Dict[str, Any]
    explicit_chiffrage_id: Optional[str] = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "mcma-automation-agent", "version": "2.0.0"}


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
    """Fills a dossier using pre-mapped MCMA payload contract."""
    try:
        result = await process_workflow(req.payload)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/fill-dossier-from-wexia")
async def api_fill_dossier_from_wexia(req: WexiaDossierRequest):
    """Translates raw Wexia JSON and executes MCMA filling."""
    try:
        mapper = WexiaToDossierMapper()
        payload = mapper.map(req.wexia_payload, explicit_chiffrage_id=req.explicit_chiffrage_id)
        result = await process_workflow(payload)
        return {"status": "success", "result": result, "mapped_payload": payload}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def process_workflow(data: dict) -> dict:
    """
    Main workflow orchestrator:
      1. Launches browser with saved auth session.
      2. Installs safety route blockers if TEST_MODE is active.
      3. Searches and opens the target mission.
      4. Fills header text fields, select options, and checkboxes.
      5. Routes to Mode Normal or Garage Conventionné engine.
      6. Pauses browser for human visual review (zero final submissions).
    """
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
    uvicorn.run(app, host="0.0.0.0", port=8000)