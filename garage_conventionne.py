"""
garage_conventionne.py — Garage Conventionné (PEC) Workflow Controller
======================================================================
Self-contained module for handling the "Garage Conventionné" (Prise en Charge)
mission mode in MCMA. Called from main.py when mode_reparation == "conventionne".

Key differences from Normal Mode:
  - Does NOT click "Ajouter +" to create new rubrique rows.
  - Instead, edits PRE-EXISTING rows in Table 2 (#DevisDetTableVal) in-place.
  - Each row is: pencil icon → fill fields → green checkmark → AJAX save.
  - After all rows, triggers DevisCalculerMontantCharge() for financial split.
  - Optionally clicks #DEVISDET_Btn ("Valider Devis") in production mode.

Logging:
  Every action is logged to logs/gc_<timestamp>.json for easy debugging.
  When something fails, share this log file for fast diagnosis.
"""

import os
import json
import time
from datetime import datetime


# =============================================================================
# Structured Logger
# =============================================================================
class GCLogger:
    """Structured JSON logger for the Garage Conventionné workflow."""

    def __init__(self, log_dir="logs"):
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"gc_{ts}.json")
        self.entries = []
        self.start_time = time.time()
        self._write()  # Create the file immediately

    def log(self, step: str, status: str, detail: str, extra: dict = None):
        """Add a log entry."""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "elapsed_s": round(time.time() - self.start_time, 2),
            "step": step,
            "status": status,
            "detail": detail,
        }
        if extra:
            entry["extra"] = extra
        self.entries.append(entry)
        self._write()
        # Also print to console with icons
        icon = {"OK": "✓", "ERROR": "✗", "WARN": "⚠", "INFO": "ℹ"}.get(status, "·")
        print(f"    [{icon}] [{step}] {detail}")

    def _write(self):
        """Persist log to disk after every entry."""
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)

    def summary(self) -> dict:
        """Return a summary of the log."""
        ok = sum(1 for e in self.entries if e["status"] == "OK")
        err = sum(1 for e in self.entries if e["status"] == "ERROR")
        warn = sum(1 for e in self.entries if e["status"] == "WARN")
        return {
            "log_file": self.log_path,
            "total_steps": len(self.entries),
            "ok": ok,
            "errors": err,
            "warnings": warn,
        }


# =============================================================================
# Helper: Take a DOM snapshot of key fields
# =============================================================================
async def _snapshot_dom_fields(page, logger: GCLogger):
    """Capture the current DOM state of key Garage Conventionné fields."""
    try:
        state = await page.evaluate("""() => {
            const get = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                return el.value !== undefined ? el.value : el.textContent?.trim();
            };
            return {
                DevisMontantTTC: get('#DevisMontantTTC'),
                DevisMontantTVA: get('#DevisMontantTVA'),
                DevisMontantVetusteTotal: get('#DevisMontantVetusteTotal'),
                DevisMontantFranchise: get('#DevisMontantFranchise'),
                DevisMontantRemise: get('#DevisMontantRemise'),
                DevisMontantChargeSocietaire: get('#DevisMontantChargeSocietaire'),
                DevisMontantChargeMutuelle: get('#DevisMontantChargeMutuelle'),
                DevisPartResponsabilite: get('#DevisPartResponsabilite'),
                MontantReparation: get('#MontantReparation'),
                MontantArrete: get('#MontantArrete'),
                BaseIndemnite: get('#BaseIndemnite'),
            };
        }""")
        logger.log("DOM_SNAPSHOT", "INFO", f"Field snapshot captured", extra=state)
        return state
    except Exception as e:
        logger.log("DOM_SNAPSHOT", "ERROR", f"Failed to capture DOM snapshot: {e}")
        return {}


# =============================================================================
# Helper: Save a screenshot
# =============================================================================
async def _save_screenshot(page, logger: GCLogger, label: str):
    """Save a screenshot for debugging."""
    try:
        os.makedirs("logs/screenshots", exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = f"logs/screenshots/gc_{label}_{ts}.png"
        await page.screenshot(path=path, full_page=False)
        logger.log("SCREENSHOT", "INFO", f"Saved screenshot: {path}")
    except Exception as e:
        logger.log("SCREENSHOT", "WARN", f"Could not save screenshot: {e}")


# =============================================================================
# Step 1: Detect Table 2 and enumerate existing rows
# =============================================================================
async def _detect_table2(page, logger: GCLogger) -> list:
    """
    Detect #DevisDetTableVal and return a list of existing row info.
    Each row: {index, row_text, rubrique_label}
    """
    # First check if the conventionne section is visible
    section_visible = await page.evaluate("""() => {
        const sec = document.querySelector('#sectionGarageConventionne, #blocDevisValide');
        return sec ? (sec.offsetParent !== null || getComputedStyle(sec).display !== 'none') : false;
    }""")

    if not section_visible:
        # Try to check if #DevisDetTableVal exists even if section wrapper doesn't
        table_exists = await page.locator("#DevisDetTableVal").count()
        if table_exists == 0:
            logger.log("DETECT_TABLE2", "ERROR",
                        "Neither #sectionGarageConventionne nor #DevisDetTableVal found on page. "
                        "This mission may not be in Garage Conventionné mode on the MCMA side.")
            return []
        else:
            logger.log("DETECT_TABLE2", "WARN",
                        "Section wrapper not visible but #DevisDetTableVal exists. Proceeding.")

    # Enumerate rows in Table 2
    rows_info = await page.evaluate("""() => {
        const rows = document.querySelectorAll('#DevisDetTableVal tbody tr');
        const result = [];
        rows.forEach((tr, idx) => {
            const tds = tr.querySelectorAll('td');
            if (tds.length >= 6) {
                result.push({
                    index: idx,
                    row_id: tr.id || '',
                    rubrique_label: tds[0]?.textContent?.trim() || '',
                    current_ht: tds[1]?.textContent?.trim() || '',
                    current_taxe: tds[2]?.textContent?.trim() || '',
                    current_ttc: tds[3]?.textContent?.trim() || '',
                    has_edit_btn: !!tr.querySelector('a.edit-row, a#Modifier, a[onclick*="editRow"]'),
                });
            }
        });
        return result;
    }""")

    if not rows_info:
        logger.log("DETECT_TABLE2", "WARN",
                    "Table 2 (#DevisDetTableVal) found but has 0 data rows. "
                    "The garage devis may not have been loaded yet.")
    else:
        logger.log("DETECT_TABLE2", "OK",
                    f"Found {len(rows_info)} row(s) in Table 2 (#DevisDetTableVal)")
        for r in rows_info:
            logger.log("DETECT_TABLE2_ROW", "INFO",
                        f"  Row {r['index']}: [{r['rubrique_label']}] "
                        f"HT={r['current_ht']} Taxe={r['current_taxe']} TTC={r['current_ttc']} "
                        f"edit_btn={r['has_edit_btn']}")

    return rows_info


# =============================================================================
# Step 2: Match rubriques from mapper output to Table 2 rows
# =============================================================================
def _match_rubriques_to_rows(rubriques: list, table_rows: list, logger: GCLogger) -> list:
    """
    Match each rubrique from the mapper to a row in Table 2.
    Returns a list of matched pairs: [{rubrique, row, match_type}]
    and logs unmatched items.
    """
    matches = []
    unmatched_rubriques = []
    used_rows = set()

    for rub in rubriques:
        rub_id = str(rub.get("IdRubrique", ""))
        rub_label = str(rub.get("_label", "")).strip().upper()
        matched = False

        for row in table_rows:
            if row["index"] in used_rows:
                continue
            row_label = row["rubrique_label"].upper()

            # Match by label similarity (contains check)
            # Normalize: remove extra spaces, common variations
            rub_words = set(rub_label.split())
            row_words = set(row_label.split())
            common_words = rub_words & row_words

            # If >50% of words match, or label contains the rubrique label
            label_match = (
                rub_label in row_label or
                row_label in rub_label or
                (len(common_words) >= len(rub_words) * 0.5 and len(common_words) >= 2)
            )

            if label_match:
                matches.append({
                    "rubrique": rub,
                    "row": row,
                    "match_type": "label",
                })
                used_rows.add(row["index"])
                matched = True
                logger.log("MATCH_RUBRIQUE", "OK",
                            f"Rubrique [{rub_id}] '{rub.get('_label', '')}' → Row {row['index']} '{row['rubrique_label']}'")
                break

        if not matched:
            unmatched_rubriques.append(rub)
            logger.log("MATCH_RUBRIQUE", "WARN",
                        f"Rubrique [{rub_id}] '{rub.get('_label', '')}' has NO matching row in Table 2")

    # Log unmatched table rows
    for row in table_rows:
        if row["index"] not in used_rows:
            logger.log("MATCH_RUBRIQUE", "INFO",
                        f"Table 2 Row {row['index']} '{row['rubrique_label']}' has no matching rubrique (will be left as-is)")

    return matches


# =============================================================================
# Step 3: Edit a single row in Table 2 (pencil → fill → checkmark)
# =============================================================================
async def _edit_row(page, row_info: dict, rubrique: dict, logger: GCLogger) -> bool:
    """
    Edit a single row in Table 2:
    1. Click the pencil icon (edit-row) in column 7
    2. Fill MontantHTValide, TaxeValide, vétusté fields
    3. Trigger keyup events for auto-calculations
    4. Click the green checkmark to save
    5. Wait for AJAX response
    Returns True on success, False on failure.
    """
    row_idx = row_info["index"]
    rub_id = rubrique.get("IdRubrique", "?")
    rub_label = rubrique.get("_label", "")
    montant_ht = str(rubrique.get("MontantHT", "0"))
    taxe = str(rubrique.get("Taxe", "0"))

    logger.log(f"EDIT_ROW_{row_idx}", "INFO",
                f"Starting edit: Rubrique [{rub_id}] '{rub_label}' → HT={montant_ht}, TVA={taxe}")

    # --- Step 3a: Click the pencil icon ---
    try:
        # Try multiple selectors for the edit button
        pencil_clicked = await page.evaluate("""(rowIdx) => {
            const rows = document.querySelectorAll('#DevisDetTableVal tbody tr');
            if (rowIdx >= rows.length) return {ok: false, error: 'Row index out of bounds'};
            const row = rows[rowIdx];
            
            // Look for edit button in column 7 (index 6)
            const tds = row.querySelectorAll('td');
            let editBtn = null;
            
            // Try column 7 first (standard position)
            if (tds.length >= 7) {
                editBtn = tds[6].querySelector('a.edit-row, a#Modifier, a[onclick*="editRow"], a[title*="Modifier"]');
            }
            // Fallback: search entire row
            if (!editBtn) {
                editBtn = row.querySelector('a.edit-row, a#Modifier, a[onclick*="editRow"], a[title*="Modifier"]');
            }
            // Fallback: any pencil icon
            if (!editBtn) {
                const pencil = row.querySelector('i.fa-pencil, i.fa-edit, i.glyphicon-pencil');
                if (pencil) editBtn = pencil.closest('a') || pencil;
            }
            
            if (editBtn) {
                editBtn.click();
                return {ok: true, clicked: editBtn.outerHTML.substring(0, 120)};
            }
            return {ok: false, error: 'No edit button found in row', rowHTML: row.innerHTML.substring(0, 300)};
        }""", row_idx)

        if not pencil_clicked.get("ok"):
            logger.log(f"EDIT_ROW_{row_idx}", "ERROR",
                        f"Could not click pencil icon: {pencil_clicked.get('error')}",
                        extra={"rowHTML": pencil_clicked.get("rowHTML", "")})
            return False

        logger.log(f"EDIT_ROW_{row_idx}", "OK",
                    f"Pencil icon clicked: {pencil_clicked.get('clicked', '')[:80]}")

    except Exception as e:
        logger.log(f"EDIT_ROW_{row_idx}", "ERROR", f"Exception clicking pencil: {e}")
        return False

    # Wait for row to enter editing mode
    await page.wait_for_timeout(800)

    # --- Step 3b: Fill the editable fields ---
    try:
        fill_result = await page.evaluate("""(args) => {
            const {montantHT, taxe} = args;
            const results = {};
            
            // Helper to set value and fire events
            function setField(selector, value) {
                const el = document.querySelector(selector);
                if (!el) return {found: false, selector: selector};
                el.value = value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '0' }));
                // jQuery triggers
                if (window.jQuery) {
                    try { window.jQuery(el).trigger('keyup').trigger('change').trigger('input'); } catch(e) {}
                }
                // Inline handlers
                if (typeof el.onkeyup === 'function') { try { el.onkeyup(); } catch(e) {} }
                if (typeof el.onchange === 'function') { try { el.onchange(); } catch(e) {} }
                return {found: true, selector: selector, setValue: value, readBack: el.value};
            }
            
            // Fill MontantHTValide
            results.ht = setField('#MontantHTValide', montantHT);
            
            // Fill TaxeValide
            results.taxe = setField('#TaxeValide', taxe);
            
            // Read back MontantTTCValide (should auto-calculate)
            const ttcEl = document.querySelector('#MontantTTCValide');
            results.ttc_auto = ttcEl ? ttcEl.value : 'NOT_FOUND';
            
            // Check for editing row class
            const editingRow = document.querySelector('#DevisDetTableVal tbody tr.editing, #DevisDetTableVal tbody tr.tr-editing');
            results.has_editing_row = !!editingRow;
            
            return results;
        }""", {"montantHT": montant_ht, "taxe": taxe})

        # Log fill results
        ht_ok = fill_result.get("ht", {}).get("found", False)
        taxe_ok = fill_result.get("taxe", {}).get("found", False)

        if ht_ok:
            logger.log(f"FILL_HT_ROW_{row_idx}", "OK",
                        f"MontantHTValide = {montant_ht} (readBack: {fill_result['ht'].get('readBack', '?')})")
        else:
            logger.log(f"FILL_HT_ROW_{row_idx}", "ERROR",
                        f"#MontantHTValide not found in editing row!",
                        extra=fill_result)

        if taxe_ok:
            logger.log(f"FILL_TAXE_ROW_{row_idx}", "OK",
                        f"TaxeValide = {taxe} (readBack: {fill_result['taxe'].get('readBack', '?')})")
        else:
            logger.log(f"FILL_TAXE_ROW_{row_idx}", "ERROR",
                        f"#TaxeValide not found in editing row!",
                        extra=fill_result)

        logger.log(f"FILL_TTC_ROW_{row_idx}", "INFO",
                    f"MontantTTCValide auto-calculated = {fill_result.get('ttc_auto', '?')}")

        if not fill_result.get("has_editing_row"):
            logger.log(f"EDIT_ROW_{row_idx}", "WARN",
                        "No <tr> with class 'editing' or 'tr-editing' detected. Row may not be in edit mode.")

    except Exception as e:
        logger.log(f"FILL_ROW_{row_idx}", "ERROR", f"Exception filling fields: {e}")
        return False

    # Small delay for calculations to cascade
    await page.wait_for_timeout(500)

    # --- Step 3c: Click the green checkmark to save ---
    try:
        save_result = await page.evaluate("""(rowIdx) => {
            const rows = document.querySelectorAll('#DevisDetTableVal tbody tr');
            if (rowIdx >= rows.length) return {ok: false, error: 'Row gone after editing'};
            const row = rows[rowIdx];
            
            // Look for save/checkmark button
            let saveBtn = null;
            const tds = row.querySelectorAll('td');
            
            // Try column 7 (standard)
            if (tds.length >= 7) {
                saveBtn = tds[6].querySelector('a.save-row, a:has(.fa-check), a[onclick*="saveRow"], a[title*="Enregistrer"]');
            }
            // Fallback: search entire row
            if (!saveBtn) {
                saveBtn = row.querySelector('a.save-row, a:has(.fa-check), a[onclick*="saveRow"], a[title*="Enregistrer"]');
            }
            // Fallback: any green check icon
            if (!saveBtn) {
                const check = row.querySelector('i.fa-check');
                if (check) saveBtn = check.closest('a') || check;
            }
            
            if (saveBtn) {
                saveBtn.click();
                return {ok: true, clicked: saveBtn.outerHTML.substring(0, 120)};
            }
            return {ok: false, error: 'No save/checkmark button found', rowHTML: row.innerHTML.substring(0, 300)};
        }""", row_idx)

        if save_result.get("ok"):
            logger.log(f"SAVE_ROW_{row_idx}", "OK",
                        f"Green checkmark clicked: {save_result.get('clicked', '')[:80]}")
        else:
            logger.log(f"SAVE_ROW_{row_idx}", "ERROR",
                        f"Could not click checkmark: {save_result.get('error')}",
                        extra={"rowHTML": save_result.get("rowHTML", "")})
            return False

    except Exception as e:
        logger.log(f"SAVE_ROW_{row_idx}", "ERROR", f"Exception clicking checkmark: {e}")
        return False

    # Wait for AJAX save + table redraw
    await page.wait_for_timeout(2000)

    logger.log(f"EDIT_ROW_{row_idx}", "OK",
                f"Row {row_idx} edit complete: [{rub_id}] {rub_label} → HT={montant_ht}, TVA={taxe}")
    return True


# =============================================================================
# Step 4: Trigger financial split calculation
# =============================================================================
async def _trigger_devis_calculations(page, logger: GCLogger):
    """Trigger DevisCalculerMontantCharge() and related calculations."""
    try:
        calc_result = await page.evaluate("""() => {
            const results = {};
            
            // Try calling native calculation functions
            if (typeof DevisCalculerMontantCharge === 'function') {
                try { DevisCalculerMontantCharge(); results.devisCalc = 'called'; } 
                catch(e) { results.devisCalc = 'error: ' + e.message; }
            } else {
                results.devisCalc = 'function_not_found';
            }
            
            if (typeof CalculerMntArrete === 'function') {
                try { CalculerMntArrete(); results.arrete = 'called'; } 
                catch(e) { results.arrete = 'error: ' + e.message; }
            }
            
            if (typeof CalculerMontantDommage === 'function') {
                try { CalculerMontantDommage(); results.dommage = 'called'; } 
                catch(e) { results.dommage = 'error: ' + e.message; }
            }
            
            // Fire events on key fields to cascade
            const selectors = [
                '#DevisMontantTTC', '#DevisMontantTVA', '#DevisMontantVetusteTotal',
                '#DevisMontantFranchise', '#DevisMontantRemise',
                '#DevisPartResponsabilite', '#DevisTvaRecupI',
                '#MontantReparation', '#MontantArrete', '#BaseIndemnite',
                '#PartResponsabilite'
            ];
            selectors.forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                    if (typeof el.onkeyup === 'function') { try { el.onkeyup(); } catch(e) {} }
                    if (typeof el.onchange === 'function') { try { el.onchange(); } catch(e) {} }
                    if (window.jQuery) {
                        try { window.jQuery(el).trigger('keyup').trigger('change'); } catch(e) {}
                    }
                }
            });
            
            // Read results
            const get = (sel) => document.querySelector(sel)?.value || null;
            results.DevisMontantChargeMutuelle = get('#DevisMontantChargeMutuelle');
            results.DevisMontantChargeSocietaire = get('#DevisMontantChargeSocietaire');
            results.DevisMontantTTC = get('#DevisMontantTTC');
            results.MontantArrete = get('#MontantArrete');
            results.BaseIndemnite = get('#BaseIndemnite');
            
            return results;
        }""")

        devis_calc_status = calc_result.get("devisCalc", "?")
        logger.log("DEVIS_CALC", "OK" if devis_calc_status == "called" else "WARN",
                    f"DevisCalculerMontantCharge: {devis_calc_status}",
                    extra=calc_result)

    except Exception as e:
        logger.log("DEVIS_CALC", "ERROR", f"Exception triggering calculations: {e}")


# =============================================================================
# Step 5: Force charge mutuelle (same logic as Normal mode fix)
# =============================================================================
async def _force_charge_mutuelle(page, logger: GCLogger):
    """Force the total into Charge Mutuelle and set Sociétaire to 0."""
    try:
        result = await page.evaluate("""() => {
            const repVal = document.querySelector('#MontantReparation')?.value || '0';
            
            // Normal mode fields
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
            
            // Devis (Garage Conventionne) fields
            const devisMut = document.querySelector('#DevisMontantChargeMutuelle');
            const devisSoc = document.querySelector('#DevisMontantChargeSocietaire');
            if (devisMut) {
                const devisRepVal = document.querySelector('#DevisMontantTTC')?.value || repVal;
                devisMut.value = devisRepVal;
                devisMut.dispatchEvent(new Event('input', { bubbles: true }));
                devisMut.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (devisSoc) {
                devisSoc.value = '0';
                devisSoc.dispatchEvent(new Event('input', { bubbles: true }));
                devisSoc.dispatchEvent(new Event('change', { bubbles: true }));
            }
            
            return {
                mutuelle: mutuelle?.value || devisMut?.value || '?',
                societaire: societaire?.value || devisSoc?.value || '?',
            };
        }""")

        logger.log("FORCE_CHARGE_MUTUELLE", "OK",
                    f"Charge Mutuelle = {result.get('mutuelle', '?')}, "
                    f"Charge Sociétaire = {result.get('societaire', '?')}")

    except Exception as e:
        logger.log("FORCE_CHARGE_MUTUELLE", "ERROR", f"Exception: {e}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
async def fill_garage_conventionne(page, data: dict, test_mode: bool = True) -> dict:
    """
    Main entry point for the Garage Conventionné (PEC) workflow.
    
    Args:
        page: Playwright page object (already navigated to the mission form)
        data: Mapped dossier payload with rubriques, text_fields, etc.
        test_mode: If True, will NOT click Valider Devis (#DEVISDET_Btn)
    
    Returns:
        dict with status, message, and log summary
    """
    logger = GCLogger()
    rubriques = data.get("rubriques", [])

    print(f"\n{'='*70}")
    print(f"  🏗️  GARAGE CONVENTIONNÉ (PEC) MODE")
    print(f"  📝  {len(rubriques)} rubrique(s) to process")
    print(f"  📋  Log file: {logger.log_path}")
    print(f"{'='*70}\n")

    logger.log("START", "INFO",
                f"Starting Garage Conventionné workflow with {len(rubriques)} rubriques")

    # --- Screenshot: before we start ---
    await _save_screenshot(page, logger, "01_before_gc")

    # --- Step 1: Detect Table 2 ---
    print(f"[*] Step 1: Detecting Table 2 (#DevisDetTableVal)...")
    table_rows = await _detect_table2(page, logger)

    if not table_rows:
        logger.log("ABORT", "ERROR",
                    "No rows in Table 2. Cannot proceed with Garage Conventionné workflow. "
                    "Possible causes: (1) Mission is actually Normal mode, (2) Garage devis not loaded, "
                    "(3) Page DOM structure is different from expected.")
        await _save_screenshot(page, logger, "02_no_table2_rows")
        await _snapshot_dom_fields(page, logger)
        summary = logger.summary()
        return {"status": "failed", "message": "No rows in Table 2", **summary}

    # --- Step 2: Match rubriques to rows ---
    print(f"[*] Step 2: Matching {len(rubriques)} rubriques to {len(table_rows)} Table 2 rows...")
    matches = _match_rubriques_to_rows(rubriques, table_rows, logger)

    if not matches:
        logger.log("ABORT", "ERROR",
                    "No rubriques could be matched to Table 2 rows. "
                    "Check if the rubrique labels in the mapper output match the labels in the MCMA table.",
                    extra={
                        "rubrique_labels": [r.get("_label") for r in rubriques],
                        "table_row_labels": [r["rubrique_label"] for r in table_rows],
                    })
        await _save_screenshot(page, logger, "03_no_matches")
        summary = logger.summary()
        return {"status": "failed", "message": "No rubrique-to-row matches found", **summary}

    logger.log("MATCH_SUMMARY", "OK",
                f"Matched {len(matches)}/{len(rubriques)} rubriques to Table 2 rows")

    # --- Step 3: Edit each matched row ---
    print(f"[*] Step 3: Editing {len(matches)} row(s) in Table 2...")
    success_count = 0
    fail_count = 0

    for i, match in enumerate(matches, 1):
        rub = match["rubrique"]
        row = match["row"]
        print(f"    [{i}/{len(matches)}] Editing Row {row['index']}: "
              f"[{rub.get('IdRubrique')}] {rub.get('_label', '')} "
              f"(HT: {rub.get('MontantHT', 0)}, TVA: {rub.get('Taxe', 0)})...")

        ok = await _edit_row(page, row, rub, logger)
        if ok:
            success_count += 1
        else:
            fail_count += 1
            await _save_screenshot(page, logger, f"04_row{row['index']}_failed")

    logger.log("EDIT_SUMMARY", "OK" if fail_count == 0 else "WARN",
                f"Edited {success_count}/{len(matches)} rows successfully. Failures: {fail_count}")

    # --- Screenshot: after all row edits ---
    await _save_screenshot(page, logger, "05_after_row_edits")

    # --- Step 4: Trigger financial calculations ---
    print(f"[*] Step 4: Triggering DevisCalculerMontantCharge()...")
    await _trigger_devis_calculations(page, logger)

    # --- Step 5: Force charge mutuelle ---
    print(f"[*] Step 5: Setting Montant à charge mutuelle...")
    await _force_charge_mutuelle(page, logger)

    # --- Final DOM snapshot ---
    print(f"[*] Capturing final DOM snapshot...")
    final_state = await _snapshot_dom_fields(page, logger)

    # --- Screenshot: final state ---
    await _save_screenshot(page, logger, "06_final_state")

    # --- Step 6: Valider Devis (only in production mode) ---
    if not test_mode:
        print(f"[*] Step 6: Clicking 'Valider Devis' (#DEVISDET_Btn)...")
        try:
            btn = page.locator("#DEVISDET_Btn").first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(3000)
                logger.log("VALIDER_DEVIS", "OK", "Clicked #DEVISDET_Btn (Valider Devis)")
                await _save_screenshot(page, logger, "07_after_valider")
            else:
                logger.log("VALIDER_DEVIS", "WARN",
                            "#DEVISDET_Btn not found or not visible. May have been already validated.")
        except Exception as e:
            logger.log("VALIDER_DEVIS", "ERROR", f"Exception clicking Valider Devis: {e}")
    else:
        logger.log("VALIDER_DEVIS", "INFO",
                    "TEST MODE — Skipped clicking Valider Devis (#DEVISDET_Btn)")
        print(f"    ⏸️  [TEST MODE] Skipped Valider Devis button (safety mode)")

    # --- Summary ---
    summary = logger.summary()
    logger.log("DONE", "OK",
                f"Garage Conventionné workflow complete. "
                f"{summary['ok']} OK / {summary['errors']} errors / {summary['warnings']} warnings")

    print(f"\n{'='*70}")
    print(f"  📊 GARAGE CONVENTIONNÉ SUMMARY")
    print(f"  ✓ Steps OK    : {summary['ok']}")
    print(f"  ✗ Errors      : {summary['errors']}")
    print(f"  ⚠ Warnings    : {summary['warnings']}")
    print(f"  📋 Full log   : {summary['log_file']}")
    if final_state:
        print(f"  💰 Charge Mut.: {final_state.get('DevisMontantChargeMutuelle', '?')}")
        print(f"  💰 Charge Soc.: {final_state.get('DevisMontantChargeSocietaire', '?')}")
    print(f"{'='*70}\n")

    status = "success" if summary["errors"] == 0 else "partial" if success_count > 0 else "failed"
    return {"status": status, "message": f"GC workflow done: {success_count}/{len(matches)} rows edited", **summary}
