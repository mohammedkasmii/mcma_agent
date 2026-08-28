"""
browser/notifications.py — MCMA Notifications & Alerts Extractor
================================================================
Fetches all active alert categories from the top navbar (#listeAlertes)
and extracts the complete datatable records for each category.

Extracted fields per row:
  - Référence Sinistre (ReferenceCie)
  - ID Sinistre (IdSinistre)
  - Date de survenance (DateSin)
  - Nom du sociétaire (NomSocietaire)
  - Numéro de Police (Police)
  - Immatriculation / Matricule (Matricule)
  - Nature du sinistre (Nature: MATÉRIEL / CORPOREL)
  - Statut du dossier (SortSin: DÉCLARÉ / EN COURS / etc.)
  - Direct URL to open the mission directly in MCMA
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


async def fetch_all_notifications(page, headless: bool = True) -> Dict[str, Any]:
    """
    Main function to fetch all notification categories and their complete datatable rows.
    """
    print(f"[*] Navigating to MCMA dashboard to check notifications...")
    await page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)

    # 1. Verify session
    if not await check_session_validity(page):
        raise Exception("MCMA session expired. Please run 'python auth_setup.py' to renew your session.")

    # 2. Trigger notification fetch if not already populated
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
            
            // Clean category title
            let cleanTitle = text;
            if (badge) {
                cleanTitle = cleanTitle.replace(badge, '').trim();
            }
            cleanTitle = cleanTitle.replace(/\\s+/g, ' ').trim();

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

        # Navigate to the specific alert category page
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Wait for table to load
        try:
            await page.wait_for_selector("#listeAlerte", timeout=10000)
        except Exception:
            print(f"    [!] Table #listeAlerte did not appear for category '{title}'.")
            continue

        # Try to select "Tout" in pagination to get all rows on one page
        try:
            select_loc = page.locator("select[name='listeAlerte_length'], #listeAlerte_length select").first
            if await select_loc.count() > 0:
                await select_loc.select_option(value="-1")
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # Extract all rows from #listeAlerte
        rows_data = await page.evaluate(r"""() => {
            const rows = document.querySelectorAll('#listeAlerte tbody tr');
            const items = [];
            
            rows.forEach(tr => {
                const text = tr.textContent.trim();
                if (text.includes('aucun') || text.includes('Aucun') || text.includes('No data') || text === '') {
                    return;
                }
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

                    const dateSin = tds[1]?.textContent?.trim() || '';
                    const societaire = tds[2]?.textContent?.trim() || '';
                    const police = tds[3]?.textContent?.trim() || '';
                    const matricule = tds[4]?.textContent?.trim() || '';
                    const nature = tds[5]?.textContent?.trim() || '';
                    const statut = tds[6]?.textContent?.trim() || '';

                    items.push({
                        reference: refText,
                        id_sinistre: idSinistre,
                        date_survenance: dateSin,
                        societaire: societaire,
                        police: police,
                        matricule: matricule,
                        nature: nature,
                        statut: statut,
                        direct_url: idSinistre ? `/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/${idSinistre}/rubrique/gestionexpert-index` : '',
                    });
                }
            });
            return items;
        }""")

        cat_summary = {
            "category_name": title,
            "code_alerte": code_alerte,
            "count": len(rows_data),
            "items": rows_data,
        }

        result["categories"].append(cat_summary)
        result["total_alerts"] += len(rows_data)

        print(f"    [✓] Extracted {len(rows_data)} item(s) for '{title}'.")
        for idx, row in enumerate(rows_data[:5], 1):
            print(f"        {idx}. Ref: {row['reference']} | Plate: {row['matricule']} | Insured: {row['societaire']} | Status: {row['statut']}")
        if len(rows_data) > 5:
            print(f"        ... and {len(rows_data) - 5} more items.")
        print()

    # Return to dashboard
    await page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
    return result
