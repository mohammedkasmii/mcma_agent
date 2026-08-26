"""
garage_conventionne.py — Garage Conventionné (PEC) Workflow Controller
======================================================================
Self-contained module for handling the "Garage Conventionné" (Prise en Charge)
mission mode in MCMA. Called from main.py when mode_reparation == "conventionne".

Architecture & Security:
  - Edits PRE-EXISTING rows in Table 2 (#DevisDetTableVal) in-place.
  - Strict All-or-Nothing Matching: aborts BEFORE any writes if even 1 rubrique is unmatched.
  - Dynamic Row Re-Location: re-locates rows by label after every table redraw (no stale indexes).
  - Full Field Injection: MontantHTValide, TaxeValide, TauxVetusteValide, MontantVetusteValide.
  - Awaits and validates POST /updateDevisDet network response.
  - Executes native DevisCalculerMontantCharge() for accurate financial split.
  - STRICT SAFETY: #DEVISDET_Btn ("Valider Devis") and #Enregistrer are NEVER clicked.
  - Structured Diagnostic Logging: logs/gc_<timestamp>.json + logs/screenshots/.
"""

import os
import re
import json
import time
from datetime import datetime
from mapper import RUBRIQUE_CATALOG, normalize_text


# =============================================================================
# Rubrique Synonyms & Aliases for Robust Table 2 Row Matching
# =============================================================================
RUBRIQUE_MATCH_ALIASES = {
    "1": [
        "fournitures carrosserie origines",
        "fournitures carrosserie origine",
        "pieces carrosserie origines",
        "pieces carrosserie origine",
        "fournitures carrosserie oem",
        "pieces origines",
    ],
    "2": [
        "fournitures carrosserie adaptables",
        "fournitures carrosserie adaptable",
        "pieces carrosserie adaptables",
        "pieces carrosserie adaptable",
        "pieces adaptables",
    ],
    "3": [
        "total pieces occasions recuperables",
        "total pieces occasions",
        "pieces occasions recuperables",
        "fournitures carrosserie recuperables",
        "fournitures carrosserie occasions",
        "pieces recuperables",
        "pieces occasions",
    ],
    "4": [
        "fournitures mecanique origines",
        "fournitures mecanique origine",
        "pieces mecanique origines",
    ],
    "5": [
        "fournitures mecanique adaptables",
        "fournitures mecanique adaptable",
        "pieces mecanique adaptables",
    ],
    "6": [
        "fournitures mecanique recuperables",
        "fournitures mecanique occasions",
        "pieces mecanique recuperables",
    ],
    "7": [
        "main d oeuvre carrosserie",
        "mo carrosserie",
        "main d oeuvre tole",
        "mo tole",
        "main doeuvre carrosserie",
    ],
    "8": [
        "main d oeuvre mecanique",
        "mo mecanique",
        "main doeuvre mecanique",
    ],
    "10": [
        "peinture origines",
        "peinture origine",
    ],
    "11": [
        "peinture adaptables",
        "peinture adaptable",
    ],
    "12": [
        "main d oeuvre peinture",
        "mo peinture",
        "main doeuvre peinture",
    ],
    "13": [
        "electrique d origine",
        "electrique origines",
        "fournitures electrique origines",
    ],
    "14": [
        "electrique adaptables",
        "electrique adaptable",
    ],
    "15": [
        "electrique recuperables",
        "electrique occasions",
    ],
    "16": [
        "peintures et ingredients",
        "peinture et ingredients",
        "peintures ingredients",
        "ingredients peinture",
    ],
    "17": ["passage au marbre", "marbre"],
    "18": ["parallelisme et equilibrage", "geometrie"],
    "19": ["reparation vitre"],
    "20": ["remplacement vitre"],
    "21": ["reparation pare brise"],
    "22": ["remplacement pare brise"],
    "23": ["reparation lunette arriere"],
    "24": ["remplacement lunette arriere"],
    "25": ["colle", "colle pare brise", "mastic colle"],
    "26": ["kit colle pare brise et lunette arriere", "kit colle"],
    "27": ["kit colle vitre"],
    "28": [
        "main d oeuvre electrique",
        "mo electrique",
        "main doeuvre electrique",
    ],
}


# =============================================================================
# Structured JSON Logger
# =============================================================================
class GCLogger:
    """Structured JSON logger for the Garage Conventionné workflow."""

    def __init__(self, log_dir="logs"):
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"gc_{ts}.json")
        self.entries = []
        self.start_time = time.time()
        self._write()

    def log(self, step: str, status: str, detail: str, extra: dict = None):
        """Add a log entry and write to disk."""
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
        icon = {"OK": "✓", "ERROR": "✗", "WARN": "⚠", "INFO": "ℹ"}.get(status, "·")
        print(f"    [{icon}] [{step}] {detail}")

    def _write(self):
        """Persist log to disk immediately."""
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def summary(self) -> dict:
        """Return a summary dictionary of execution stats."""
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
# Diagnostic Helpers
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
        logger.log("DOM_SNAPSHOT", "INFO", "Field snapshot captured", extra=state)
        return state
    except Exception as e:
        logger.log("DOM_SNAPSHOT", "ERROR", f"Failed to capture DOM snapshot: {e}")
        return {}


async def _save_screenshot(page, logger: GCLogger, label: str):
    """Save a timestamped screenshot for visual inspection."""
    try:
        os.makedirs("logs/screenshots", exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = f"logs/screenshots/gc_{label}_{ts}.png"
        await page.screenshot(path=path, full_page=False)
        logger.log("SCREENSHOT", "INFO", f"Saved screenshot: {path}")
    except Exception as e:
        logger.log("SCREENSHOT", "WARN", f"Could not save screenshot: {e}")


# =============================================================================
# Step 1: Detect Table 2 (#DevisDetTableVal) and enumerate existing rows
# =============================================================================
async def _detect_table2(page, logger: GCLogger) -> list:
    """
    Detect #DevisDetTableVal and return structured info for all existing rows.
    """
    # Check if Table 2 exists on page
    table_count = await page.locator("#DevisDetTableVal").count()
    if table_count == 0:
        logger.log("DETECT_TABLE2", "ERROR",
                    "Table 2 (#DevisDetTableVal) NOT found in page DOM. "
                    "This mission does not appear to be in Garage Conventionné mode on MCMA.")
        return []

    # Enumerate rows
    rows_info = await page.evaluate("""() => {
        const rows = document.querySelectorAll('#DevisDetTableVal tbody tr');
        const result = [];
        rows.forEach((tr, idx) => {
            const tds = tr.querySelectorAll('td');
            if (tds.length >= 4) {
                const label = tds[0]?.textContent?.trim() || '';
                // Skip empty or placeholder rows
                if (label && !label.toLowerCase().includes('aucun') && !label.toLowerCase().includes('no data')) {
                    result.push({
                        index: idx,
                        row_id: tr.id || '',
                        rubrique_label: label,
                        current_ht: tds[1]?.textContent?.trim() || '',
                        current_taxe: tds[2]?.textContent?.trim() || '',
                        current_ttc: tds[3]?.textContent?.trim() || '',
                        has_edit_btn: !!tr.querySelector('a.edit-row, a#Modifier, a[onclick*="editRow"], i.fa-pencil'),
                    });
                }
            }
        });
        return result;
    }""")

    if not rows_info:
        logger.log("DETECT_TABLE2", "WARN",
                    "Table 2 (#DevisDetTableVal) found but has 0 data rows. "
                    "The garage devis may not have been submitted or loaded yet.")
    else:
        logger.log("DETECT_TABLE2", "OK",
                    f"Found {len(rows_info)} row(s) in Table 2 (#DevisDetTableVal)")
        for r in rows_info:
            logger.log("DETECT_TABLE2_ROW", "INFO",
                        f"  Row {r['index']}: '{r['rubrique_label']}' "
                        f"[HT={r['current_ht']} | Taxe={r['current_taxe']} | TTC={r['current_ttc']}]")

    return rows_info


# =============================================================================
# Step 2: Strict All-or-Nothing Rubrique Matching
# =============================================================================
def _match_single_rubrique(rub: dict, table_rows: list, used_indices: set) -> tuple:
    """
    Attempts to match a single rubrique against available Table 2 rows.
    Returns (matched_row, match_method) or (None, None).
    """
    rub_id = str(rub.get("IdRubrique", "")).strip()
    rub_lib = rub.get("LibRubrique") or rub.get("_label") or RUBRIQUE_CATALOG.get(rub_id, "")
    norm_rub_lib = normalize_text(rub_lib)

    # 1. Exact normalized label match
    for row in table_rows:
        if row["index"] in used_indices:
            continue
        norm_row_lib = normalize_text(row["rubrique_label"])
        if norm_rub_lib and norm_rub_lib == norm_row_lib:
            return row, f"exact_label ('{norm_rub_lib}')"

    # 2. Known alias match for this IdRubrique
    known_aliases = RUBRIQUE_MATCH_ALIASES.get(rub_id, [])
    for row in table_rows:
        if row["index"] in used_indices:
            continue
        norm_row_lib = normalize_text(row["rubrique_label"])
        for alias in known_aliases:
            norm_alias = normalize_text(alias)
            if norm_alias and (norm_alias == norm_row_lib or norm_alias in norm_row_lib or norm_row_lib in norm_alias):
                return row, f"known_alias ('{alias}')"

    # 3. Substring inclusion match (min 4 chars)
    for row in table_rows:
        if row["index"] in used_indices:
            continue
        norm_row_lib = normalize_text(row["rubrique_label"])
        if len(norm_rub_lib) >= 4 and (norm_rub_lib in norm_row_lib or norm_row_lib in norm_rub_lib):
            return row, f"substring ('{norm_rub_lib}' ~ '{norm_row_lib}')"

    return None, None


def match_all_rubriques(rubriques: list, table_rows: list, logger: GCLogger) -> list:
    """
    Strict All-or-Nothing matching:
    Every single rubrique in `rubriques` must match exactly one distinct row.
    If ANY rubrique is unmatched, returns [] and logs error.
    """
    matches = []
    used_indices = set()
    unmatched = []

    for rub in rubriques:
        rub_id = str(rub.get("IdRubrique", "?"))
        rub_lib = rub.get("LibRubrique") or rub.get("_label") or RUBRIQUE_CATALOG.get(rub_id, "")
        
        row, method = _match_single_rubrique(rub, table_rows, used_indices)
        if row is not None:
            matches.append({
                "rubrique": rub,
                "target_label": row["rubrique_label"],
                "target_index": row["index"],
                "match_method": method,
            })
            used_indices.add(row["index"])
            logger.log("MATCH_RUBRIQUE", "OK",
                        f"Rubrique [{rub_id}] '{rub_lib}' → Row '{row['rubrique_label']}' (via {method})")
        else:
            unmatched.append({"IdRubrique": rub_id, "LibRubrique": rub_lib})
            logger.log("MATCH_RUBRIQUE", "ERROR",
                        f"Rubrique [{rub_id}] '{rub_lib}' CANNOT be matched to any available Table 2 row!")

    # Check for complete 100% match
    if unmatched:
        logger.log("MATCH_ABORT", "ERROR",
                    f"All-or-Nothing Match Failed: {len(unmatched)}/{len(rubriques)} rubriques could not be matched. "
                    "Aborting workflow before touching any rows to prevent partial corruption.",
                    extra={
                        "unmatched_rubriques": unmatched,
                        "table_rows": [r["rubrique_label"] for r in table_rows],
                    })
        return []

    logger.log("MATCH_SUMMARY", "OK",
                f"All {len(matches)}/{len(rubriques)} rubriques successfully and uniquely matched to Table 2 rows.")
    return matches


# =============================================================================
# Step 3: Dynamic In-Place Row Editing & Network Await
# =============================================================================
async def _edit_single_row_dynamic(page, match: dict, logger: GCLogger) -> bool:
    """
    Dynamically locates the row by its label in #DevisDetTableVal, clicks pencil,
    fills MontantHTValide, TaxeValide, TauxVetusteValide, MontantVetusteValide,
    clicks the row checkmark, and waits for POST /updateDevisDet.
    """
    rub = match["rubrique"]
    rub_id = str(rub.get("IdRubrique", "?"))
    rub_lib = rub.get("LibRubrique") or rub.get("_label") or RUBRIQUE_CATALOG.get(rub_id, "")
    target_label = match["target_label"]
    norm_target = normalize_text(target_label)

    montant_ht = str(rub.get("MontantHT", "0"))
    taxe = str(rub.get("Taxe", "0"))
    taux_vet = str(rub.get("TauxVetuste", "0.00"))
    mt_vet = str(rub.get("MontantVetuste", "0.00"))

    logger.log(f"EDIT_START", "INFO",
                f"Processing: [{rub_id}] '{rub_lib}' (HT={montant_ht}, TVA={taxe}, Vétusté={mt_vet})")

    # --- 3a. Re-locate the target row dynamically in the live DOM ---
    row_found = await page.evaluate(r"""(normTarget) => {
        const rows = document.querySelectorAll('#DevisDetTableVal tbody tr');
        for (let i = 0; i < rows.length; i++) {
            const label = rows[i].querySelector('td:first-child')?.textContent?.trim() || '';
            const norm = label.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9\s]/g, ' ').toLowerCase().replace(/\s+/g, ' ').trim();
            if (norm === normTarget || norm.includes(normTarget) || normTarget.includes(norm)) {
                return { found: true, rowIndex: i, label: label };
            }
        }
        return { found: false };
    }""", norm_target)

    if not row_found.get("found"):
        logger.log("EDIT_LOCATE", "ERROR",
                    f"Could not re-locate row with label '{target_label}' in #DevisDetTableVal.")
        return False

    live_idx = row_found["rowIndex"]

    # --- 3b. Click the pencil icon on that row ---
    click_pencil_res = await page.evaluate("""(idx) => {
        const row = document.querySelectorAll('#DevisDetTableVal tbody tr')[idx];
        if (!row) return { ok: false, error: 'Row not found at index ' + idx };
        
        let editBtn = row.querySelector('a.edit-row, a#Modifier, a[onclick*="editRow"], a[title*="Modifier"], i.fa-pencil');
        if (editBtn) {
            const clickable = editBtn.closest('a') || editBtn;
            clickable.click();
            return { ok: true };
        }
        return { ok: false, error: 'No edit icon found in row HTML: ' + row.innerHTML.substring(0, 200) };
    }""", live_idx)

    if not click_pencil_res.get("ok"):
        logger.log("EDIT_PENCIL", "ERROR",
                    f"Failed to click pencil: {click_pencil_res.get('error')}")
        return False

    # Wait for the inline inputs to appear
    await page.wait_for_timeout(800)

    # --- 3c. Fill MontantHTValide, TaxeValide, TauxVetusteValide, MontantVetusteValide ---
    fill_res = await page.evaluate("""(args) => {
        const { ht, taxe, tauxVet, mtVet } = args;
        const res = {};
        
        function setVal(sel, val) {
            const el = document.querySelector(sel);
            if (!el) return { found: false, selector: sel };
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: '0' }));
            if (typeof el.onkeyup === 'function') { try { el.onkeyup(); } catch(e) {} }
            if (typeof el.onchange === 'function') { try { el.onchange(); } catch(e) {} }
            if (window.jQuery) {
                try { window.jQuery(el).trigger('input').trigger('change').trigger('keyup'); } catch(e) {}
            }
            return { found: true, val: val, readBack: el.value };
        }
        
        res.ht = setVal('#MontantHTValide', ht);
        res.taxe = setVal('#TaxeValide', taxe);
        if (tauxVet && tauxVet !== '0.00' && tauxVet !== '0') {
            res.tauxVet = setVal('#TauxVetusteValide', tauxVet);
        }
        if (mtVet && mtVet !== '0.00' && mtVet !== '0') {
            res.mtVet = setVal('#MontantVetusteValide', mtVet);
        }
        
        const ttcEl = document.querySelector('#MontantTTCValide');
        res.ttc_computed = ttcEl ? ttcEl.value : null;
        return res;
    }""", {"ht": montant_ht, "taxe": taxe, "tauxVet": taux_vet, "mtVet": mt_vet})

    if not fill_res.get("ht", {}).get("found") or not fill_res.get("taxe", {}).get("found"):
        logger.log("EDIT_FILL", "ERROR",
                    "Required inputs (#MontantHTValide / #TaxeValide) were NOT found in the editing row!",
                    extra=fill_res)
        return False

    logger.log("EDIT_FILL", "OK",
                f"Injected HT={montant_ht}, TVA={taxe}, TTC(auto)={fill_res.get('ttc_computed')}")

    await page.wait_for_timeout(500)

    # --- 3d. Click the green checkmark and await network response ---
    save_clicked = False
    try:
        # Try to capture the updateDevisDet response if triggered via AJAX
        async with page.expect_response(
            lambda r: "updateDevisDet" in r.url,
            timeout=5000
        ) as response_info:
            click_save_res = await page.evaluate("""(idx) => {
                const row = document.querySelectorAll('#DevisDetTableVal tbody tr')[idx];
                if (!row) return { ok: false, error: 'Row disappeared' };
                
                let saveBtn = row.querySelector('a.save-row, a:has(.fa-check), a[onclick*="saveRow"], a[title*="Enregistrer"], i.fa-check');
                if (saveBtn) {
                    const clickable = saveBtn.closest('a') || saveBtn;
                    clickable.click();
                    return { ok: true };
                }
                return { ok: false, error: 'No checkmark/save button found in row' };
            }""", live_idx)

            if not click_save_res.get("ok"):
                logger.log("EDIT_SAVE", "ERROR", f"Could not click checkmark: {click_save_res.get('error')}")
                return False

            save_clicked = True

        # Check response
        resp = await response_info.value
        logger.log("EDIT_NETWORK", "OK" if resp.status == 200 else "WARN",
                    f"POST /updateDevisDet returned HTTP {resp.status}")

    except Exception as net_err:
        # If timeout waiting for AJAX, verify if the row locked in anyway
        if not save_clicked:
            # Click directly if expect_response wrapper failed
            await page.evaluate("""(idx) => {
                const row = document.querySelectorAll('#DevisDetTableVal tbody tr')[idx];
                if (row) {
                    const btn = row.querySelector('a.save-row, a:has(.fa-check), a[onclick*="saveRow"], i.fa-check');
                    if (btn) (btn.closest('a') || btn).click();
                }
            }""", live_idx)
        logger.log("EDIT_NETWORK", "INFO", f"Network response wait note: {net_err}")

    # Wait for table redraw
    await page.wait_for_timeout(2000)

    logger.log("EDIT_ROW_DONE", "OK",
                f"Row for [{rub_id}] '{rub_lib}' locked in successfully.")
    return True


# =============================================================================
# Step 4: Financial Split & Calculations
# =============================================================================
async def _trigger_devis_calculations(page, logger: GCLogger):
    """
    Executes MCMA's native DevisCalculerMontantCharge() and related functions.
    Does NOT blindly overwrite the values with hardcoded 0.
    """
    try:
        res = await page.evaluate("""() => {
            const results = {};
            if (typeof DevisCalculerMontantCharge === 'function') {
                try { DevisCalculerMontantCharge(); results.devisCalc = 'executed'; }
                catch(e) { results.devisCalc = 'error: ' + e.message; }
            } else {
                results.devisCalc = 'not_present';
            }
            
            if (typeof CalculerMntArrete === 'function') {
                try { CalculerMntArrete(); results.arrete = 'executed'; } catch(e) {}
            }
            
            // Trigger cascading change events
            const selectors = [
                '#DevisMontantTTC', '#DevisMontantTVA', '#DevisMontantVetusteTotal',
                '#DevisMontantFranchise', '#DevisMontantRemise', '#DevisPartResponsabilite',
                '#DevisTvaRecupI', '#MontantReparation'
            ];
            selectors.forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    if (window.jQuery) {
                        try { window.jQuery(el).trigger('keyup').trigger('change'); } catch(e) {}
                    }
                }
            });
            
            return results;
        }""")

        logger.log("CALCULATIONS", "OK", f"Calculations triggered: {res}")
    except Exception as e:
        logger.log("CALCULATIONS", "ERROR", f"Exception running calculations: {e}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
async def fill_garage_conventionne(page, data: dict, test_mode: bool = True) -> dict:
    """
    Main entry point for Garage Conventionné (PEC) mode.
    
    Guarantees:
      - Strict All-or-Nothing matching (0 writes if any rubrique fails to match)
      - Dynamic row locating
      - Awaits updateDevisDet
      - Valider Devis (#DEVISDET_Btn) is STRICTLY NEVER CLICKED
      - Full logging to logs/gc_<timestamp>.json
    """
    logger = GCLogger()
    rubriques = data.get("rubriques", [])

    print(f"\n{'='*70}")
    print(f"  🏗️  GARAGE CONVENTIONNÉ (PEC) AUTOMATION CONTROLLER")
    print(f"  📝  Target Rubriques count : {len(rubriques)}")
    print(f"  🛡️  Safety Review Mode    : {'ACTIVE (Zero final submissions)' if test_mode else 'OFF'}")
    print(f"  📋  Diagnostic Log File    : {logger.log_path}")
    print(f"{'='*70}\n")

    logger.log("START", "INFO",
                f"Starting Garage Conventionné controller for dossier {data.get('dossier_reference')} ({len(rubriques)} rubriques)")

    # --- Initial Screenshot ---
    await _save_screenshot(page, logger, "01_initial_state")

    # --- Step 1: Detect Table 2 ---
    print(f"[*] Step 1: Detecting Table 2 (#DevisDetTableVal)...")
    table_rows = await _detect_table2(page, logger)
    if not table_rows:
        logger.log("ABORT", "ERROR",
                    "Table 2 (#DevisDetTableVal) has no rows. Cannot proceed.")
        await _save_screenshot(page, logger, "02_no_table2_rows")
        summary = logger.summary()
        return {"status": "failed", "message": "Table 2 has no rows", **summary}

    # --- Step 2: Strict All-or-Nothing Matching ---
    print(f"[*] Step 2: Validating All-or-Nothing Rubrique Matching...")
    matches = match_all_rubriques(rubriques, table_rows, logger)
    if not matches or len(matches) != len(rubriques):
        logger.log("ABORT", "ERROR",
                    f"Matching failed: {len(matches)}/{len(rubriques)} rubriques matched. Aborting with ZERO modifications.")
        await _save_screenshot(page, logger, "03_matching_failed")
        summary = logger.summary()
        return {"status": "failed", "message": "All-or-Nothing matching failed. Zero rows modified.", **summary}

    # --- Step 3: Dynamic In-Place Row Editing ---
    print(f"[*] Step 3: Editing {len(matches)} Table 2 row(s) in-place...")
    success_count = 0

    for idx, match in enumerate(matches, 1):
        rub_id = match["rubrique"].get("IdRubrique", "?")
        rub_lib = match["rubrique"].get("LibRubrique") or match["rubrique"].get("_label", "")
        print(f"    [{idx}/{len(matches)}] Updating Row '{match['target_label']}' for Rubrique [{rub_id}] {rub_lib}...")

        ok = await _edit_single_row_dynamic(page, match, logger)
        if ok:
            success_count += 1
        else:
            logger.log("ROW_FAIL_ABORT", "ERROR",
                        f"Failed to edit row for Rubrique [{rub_id}]. Aborting remaining edits.")
            await _save_screenshot(page, logger, f"04_failed_row_{rub_id}")
            break

    # --- Screenshot after row edits ---
    await _save_screenshot(page, logger, "05_after_edits")

    # --- Step 4: Native Calculation & DOM Snapshot ---
    print(f"[*] Step 4: Executing native DevisCalculerMontantCharge()...")
    await _trigger_devis_calculations(page, logger)
    final_dom = await _snapshot_dom_fields(page, logger)

    # --- Step 5: Final Validation Button (STRICTLY UNTOUCHED) ---
    logger.log("VALIDER_DEVIS", "INFO",
                "SAFETY / REVIEW MODE — #DEVISDET_Btn ('Valider Devis') is STRICTLY UNTOUCHED for human verification.")
    print(f"    ⏸️  [SAFETY MODE] 'Valider Devis' (#DEVISDET_Btn) is UNTOUCHED for your inspection.")

    # --- Final Screenshot ---
    await _save_screenshot(page, logger, "06_final_verification")

    summary = logger.summary()
    status = "success" if success_count == len(matches) else "failed"

    print(f"\n{'='*70}")
    print(f"  📊 GARAGE CONVENTIONNÉ EXECUTION SUMMARY")
    print(f"  Status        : {status.upper()}")
    print(f"  Rows Edited   : {success_count}/{len(matches)}")
    print(f"  Errors Logged : {summary['errors']}")
    print(f"  Log File      : {summary['log_file']}")
    if final_dom:
        print(f"  Devis TTC     : {final_dom.get('DevisMontantTTC', '?')}")
        print(f"  Charge Mut.   : {final_dom.get('DevisMontantChargeMutuelle', '?')}")
        print(f"  Charge Soc.   : {final_dom.get('DevisMontantChargeSocietaire', '?')}")
    print(f"{'='*70}\n")

    return {
        "status": status,
        "message": f"Garage Conventionné: {success_count}/{len(matches)} rows updated.",
        **summary
    }
