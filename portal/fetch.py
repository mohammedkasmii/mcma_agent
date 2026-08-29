"""
portal/fetch.py — Alert Row Extraction
=======================================
Pulls every row of one alert category out of the portal.

Two strategies, in order:
  1. In-page AJAX POST to getAlerte/CodeAlerte/{code} with length=-1 — sub-second,
     no page reload, returns the full dataset in one call.
  2. DOM navigation fallback with DataTables "Tout" and one retry.

This lives in portal/ rather than browser/ because it is portal knowledge — the
endpoint shape, the field names, the status codes — not browser mechanics.
browser/ keeps only Playwright plumbing (DOM helpers, form filling, safety
interception), which is what BLUEPRINT SS14's layering requires.

Raises on failure rather than returning []. An empty list must mean "the portal
answered and there was nothing there"; anything else is a FAILED category, and
conflating the two archives live claims (SS8.2).
"""

import asyncio
import re
from typing import Any, Dict, List


class CategoryFetchError(RuntimeError):
    """Raised when a category could not be read. Never conflate with 'empty'."""


async def fetch_category_rows(page, code_alerte: str, title: str, category_url: str) -> List[Dict[str, Any]]:
    """
    Extracts all rows for an alert category.
    Strategy 1: Direct in-page AJAX POST to /getAlerte/CodeAlerte/{code_alerte} (instant, sub-second).
    Strategy 2: If AJAX fails, falls back to DOM navigation with auto-retry.
    """
    # -------------------------------------------------------------------------
    # Strategy 1: Direct In-Page AJAX with Full Dataset Parameters (length=-1)
    # -------------------------------------------------------------------------
    try:
        ajax_res = await page.evaluate(r"""async (codeAlerte) => {
            try {
                const params = new URLSearchParams({
                    'length': '-1',
                    'start': '0',
                    'iDisplayLength': '-1',
                    'iDisplayStart': '0',
                    'rows': '999999',
                    'limit': '999999',
                    'page': '1',
                    'draw': '1'
                });
                const resp = await fetch('/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/' + codeAlerte, {
                    method: 'POST',
                    headers: { 
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json, text/javascript, */*',
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
                    },
                    body: params.toString()
                });
                if (!resp.ok) return { ok: false, status: resp.status };
                const text = await resp.text();
                try {
                    const json = JSON.parse(text);
                    if (Array.isArray(json)) return { ok: true, data: json };
                    if (json && json.data && Array.isArray(json.data)) return { ok: true, data: json.data };
                    if (json && json.rows && Array.isArray(json.rows)) return { ok: true, data: json.rows };
                } catch(e) {}
                return { ok: false, raw: text.substring(0, 100) };
            } catch(err) {
                return { ok: false, error: err.message };
            }
        }""", code_alerte)

        if ajax_res.get("ok") and ajax_res.get("data") and len(ajax_res["data"]) > 0:
            raw_list = ajax_res["data"]
            items = []
            for row in raw_list:
                id_sin = str(row.get("IdSinistre") or "").strip()
                ref_cie = str(row.get("ReferenceCie") or "").strip()
                ref_clean = re.sub(r"<[^>]+>", "", ref_cie).strip()

                nature_raw = str(row.get("Nature") or "").upper()
                nature_label = "CORPOREL" if nature_raw == "C" else "MATÉRIEL"

                sort_raw = str(row.get("SortSin") or "").upper()
                statut_map = {
                    "D": "DÉCLARÉ",
                    "E": "EN COURS",
                    "F": "FERMÉ",
                    "C": "CLÔTURÉ",
                    "R": "RÉOUVERT",
                }
                statut_label = statut_map.get(sort_raw, sort_raw or "DÉCLARÉ")

                items.append({
                    "reference": ref_clean,
                    "id_sinistre": id_sin,
                    "date_survenance": str(row.get("DateSin") or "").strip(),
                    "societaire": str(row.get("NomSocietaire") or "").strip(),
                    "police": str(row.get("Police") or "").strip(),
                    "matricule": str(row.get("Matricule") or "").strip(),
                    "nature": nature_label,
                    "statut": statut_label,
                    "direct_url": f"/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id_sin}/rubrique/gestionexpert-index" if id_sin else "",
                })
            return items
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # Strategy 2: DOM Navigation Fallback with Select "Tout" (-1) and Retries
    # -------------------------------------------------------------------------
    last_error: Any = None
    for attempt in range(2):
        try:
            await page.goto(category_url, timeout=20000, wait_until="domcontentloaded")
            await page.wait_for_selector("#listeAlerte", timeout=8000)

            # Trigger "Tout" (-1) on DataTables and DOM Select
            await page.evaluate(r"""() => {
                try {
                    if (window.jQuery && jQuery.fn.DataTable && jQuery.fn.DataTable.isDataTable('#listeAlerte')) {
                        jQuery('#listeAlerte').DataTable().page.len(-1).draw();
                    } else if (window.jQuery && jQuery.fn.dataTable) {
                        jQuery('#listeAlerte').dataTable().fnLengthChange(-1);
                    }
                } catch(e) {}
                
                const selects = document.querySelectorAll("select[name*='listeAlerte_length'], select[aria-controls='listeAlerte'], #listeAlerte_length select");
                selects.forEach(sel => {
                    sel.value = "-1";
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                    if (window.jQuery) jQuery(sel).trigger('change');
                });
            }""")
            await page.wait_for_timeout(1200)

            # Extract from DOM Table
            rows_data = await page.evaluate(r"""() => {
                const rows = document.querySelectorAll('#listeAlerte tbody tr');
                const items = [];
                rows.forEach(tr => {
                    const text = tr.textContent.trim();
                    if (text.includes('aucun') || text.includes('Aucun') || text.includes('No data') || text === '') return;
                    const tds = tr.querySelectorAll('td');
                    if (tds.length >= 5) {
                        const link = tds[0]?.querySelector('a');
                        const refText = tds[0]?.textContent?.trim() || '';
                        let idSinistre = '';
                        if (link) {
                            const href = link.getAttribute('href') || '';
                            const idMatch = href.match(/gotoSinistre\((\d+)\)/i);
                            if (idMatch) idSinistre = idMatch[1];
                        }
                        items.push({
                            reference: refText,
                            id_sinistre: idSinistre,
                            date_survenance: tds[1]?.textContent?.trim() || '',
                            societaire: tds[2]?.textContent?.trim() || '',
                            police: tds[3]?.textContent?.trim() || '',
                            matricule: tds[4]?.textContent?.trim() || '',
                            nature: tds[5]?.textContent?.trim() || '',
                            statut: tds[6]?.textContent?.trim() || '',
                            direct_url: idSinistre ? `/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/${idSinistre}/rubrique/gestionexpert-index` : '',
                        });
                    }
                });
                return items;
            }""")
            return rows_data
        except Exception as err:
            last_error = err
            if attempt == 0:
                await asyncio.sleep(1.5)

    # Both strategies exhausted. RAISE - never return [].
    #
    # This is the root of the SS8.2 defect: the previous implementation returned
    # a bare [] here, making a failed category indistinguishable from a genuinely
    # empty one. The caller then counted every claim in that category as missing
    # and archived the lot after three polls.
    raise CategoryFetchError(
        f"Extraction impossible pour la categorie '{title}' "
        f"(code {code_alerte}) : {last_error}"
    )
