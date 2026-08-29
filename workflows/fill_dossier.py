"""
workflows/fill_dossier.py — Expertise Form Filling Orchestrator
===============================================================
Drives a full dossier through the MCMA portal: navigate, fill the header, route
to Mode Normal or Garage Conventionne, then stop for human review.

This is business logic, not an API concern, which is why it no longer lives in
main.py. It is also the innermost guard for the FORM_FILLING feature flag: every
caller - the HTTP API, run_dossier.py, any future entry point - passes through
here, so a disabled feature cannot reach a browser regardless of how it was
invoked.
"""

import os

from playwright.async_api import async_playwright

from browser.form_filler import fill_main_form
from browser.mission_navigator import search_and_open_mission
from browser.mode_conventionne import fill_mode_conventionne
from browser.mode_normal import fill_mode_normal
from browser.safety_interceptor import install_safety_policy
from core.config import AUTH_STATE_FILE, TEMP_DIR, TEST_MODE
from core.features import require_form_filling


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
