"""
browser/safety_interceptor.py — Network-Level Mutating Endpoint Interceptor
===========================================================================
Installs Playwright route interception in TEST_MODE to block any accidental
submissions (save, validate, close, GED) at the HTTP socket level.
"""

from typing import List

MUTATING_ENDPOINTS: List[str] = [
    "**/garageModifierValDevis",
    "**/expertCloturerMission",
    "**/expertEnregistrerMission",
    "**/cloturerMission",
    "**/enregistrerMission",
    "**/ajouterDocument",
    "**/deleteDocument",
    "**/cloturerTraitement",
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
        await route.fulfill(
            status=200,
            content_type="application/json",
            body='{"state":"success","message":"[SIMULATED] Blocked by safety mode"}'
        )

    for pattern in MUTATING_ENDPOINTS:
        await page.route(pattern, block_handler)
