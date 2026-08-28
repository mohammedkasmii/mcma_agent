"""
browser/notifications.py — High-Speed & Resilient MCMA Notifications Extractor
==============================================================================
Fetches all active alert categories from the top navbar (#listeAlertes)
and extracts complete datatable records for each category.

Architecture:
  - Strategy 1 (Primary): Direct in-page asynchronous AJAX fetch (sub-second per category, zero reloads).
  - Strategy 2 (Fallback): DOM navigation with auto-retry and connection resilience.
  - Crash-Proof: Errors in individual categories are isolated and logged without aborting the run.
"""

import os
import sys
import re
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from core.config import DASHBOARD_URL, BASE_URL
from browser.mission_navigator import check_session_validity


async def _fetch_category_rows(page, code_alerte: str, title: str, category_url: str) -> List[Dict[str, Any]]:
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
            if attempt == 0:
                await asyncio.sleep(1.5)
            else:
                print(f"    [!] Note: Could not load table for '{title}': {err}")
                return []

    return []


async def fetch_all_notifications(page, headless: bool = True) -> Dict[str, Any]:
    """
    Main entry point to fetch all notification categories and their datatables.
    """
    print(f"[*] Navigating to MCMA dashboard to check notifications...")
    await page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)

    # 1. Verify session
    if not await check_session_validity(page):
        raise Exception("MCMA session expired. Please run 'python auth_setup.py' to renew your session.")

    # 2. Trigger notification fetch in navbar
    await page.evaluate("""() => {
        if (typeof actualierAlertes === 'function') {
            actualierAlertes();
        } else {
            const el = document.querySelector('#listeAlertes');
            if (el && window.jQuery) {
                window.jQuery(el).load('/SinAuto_MCMA/expertise/notification/alerte');
            }
        }
    }""")
    await page.wait_for_timeout(2000)

    # 3. Discover all alert category links from #listeAlertes
    categories_info = await page.evaluate(r"""() => {
        const results = [];
        const links = document.querySelectorAll('#listeAlertes a[href*="notification/alerte/"], #listeAlertes a[href*="notification/notification/alerte/"]');
        links.forEach(a => {
            const text = a.textContent.trim();
            const href = a.href;
            const badge = a.querySelector('.badge')?.textContent?.trim() || '';
            const match = href.match(/alerte\/([A-Za-z0-9\-]+)/i);
            const codeAlerte = match ? match[1] : '';
            
            let cleanTitle = text;
            if (badge) {
                cleanTitle = cleanTitle.replace(badge, '').trim();
            }
            cleanTitle = cleanTitle.replace(/\s+/g, ' ').trim();

            if (href && !results.some(r => r.codeAlerte === codeAlerte)) {
                results.push({
                    title: cleanTitle || 'ALERTE',
                    count: badge || '0',
                    codeAlerte: codeAlerte,
                    href: href,
                });
            }
        });
        return results;
    }""")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result: Dict[str, Any] = {
        "timestamp": ts,
        "total_categories": len(categories_info),
        "total_alerts": 0,
        "categories": [],
    }

    if not categories_info:
        print("    [i] No active notification categories found on the navbar.")
        return result

    print(f"    [+] Found {len(categories_info)} alert category(ies). Extracting table rows for each...\n")

    for cat in categories_info:
        title = cat["title"]
        code_alerte = cat["codeAlerte"]
        url = cat["href"]
        print(f"[*] Extracting category: '{title}' (Code: {code_alerte})...")

        rows_data = await _fetch_category_rows(page, code_alerte=code_alerte, title=title, category_url=url)

        cat_summary = {
            "category_name": title,
            "code_alerte": code_alerte,
            "count": len(rows_data),
            "items": rows_data,
        }

        result["categories"].append(cat_summary)
        result["total_alerts"] += len(rows_data)

        print(f"    [✓] Extracted {len(rows_data)} item(s) for '{title}'.")
        for idx, row in enumerate(rows_data[:3], 1):
            print(f"        {idx}. Ref: {row['reference']} | Plate: {row['matricule']} | Insured: {row['societaire']} | Status: {row['statut']}")
        if len(rows_data) > 3:
            print(f"        ... and {len(rows_data) - 3} more items.")
        print()

    return result
