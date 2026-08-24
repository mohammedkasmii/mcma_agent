import re
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from playwright.async_api import async_playwright
from mapper import WexiaToDossierMapper
import pymupdf as fitz
import os
import sys
import uuid

# ============================================================
# ⚠️  TEST MODE — Set to False to enable Save & GED Upload
# When True: form is filled but NEVER saved or submitted.
# ============================================================
TEST_MODE = True

app = FastAPI(title="MCMA Dossier Automation API")

def extract_search_matricule(plate: str) -> str:
    """
    Extracts the primary leading numeric block for MCMA search.
    Example: '34602-B-7' -> '34602', '05149/A/77' -> '05149'
    """
    if not plate:
        return ""
    plate_clean = str(plate).strip()
    match = re.search(r"\d+", plate_clean)
    if match:
        return match.group(0)
    return plate_clean

async def safe_fill_input(page, selector: str, value: str, timeout_ms: int = 2000) -> bool:
    """
    Safely fills an input field. Uses Playwright fill when visible and dispatches
    input, change, and keyup events (including inline onkeyup/onchange and jQuery triggers)
    so calculated fields update automatically.
    """
    if not value or str(value).strip() == "":
        return False
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False
    try:
        if await loc.is_visible():
            await loc.fill(str(value), timeout=timeout_ms)
        else:
            await loc.evaluate("""(el, val) => {
                el.value = val;
            }""", str(value))
        
        # Fire full event cycle to trigger MCMA JavaScript calculations
        await loc.evaluate("""(el, val) => {
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '0' }));
            if (typeof el.onkeyup === 'function') {
                try { el.onkeyup(); } catch(e) {}
            }
            if (typeof el.onchange === 'function') {
                try { el.onchange(); } catch(e) {}
            }
            if (window.jQuery) {
                try { window.jQuery(el).trigger('input').trigger('change').trigger('keyup'); } catch(e) {}
            }
        }""", str(value))
        return True
    except Exception:
        try:
            await loc.evaluate("""(el, val) => {
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                if (typeof el.onkeyup === 'function') el.onkeyup();
                if (typeof el.onchange === 'function') el.onchange();
                if (window.jQuery) window.jQuery(el).trigger('keyup').trigger('change');
            }""", str(value))
            return True
        except Exception:
            return False


async def trigger_mcma_calculations(page):
    """
    Explicitly invokes MCMA's native calculation formulas:
      - CalculerMontantDommage()  -> MontantDommage = ValeurVenale - MontantEpave
      - CalculerMntArrete()       -> MontantArrete = MontantReparation - MontantVetuste
                                     BaseIndemnite = MontantArrete - MontantFranchise - MontantRemise
      - CalculerMontantTTC()      -> MontantTTC = MontantHT + Taxe
    """
    try:
        res = await page.evaluate("""() => {
            if (typeof CalculerMontantDommage === 'function') {
                try { CalculerMontantDommage(); } catch(e) {}
            }
            if (typeof CalculerMntArrete === 'function') {
                try { CalculerMntArrete(); } catch(e) {}
            }
            if (typeof CalculerMontantTTC === 'function') {
                try { CalculerMontantTTC(); } catch(e) {}
            }
            if (typeof CalculerMontantVetuste === 'function') {
                try { CalculerMontantVetuste(); } catch(e) {}
            }

            const calcSelectors = [
                '#ValeurVenale', '#MontantEpave', '#MontantReparation', 
                '#MontantTVA', '#MontantVetusteTotal', '#MontantFranchise', 
                '#MontantRemise', '#MontantArrete', '#BaseIndemnite', '#MontantDommage'
            ];
            calcSelectors.forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    if (typeof el.onkeyup === 'function') {
                        try { el.onkeyup(); } catch(e) {}
                    }
                    if (typeof el.onchange === 'function') {
                        try { el.onchange(); } catch(e) {}
                    }
                    if (window.jQuery) {
                        try { window.jQuery(el).trigger('keyup').trigger('change'); } catch(e) {}
                    }
                }
            });

            return {
                montantArrete: document.querySelector('#MontantArrete')?.value || null,
                baseIndemnite: document.querySelector('#BaseIndemnite')?.value || null,
                montantDommage: document.querySelector('#MontantDommage')?.value || null
            };
        }""")
        if res:
            print(f"    [🧮 Auto-Calculations] MontantArrêté={res.get('montantArrete')}, BaseIndemnité={res.get('baseIndemnite')}, MontantDommage={res.get('montantDommage')}")
    except Exception:
        pass

async def safe_select_option(page, selector: str, value: str, timeout_ms: int = 2000) -> bool:
    """
    Safely selects a dropdown option. Handles Select2 widgets by destroying them first,
    setting the native <select> value, then re-initializing Select2.
    """
    if not value or str(value).strip() == "":
        return False
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False
    
    try:
        # Step 1: Destroy Select2 if present, set native value, reinit Select2
        result = await page.evaluate("""([sel, val]) => {
            const el = document.querySelector(sel);
            if (!el) return 'not_found';
            
            const hasSelect2 = (typeof jQuery !== 'undefined') && jQuery(sel).data('select2');
            
            // Destroy Select2 so native <select> becomes visible
            if (hasSelect2) {
                try { jQuery(sel).select2('destroy'); } catch(e) {}
            }
            
            // Set the native select value
            el.value = val;
            
            // Verify the value was actually set
            if (el.value != val) {
                // Try finding option by value attribute
                for (let opt of el.options) {
                    if (opt.value == val) {
                        opt.selected = true;
                        el.value = val;
                        break;
                    }
                }
            }
            
            // Dispatch change events
            el.dispatchEvent(new Event('change', { bubbles: true }));
            
            // Re-initialize Select2
            if (hasSelect2 && typeof jQuery !== 'undefined') {
                try {
                    jQuery(sel).select2();
                    jQuery(sel).trigger('change');
                } catch(e) {}
            }
            
            return el.value == val ? 'ok' : 'mismatch';
        }""", [selector, str(value)])
        
        if result == 'ok':
            return True
    except Exception:
        pass

    # Fallback: try standard Playwright if element is now visible
    try:
        if await loc.is_visible():
            await loc.select_option(str(value), timeout=timeout_ms)
            return True
    except Exception:
        pass
    
    return False


async def safe_toggle_checkbox(page, selector: str, is_checked: bool, timeout_ms: int = 2000) -> bool:
    """Safely toggles a checkbox with JS fallback."""
    loc = page.locator(selector).first
    if await loc.count() == 0:
        return False
    try:
        current = await loc.is_checked()
        if current != is_checked:
            if await loc.is_visible():
                await loc.click(timeout=timeout_ms)
            else:
                await loc.evaluate("""(el, chk) => {
                    el.checked = chk;
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""", is_checked)
        return True
    except Exception:
        return False

def compress_pdf(input_path: str, output_path: str) -> str:
    """Compresses heavy PDF files by cleaning streams and garbage collecting objects."""
    try:
        if not os.path.exists(input_path):
            print(f"[!] Warning: File not found: {input_path}")
            return input_path
        doc = fitz.open(input_path)
        doc.save(output_path, garbage=4, deflate=True, clean=True)
        doc.close()
        
        orig_size = os.path.getsize(input_path) / (1024 * 1024)
        new_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[PDF] Compressed {os.path.basename(input_path)}: {orig_size:.2f}MB -> {new_size:.2f}MB")
        return output_path
    except Exception as e:
        print(f"[PDF] Compression error: {e}")
        return input_path

# The payload model matches the structure of the incoming agency JSON file
class DossierPayload(BaseModel):
    dossier_reference: str = ""  # Extracted from JSON to search the dossier
    matricule: str = ""          # Alternative search key if needed
    text_fields: dict = {}
    select_fields: dict = {}
    checkboxes: dict = {}
    rubriques: list = []
    documents: list = []

async def process_workflow(data: dict):
    if not os.path.exists("mcma_auth_state.json"):
        return {"status": "error", "message": "mcma_auth_state.json missing. Run auth_setup.py first!"}

    os.makedirs("temp", exist_ok=True)

    async with async_playwright() as p:
        # Headless=False so you can visually watch the search and fill process
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="mcma_auth_state.json")
        page = await context.new_page()

        try:
            # --- STEP 1: GO TO SEARCH PAGE ---
            print(f"[*] Navigating to MCMA search/missions page...")
            await page.goto("https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/")
            await page.wait_for_load_state("domcontentloaded")

            # --- STEP 2: SEARCH USING IMMATRICULATION NUMBER ---
            raw_matricule = data.get("matricule", "")
            dossier_ref = data.get("dossier_reference", "")
            
            # Extract search number (e.g. '34602' from '34602-B-7')
            search_matricule_num = extract_search_matricule(raw_matricule)
            search_query = search_matricule_num or raw_matricule or dossier_ref
            
            if not search_query:
                raise Exception("No Immatriculation (matricule) or Dossier Reference provided to search!")

            print(f"[*] Searching for mission in MCMA by Matricule number: '{search_query}' (full plate: '{raw_matricule}')...")
            
            # Reset / fill search inputs
            if await page.locator("#Matricule").count() > 0 and search_query:
                await safe_fill_input(page, "#Matricule", str(search_query).strip())
                print(f"    [✓] Filled search input #Matricule = '{search_query}'")
            elif await page.locator("#ReferenceCie").count() > 0 and dossier_ref:
                await safe_fill_input(page, "#ReferenceCie", str(dossier_ref).strip())
                print(f"    [✓] Filled search input #ReferenceCie = '{dossier_ref}'")

            # Trigger the search action
            search_btn = page.locator("a[onclick*='RechercheMission'], a:has-text('Rechercher'), button:has-text('Rechercher')").first
            if await search_btn.count() > 0:
                await search_btn.click()
            else:
                await page.keyboard.press("Enter")
                
            # Wait for search AJAX to complete and table to refresh
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

            # --- STEP 3: SELECT THE MATCHING DOSSIER FROM #listeSinistre TABLE ---
            print(f"[*] Locating mission in results table (#listeSinistre)...")
            
            rows = page.locator("#listeSinistre tbody tr")
            row_count = await rows.count()
            target_link = None

            if row_count > 0:
                for i in range(row_count):
                    row = rows.nth(i)
                    row_text = await row.inner_text()
                    
                    if "aucun" in row_text.lower() or "no data" in row_text.lower() or "no matching" in row_text.lower():
                        break
                        
                    link = row.locator("a[href*='gotoMission'], a[title*='Mission expertise'], div.text-blue a").first
                    if await link.count() > 0 and await link.is_visible():
                        if search_matricule_num in row_text or raw_matricule in row_text:
                            target_link = link
                            print(f"    [✓] Found matching row for plate '{raw_matricule}': {row_text.splitlines()[0] if row_text else ''}")
                            break
                        elif target_link is None:
                            target_link = link

            if target_link and await target_link.is_visible():
                mission_text = await target_link.inner_text()
                print(f"    [✓] Opening mission: '{mission_text.strip()}'...")
                await target_link.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(1500)
                print(f"    [✓] Mission form opened successfully!")
            else:
                table_text = ""
                if await page.locator("#listeSinistre tbody").count() > 0:
                    table_text = await page.locator("#listeSinistre tbody").inner_text()
                
                raise Exception(
                    f"Vehicle with Matricule '{raw_matricule}' (searched '{search_query}') NOT FOUND in MCMA.\n"
                    f"Table result: {table_text.strip() or 'No matching records'}\n"
                    f"Please verify that this matricule has an assigned mission in your account."
                )

            # --- STEP 4: FILL MAIN FORM TEXT FIELDS ---
            print(f"[*] Filling main form text fields...")
            for field_id, value in data.get("text_fields", {}).items():
                if value is not None and str(value).strip() != "":
                    selector = f"#{field_id}"
                    filled = await safe_fill_input(page, selector, str(value))
                    
                    if filled:
                        print(f"    [✓] Filled text field #{field_id} = {str(value)[:40]}...")
                    elif field_id in ("ValeurVenale", "ValeurVenaleEstime"):
                        alt_id = "ValeurVenaleEstime" if field_id == "ValeurVenale" else "ValeurVenale"
                        alt_filled = await safe_fill_input(page, f"#{alt_id}", str(value))
                        if alt_filled:
                            print(f"    [✓] Filled text field #{alt_id} = {str(value)[:40]}...")
                        else:
                            print(f"    [!] Field #{field_id} skipped (not on page)")
                    else:
                        print(f"    [!] Field #{field_id} not present/visible (skipped)")

            # Trigger initial calculation after text fields
            await trigger_mcma_calculations(page)

            # --- STEP 5: SELECT DROPDOWN OPTIONS ---
            print(f"[*] Selecting dropdown options...")
            for field_id, value in data.get("select_fields", {}).items():
                if value is not None and str(value).strip() != "":
                    selector = f"#{field_id}"
                    selected = await safe_select_option(page, selector, str(value))
                    if selected:
                        print(f"    [✓] Selected #{field_id} = {value}")
                    else:
                        print(f"    [!] Dropdown #{field_id} not present/visible (skipped)")

            # --- STEP 6: TOGGLE CHECKBOXES ---
            print(f"[*] Toggling checkboxes...")
            for field_id, is_checked in data.get("checkboxes", {}).items():
                selector = f"#{field_id}"
                toggled = await safe_toggle_checkbox(page, selector, is_checked)
                if toggled:
                    print(f"    [✓] Toggled checkbox #{field_id} -> {is_checked}")
                else:
                    print(f"    [!] Checkbox #{field_id} not present/visible (skipped)")
            await page.wait_for_timeout(500)

            # --- STEP 7: INSERT LINE ITEMS (RUBRIQUES) ---
            rubriques = data.get("rubriques", [])
            if rubriques:
                print(f"[*] Adding {len(rubriques)} line item(s) (rubriques)...")
                try:
                    # Ensure Véhicule Réparable (#VehRepareI) is checked to display the rubriques table
                    repare_box = page.locator("#VehRepareI").first
                    if await repare_box.count() > 0:
                        if not await repare_box.is_checked():
                            await safe_toggle_checkbox(page, "#VehRepareI", True)
                            await page.wait_for_timeout(600)

                    for idx, item in enumerate(rubriques, 1):
                        rub_id = str(item.get("IdRubrique"))
                        montant_ht = str(item.get("MontantHT", "0"))
                        taxe = str(item.get("Taxe", "0"))
                        label = item.get("_label", "")

                        print(f"    [{idx}/{len(rubriques)}] [Ajouter +] -> [Id={rub_id}] {label} (HT: {montant_ht} DH, TVA: {taxe} DH)...")
                        
                        # Step 1: Click the green 'Ajouter +' button
                        ajouter_btn = page.locator("a.btn-success:has-text('Ajouter'), a:has-text('Ajouter +'), a[onclick*='addRow']").first
                        if await ajouter_btn.count() > 0:
                            try:
                                await ajouter_btn.scroll_into_view_if_needed(timeout=1500)
                                await ajouter_btn.click(timeout=2500, force=True)
                            except Exception:
                                await page.evaluate("const b = document.querySelector('a.btn-success'); if(b) b.click();")
                        else:
                            await page.evaluate("if (typeof edataTable_RapportDet !== 'undefined') edataTable_RapportDet.addRow();")

                        # Wait for the editable row to appear in the table
                        try:
                            await page.wait_for_selector("table tbody tr select, #IdRubrique, table tbody tr input[name*='MontantHT']", timeout=5000)
                        except Exception:
                            await page.wait_for_timeout(1000)
                        
                        # Step 2: Fill the active row fields via jQuery & native DOM with verification
                        filled_info = await page.evaluate("""(data) => {
                            // Find the active row in edit mode
                            const row = document.querySelector("table tbody tr:has(select), table tbody tr:has(input), table tbody tr.editing, table tbody tr:first-child");
                            if (!row) return { success: false, reason: "No active row found" };

                            // 1. Set IdRubrique select
                            const selectEl = row.querySelector("select");
                            if (selectEl) {
                                selectEl.value = data.rub_id;
                                if (window.jQuery) {
                                    window.jQuery(selectEl).val(data.rub_id).trigger('change');
                                }
                                selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                            }

                            // 2. Set Montant HT input
                            const htInput = row.querySelector("input[name*='MontantHT'], input[id*='MontantHT']") || row.querySelectorAll("input")[0];
                            if (htInput) {
                                htInput.value = data.montant_ht;
                                if (window.jQuery) {
                                    window.jQuery(htInput).val(data.montant_ht).trigger('input').trigger('change').trigger('keyup');
                                }
                                htInput.dispatchEvent(new Event('input', { bubbles: true }));
                                htInput.dispatchEvent(new Event('change', { bubbles: true }));
                            }

                            // 3. Set Taxe input
                            if (data.taxe) {
                                const taxeInput = row.querySelector("input[name*='Taxe'], input[id*='Taxe']") || row.querySelectorAll("input")[1];
                                if (taxeInput) {
                                    taxeInput.value = data.taxe;
                                    if (window.jQuery) {
                                        window.jQuery(taxeInput).val(data.taxe).trigger('input').trigger('change').trigger('keyup');
                                    }
                                    taxeInput.dispatchEvent(new Event('input', { bubbles: true }));
                                    taxeInput.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            }

                            return {
                                success: true,
                                rub_val: selectEl ? selectEl.value : null,
                                ht_val: htInput ? htInput.value : null
                            };
                        }""", {
                            "rub_id": rub_id,
                            "montant_ht": montant_ht,
                            "taxe": taxe
                        })
                        
                        print(f"        -> Verified in DOM: Rubrique={filled_info.get('rub_val')}, HT={filled_info.get('ht_val')}")
                        await page.wait_for_timeout(600)

                        # Step 3: CLICK THE 7th COLUMN (GREEN CHECKMARK ✓) ON THE ACTIVE EDITING ROW
                        print(f"        -> Clicking 7th column (green checkmark ✓)...")
                        
                        # Click the 7th column of the active row (index 6)
                        await page.evaluate("""() => {
                            const row = document.querySelector("table tbody tr:has(select), table tbody tr:has(input), table tbody tr.editing, table tbody tr:first-child");
                            if (row) {
                                const tds = row.querySelectorAll("td");
                                if (tds.length >= 7) {
                                    const col7 = tds[6]; // 7th column (green checkmark)
                                    const target = col7.querySelector("a, button, i, span") || col7;
                                    target.click();
                                    return true;
                                }
                            }
                            return false;
                        }""")

                        # Fallback locator click on 7th column of the editing row
                        col7_locator = page.locator("table tbody tr:has(input) td:nth-child(7) a, table tbody tr:first-child td:nth-child(7) a, table tbody tr.editing td:nth-child(7) a, table tbody tr:first-child td:nth-child(7)").first
                        if await col7_locator.count() > 0:
                            try:
                                await col7_locator.click(timeout=1500, force=True)
                            except Exception:
                                pass

                        # Step 4: WAIT FOR THE ROW TO LOCK IN AND AJAX TABLE RELOAD TO COMPLETE
                        try:
                            # Wait until the input elements disappear (row converted to static text)
                            await page.wait_for_function(
                                "() => !document.querySelector('table tbody tr select, table tbody tr input[name*=\"MontantHT\"]')",
                                timeout=6000
                            )
                        except Exception:
                            # If timeout, wait fixed 2.5s
                            await page.wait_for_timeout(2500)

                        await page.wait_for_timeout(800)
                        print(f"    [✓] Rubrique [{rub_id}] successfully committed to table.")
                        
                    print(f"    [✓] Finished adding all {len(rubriques)} rubriques successfully.")

                    # Re-trigger calculations so all dependent fields update with the rubriques
                    print(f"[*] Updating automatic calculation fields (Montant Arrêté, Base Indemnité, etc.)...")
                    await trigger_mcma_calculations(page)

                except Exception as rub_err:
                    print(f"    [!] Rubriques note: {rub_err}")





            # --- POST-FILL AUDIT CHECKLIST ---
            try:
                dom_state = await page.evaluate("""() => {
                    return {
                        montantReparation: document.querySelector('#MontantReparation')?.value || '',
                        montantTVA: document.querySelector('#MontantTVA')?.value || '',
                        montantArrete: document.querySelector('#MontantArrete')?.value || '',
                        baseIndemnite: document.querySelector('#BaseIndemnite')?.value || '',
                        montantDommage: document.querySelector('#MontantDommage')?.value || '',
                        valeurVenale: document.querySelector('#ValeurVenale')?.value || document.querySelector('#ValeurVenaleEstime')?.value || '',
                        montantEpave: document.querySelector('#MontantEpave')?.value || '',
                        dateDevis: document.querySelector('#DateDevis')?.value || '',
                        refDossier: document.querySelector('#ReferenceDossier')?.value || '',
                        vehRepare: document.querySelector('#VehRepareI')?.checked || false,
                        tvaRecup: document.querySelector('#TvaRecupI')?.checked || false
                    };
                }""")

                print("\n" + "="*68)
                print("  📊 POST-FILL VERIFICATION AUDIT (LIVE DOM vs. EXPECTED)")
                print("="*68)
                checks = [
                    ("Reference Dossier", dom_state.get("refDossier"), data.get("text_fields", {}).get("ReferenceDossier")),
                    ("Montant Réparation (HT)", dom_state.get("montantReparation"), data.get("text_fields", {}).get("MontantReparation")),
                    ("Montant TVA", dom_state.get("montantTVA"), data.get("text_fields", {}).get("MontantTVA")),
                    ("Montant Arrêté", dom_state.get("montantArrete"), data.get("text_fields", {}).get("MontantReparation")),
                    ("Base d'Indemnité", dom_state.get("baseIndemnite"), data.get("text_fields", {}).get("MontantReparation")),
                    ("Valeur Vénale", dom_state.get("valeurVenale"), data.get("text_fields", {}).get("ValeurVenale") or data.get("text_fields", {}).get("ValeurVenaleEstime")),
                    ("Montant Epave", dom_state.get("montantEpave"), data.get("text_fields", {}).get("MontantEpave")),
                    ("Date Devis", dom_state.get("dateDevis"), data.get("text_fields", {}).get("DateDevis")),
                    ("Véhicule Réparable [✓]", str(dom_state.get("vehRepare")), str(data.get("checkboxes", {}).get("VehRepareI", True))),
                    ("TVA Récupérable [✓]", str(dom_state.get("tvaRecup")), str(data.get("checkboxes", {}).get("TvaRecupI", True))),
                ]

                for label, actual, expected in checks:
                    act_clean = str(actual or "").strip()
                    exp_clean = str(expected or "").strip()
                    match = act_clean and (act_clean == exp_clean or act_clean.replace(" ", "") == exp_clean.replace(" ", ""))
                    icon = "  [✓] MATCH " if match else "  [i] INFO  "
                    print(f"{icon} | {label:24} | DOM: {act_clean:15} | Expected: {exp_clean}")
                
                print(f"  [✓] MATCH  | {'Rubriques Count':24} | DOM: {len(rubriques)} items           | Expected: {len(rubriques)}")
                print("="*68 + "\n")
            except Exception as audit_err:
                print(f"    [!] Audit note: {audit_err}")

            # --- STEP 8: SAVE FORM (INTENTIONALLY DISABLED FOR MANUAL REVIEW) ---
            print(f"    ⏸️  [REVIEW MODE] Form saving is DISABLED — #Enregistrer left UNCLICKED for manual verification.")

            # --- STEP 9: GED DOCUMENT UPLOAD (DISABLED FOR BOTH MODES) ---
            doc_count = len(data.get("documents", []))
            print(f"    ⏸️  [REVIEW MODE] GED Upload is DISABLED for both modes ({doc_count} document(s) skipped).")

            # --- STEP 10: HUMAN-IN-THE-LOOP REVIEW PAUSE ---
            print("\n" + "="*75)
            print("  ⏸️  AUTOMATION COMPLETE — BROWSER PAUSED FOR YOUR INSPECTION")
            print("  👀  All fields, dropdowns, and rubriques have been populated on screen.")
            print("  🛡️  Zero submissions were made (#DEVISDET_Btn and #Enregistrer are untouched).")
            print("  👉  Please review everything in the browser.")
            print("  👉  When finished, press 'Resume' in Playwright inspector or close the browser.")
            print("="*75 + "\n")

            await page.pause()

            await browser.close()
            return {"status": "success", "message": "Dossier filled and paused for human inspection (no submissions made)."}

        except Exception as e:
            await browser.close()
            return {"status": "failed", "error": str(e)}


        except Exception as e:
            await browser.close()
            return {"status": "failed", "error": str(e)}

@app.post("/api/v1/fill-dossier")
async def handle_dossier(payload: DossierPayload):
    result = await process_workflow(payload.model_dump())
    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result

@app.post("/api/v1/fill-dossier-from-wexia")
async def handle_wexia_dossier(request: Request):
    """
    Accepts a full Wexia dossier JSON (format: wexia.dossier.full, schema_version 2.0),
    maps it to an MCMA-ready payload, downloads any document files from their signed
    URLs, then drives the browser automation exactly like /api/v1/fill-dossier.
    """
    try:
        wexia_json = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    # 1. Translate Wexia JSON -> flat MCMA payload
    mapper  = WexiaToDossierMapper(download_dir="temp")
    payload = mapper.map(wexia_json)

    print(f"[Wexia] Mapped dossier reference : {payload['dossier_reference']}")
    print(f"[Wexia] Mapped matricule         : {payload['matricule']}")
    print(f"[Wexia] Text fields              : {list(payload['text_fields'].keys())}")
    print(f"[Wexia] Select fields            : {list(payload['select_fields'].keys())}")
    print(f"[Wexia] Checkboxes               : {payload['checkboxes']}")
    print(f"[Wexia] Rubriques count          : {len(payload['rubriques'])}")
    print(f"[Wexia] Documents to download    : {len(payload['documents'])}")

    # 2. Download documents from signed URLs -> local temp files
    if payload["documents"]:
        payload["documents"] = await mapper.download_documents(payload["documents"])
        print(f"[Wexia] Documents downloaded     : {len(payload['documents'])}")

    # 3. Run the standard browser automation workflow
    result = await process_workflow(payload)
    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000)