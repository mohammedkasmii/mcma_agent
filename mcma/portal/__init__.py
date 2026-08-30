"""mcma.portal — Playwright gateway: capabilities, interception, session vault, identity gate. Sole Playwright owner (from INC-07).

INC-07 provides the context-level default-deny network policy:
mcma.portal.canonical (request canonicalization), mcma.portal.contracts
(RouteContract + the pure decision), mcma.portal.final_endpoints (the
permanent blocklist), and mcma.portal.interception (the async Playwright
adapter and its single public installer, install_portal_guard). INC-08
adds mcma.portal.capabilities (ReadCapability, LoginCapability) and
mcma.portal.session (the shared guarded-context opener). INC-09A adds
mcma.portal.identity (the two-tier identity gate) and mcma.portal.mission
(exactly-one search, mission-open navigation, workflow detection).
VerifiedMissionWriter, exact row matching, and row operations are INC-09B
and are not implemented here.
"""
