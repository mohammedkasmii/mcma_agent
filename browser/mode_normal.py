"""
browser/mode_normal.py — Mode Normal Rubriques Controller
==========================================================
Handles standard Mode Normal line items creation:
Clicks 'Ajouter +', fills IdRubrique / MontantHT / Taxe, clicks row checkmark (✓),
triggers native MCMA calculations, and sets Montant à charge mutuelle.
"""

from typing import List, Dict, Any
from browser.dom_helpers import (
    safe_fill_input,
    safe_select_option,
    safe_toggle_checkbox,
    trigger_mcma_calculations,
)
from core.logger import StructuredLogger, capture_screenshot


async def fill_mode_normal(page, data: dict, logger: StructuredLogger = None) -> dict:
    """
    Executes Mode Normal rubriques workflow.
    """
    if logger is None:
        logger = StructuredLogger(prefix="normal")

    rubriques: List[Dict[str, Any]] = data.get("rubriques", [])
    if not rubriques:
        print("    [!] Mode Normal: No rubriques to process.")
        return {"status": "success", "message": "No rubriques to process", **logger.summary()}

    print(f"\n{'=' * 70}")
    print(f"  🔧  MODE NORMAL (Rapport d'expertise) AUTOMATION")
    print(f"  📝  {len(rubriques)} rubrique(s) to add")
    print(f"  📋  Log file: {logger.log_path}")
    print(f"{'=' * 70}\n")

    logger.log("START", "INFO", f"Starting Mode Normal for {len(rubriques)} rubriques")
    await capture_screenshot(page, logger, "normal_01_start")

    # Step 1: Ensure Véhicule Réparable (#VehRepareI) is checked to display the rubriques table
    repare_box = page.locator("#VehRepareI").first
    if await repare_box.count() > 0:
        if not await repare_box.is_checked():
            await safe_toggle_checkbox(page, "#VehRepareI", True)
            await page.wait_for_timeout(600)

    success_count = 0
    for idx, item in enumerate(rubriques, 1):
        rub_id = str(item.get("IdRubrique"))
        montant_ht = str(item.get("MontantHT", "0"))
        taxe = str(item.get("Taxe", "0"))
        label = item.get("LibRubrique") or item.get("_label", "")

        print(f"    [{idx}/{len(rubriques)}] [Ajouter +] -> [Id={rub_id}] {label} (HT: {montant_ht} DH, TVA: {taxe} DH)...")
        logger.log("ADD_ROW_START", "INFO", f"Adding rubrique [{rub_id}] '{label}' (HT={montant_ht}, TVA={taxe})")

        # Step 2: Click the green 'Ajouter +' button
        ajouter_btn = page.locator("a.btn-success:has-text('Ajouter'), a:has-text('Ajouter +'), a[onclick*='addRow']").first
        if await ajouter_btn.count() > 0:
            try:
                await ajouter_btn.scroll_into_view_if_needed(timeout=1500)
                await ajouter_btn.click(timeout=2500, force=True)
            except Exception:
                await page.evaluate("const b = document.querySelector('a.btn-success'); if(b) b.click();")
        else:
            await page.evaluate("if (typeof edataTable_RapportDet !== 'undefined') edataTable_RapportDet.addRow();")

        await page.wait_for_timeout(1000)

        # Step 3: Fill IdRubrique, MontantHT, and Taxe
        await safe_select_option(page, "#IdRubrique, table select[name*='IdRubrique'], select[name*='IdRubrique']", rub_id)
        await safe_fill_input(page, "#MontantHT, table input[name*='MontantHT'], input[name*='MontantHT']", montant_ht)
        if taxe and taxe != "0":
            await safe_fill_input(page, "#Taxe, table input[name*='Taxe'], input[name*='Taxe']", taxe)

        await page.wait_for_timeout(600)

        # Step 4: Click the 7th column green checkmark (✓)
        print("        -> Clicking green checkmark (✓)...")
        col7_loc = page.locator("table tr:has(#MontantHT) td:nth-child(7) a, table tr:has(#MontantHT) td:nth-child(7), table tbody tr:first-child td:nth-child(7) a, table tbody tr:first-child td:nth-child(7)").first
        if await col7_loc.count() > 0:
            try:
                await col7_loc.click(timeout=2000, force=True)
            except Exception:
                pass

        await page.evaluate("""() => {
            const ht = document.querySelector("#MontantHT") || document.querySelector("#IdRubrique");
            const row = ht ? ht.closest("tr") : document.querySelector("table tbody tr");
            if (row) {
                const tds = row.querySelectorAll("td");
                if (tds.length >= 7) {
                    const btn = tds[6].querySelector("a, button, i, span") || tds[6];
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")

        await page.wait_for_timeout(2000)
        logger.log("ADD_ROW_DONE", "OK", f"Rubrique [{rub_id}] locked in with checkmark.")
        print(f"    [✓] Rubrique [{rub_id}] locked in with checkmark (✓).")
        success_count += 1

    # Step 5: Calculations update
    print("[*] Updating automatic calculation fields (Montant Arrêté, Base Indemnité, etc.)...")
    await trigger_mcma_calculations(page)

    # Step 6: Force Charge Mutuelle
    print("[*] Setting Montant à charge mutuelle...")
    try:
        await page.evaluate("""() => {
            const repVal = document.querySelector('#MontantReparation')?.value || '0';
            const mutuelle = document.querySelector('#MontantChargeMutuelle');
            const societaire = document.querySelector('#MontantChargeSocietaire');
            if (mutuelle) {
                mutuelle.value = repVal;
                mutuelle.dispatchEvent(new Event('input', { bubbles: true }));
                mutuelle.dispatchEvent(new Event('change', { bubbles: true }));
                if (window.jQuery) { window.jQuery(mutuelle).trigger('keyup').trigger('change'); }
            }
            if (societaire) {
                societaire.value = '0';
                societaire.dispatchEvent(new Event('input', { bubbles: true }));
                societaire.dispatchEvent(new Event('change', { bubbles: true }));
                if (window.jQuery) { window.jQuery(societaire).trigger('keyup').trigger('change'); }
            }
        }""")
        logger.log("CHARGE_MUTUELLE", "OK", "Montant à charge mutuelle forced to repair total.")
    except Exception as e:
        logger.log("CHARGE_MUTUELLE", "WARN", f"Could not force charge mutuelle: {e}")

    await capture_screenshot(page, logger, "normal_02_completed")
    summary = logger.summary()
    return {
        "status": "success" if success_count == len(rubriques) else "partial",
        "message": f"Mode Normal: {success_count}/{len(rubriques)} rubriques added.",
        **summary,
    }
