"""
browser/mission_navigator.py — Mission Search & Selection Controller
====================================================================
Navigates MCMA search dashboard, queries by vehicle plate or reference,
locates matching dossier row in #listeSinistre, and opens the mission form.
"""

from typing import Optional
from core.config import DASHBOARD_URL
from core.utils import extract_search_matricule
from browser.dom_helpers import safe_fill_input


async def check_session_validity(page) -> bool:
    """Checks if the session is alive or redirected to the login page."""
    page_content = await page.content()
    is_expired = (
        "expert_.phtml" in page_content
        or "login" in page.url.lower()
        or await page.locator("input[name='login'], #login, #password").count() > 0
    )
    return not is_expired


async def search_and_open_mission(page, matricule: str, dossier_ref: str) -> bool:
    """
    Executes search on MCMA dashboard and clicks the matching mission link.
    """
    print(f"[*] Navigating to MCMA search/missions page: {DASHBOARD_URL}")
    await page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)

    # 1. Verify session
    if not await check_session_validity(page):
        print("\n" + "=" * 70)
        print("  ⚠️  MCMA SESSION HAS EXPIRED OR IS INVALID!")
        print("  🔑  Your login session in 'mcma_auth_state.json' needs to be refreshed.")
        print("  👉  Please run:  python auth_setup.py")
        print("=" * 70 + "\n")
        raise Exception("MCMA session expired. Please run 'python auth_setup.py' to log in and renew your session.")

    raw_matricule = matricule or ""
    search_matricule_num = extract_search_matricule(raw_matricule)
    search_query = search_matricule_num or raw_matricule or dossier_ref

    print(f"[*] Searching for mission in MCMA by Matricule: '{search_query}' (plate: '{raw_matricule}', ref: '{dossier_ref}')...")

    async def perform_search(mat_val: str = "", ref_val: str = ""):
        if await page.locator("#Matricule").count() > 0:
            await safe_fill_input(page, "#Matricule", str(mat_val).strip() if mat_val else "")
        if await page.locator("#ReferenceCie").count() > 0:
            await safe_fill_input(page, "#ReferenceCie", str(ref_val).strip() if ref_val else "")

        search_btn = page.locator("a[onclick*='rechercheMission'], a[onclick*='RechercheMission'], a:has-text('Rechercher'), button:has-text('Rechercher')").first
        if await search_btn.count() > 0:
            await search_btn.click()
        else:
            await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1500)

    async def find_mission_link():
        rows = page.locator("#listeSinistre tbody tr")
        count = await rows.count()
        if count == 0:
            return None

        valid_candidates = []
        for i in range(count):
            row = rows.nth(i)
            row_text = await row.inner_text()
            if "aucun" in row_text.lower() or "no data" in row_text.lower() or "no matching" in row_text.lower():
                continue
            link = row.locator("a[href*='gotoMission'], a[title*='Mission expertise'], div.text-blue a, a.btn-primary").first
            if await link.count() > 0 and await link.is_visible():
                if search_matricule_num and search_matricule_num in row_text:
                    return link
                if raw_matricule and raw_matricule in row_text:
                    return link
                if dossier_ref and dossier_ref in row_text:
                    return link
                valid_candidates.append(link)

        if len(valid_candidates) == 1 and (search_matricule_num or dossier_ref):
            return valid_candidates[0]

        return None

    # Try 1: Search by matricule number
    if search_matricule_num:
        await perform_search(mat_val=search_matricule_num)

    target_link = await find_mission_link()

    # Try 2: Search by ReferenceCie
    if not target_link and dossier_ref:
        print(f"    [i] Matricule not found in results. Retrying search by Dossier Reference: '{dossier_ref}'...")
        await perform_search(ref_val=dossier_ref)
        target_link = await find_mission_link()

    # Try 3: Clear filters to view all assigned missions
    if not target_link:
        print(f"    [i] Trying to show all assigned missions (clearing search filters)...")
        await perform_search(mat_val="", ref_val="")
        target_link = await find_mission_link()

    if target_link and await target_link.is_visible():
        mission_text = await target_link.inner_text()
        print(f"    [✓] Opening mission: '{mission_text.strip()}'...")
        await target_link.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
        print(f"    [✓] Mission form opened successfully!")

        # Verify opened mission context
        opened_info = await page.evaluate("""() => {
            const get = (sel) => {
                const el = document.querySelector(sel);
                return el ? (el.value || el.textContent || '').trim() : '';
            };
            return {
                matricule: get('#MatriculeVeh, #Immatriculation, input[name="MatriculeVeh"]'),
                dossier_ref: get('#ReferenceDossier, #RefDossier, input[name="ReferenceDossier"]'),
                mode_rep: get('#modeReparation, #ModeReparation, select[name="ModeReparation"]'),
            };
        }""")
        print(f"    [✓] Verified opened mission DOM: Matricule='{opened_info.get('matricule')}', Ref='{opened_info.get('dossier_ref')}'")
        return True
    else:
        table_text = ""
        if await page.locator("#listeSinistre tbody").count() > 0:
            table_text = await page.locator("#listeSinistre tbody").inner_text()

        print(f"\n    ⚠️  No mission auto-matched for Matricule '{raw_matricule}' / Ref '{dossier_ref}'.")
        print(f"    📋 Current Table Content: {table_text.strip() or 'Empty table'}")
        print(f"    ⏸️  Browser is paused on dashboard for manual selection.")
        print(f"    👉  Click the desired mission in browser, then press 'Resume' in Playwright inspector.\n")

        await page.pause()

        if await page.locator("#MontantReparation, #VehRepareI, #DevisDetTableVal").count() == 0:
            raise Exception("No mission opened. Please navigate to a mission to proceed.")
        return True
