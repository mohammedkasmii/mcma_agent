"""
browser/safety_interceptor.py — Network-Level Mutating Endpoint Interceptor
===========================================================================
Installs Playwright route interception in TEST_MODE to block any accidental
submissions (save, validate, close, GED) at the HTTP socket level.
"""

import json
from typing import List

#: Sentinel key present in every blocked response body. Callers MUST treat a
#: response carrying this key as a failed write (fail closed), never as success.
BLOCKED_SENTINEL_KEY = "__mcma_blocked"

# ---------------------------------------------------------------------------
# Every pattern below MUST correspond to an endpoint observed in a real network
# capture (script spy/website_investigation_v6/, v12_camoufox_output/) or in
# mock_server.py. Never add an endpoint inferred from a sibling's name.
#
# History: the list previously blocked "createDevisDet", which does not exist on
# the portal, while the real Mode Normal row-creation endpoint
# "createRapportDefDet" was absent — so Mode Normal row writes were never
# intercepted at all. See PROJECT_ARCHITECTURE_BLUEPRINT.md §11.0.
# ---------------------------------------------------------------------------
MUTATING_ENDPOINTS: List[str] = [
    # --- Final validation / closure (irreversible) ---
    "**/garageModifierValDevis",   # fired by ValiderDevis() on #DEVISDET_Btn
    "**/validerDevis",
    "**/expertCloturerMission",
    "**/cloturerMission",
    "**/expertEnregistrerMission",
    "**/enregistrerMission",
    "**/cloturerTraitement",
    # --- Row-level writes ---
    "**/createRapportDefDet",      # Mode Normal: adds a rubrique row to #tableRapportDet
    "**/updateDevisDet",           # Mode Conventionné: edits a row in #DevisDetTableVal
    "**/deleteRapportDefDet",
    "**/deleteDevisDet",
    # --- GED document writes ---
    "**/ajouterDocument",
    "**/deleteDocument",
]


async def install_safety_policy(page, enabled: bool = True):
    """
    Blocks mutating endpoints at the network layer during safety / preview mode.
    """
    if not enabled:
        return

    async def block_handler(route):
        url = route.request.url
        print(f"\n    🛡️  [SAFETY POLICY] Intercepted and blocked live write request to: {url}")
        # Fail CLOSED. A blocked write must never look like a successful one:
        # the previous implementation returned HTTP 200 {"state":"success"}, which
        # made read-back verification report success for a write that never happened.
        # See PROJECT_ARCHITECTURE_BLUEPRINT.md §11.3.
        await route.fulfill(
            status=403,
            content_type="application/json",
            body=json.dumps({
                "__mcma_blocked": True,
                "state": "blocked",
                "endpoint": url,
                "message": "Blocked by MCMA safety policy. No write was performed.",
            }),
        )

    for pattern in MUTATING_ENDPOINTS:
        await page.route(pattern, block_handler)
