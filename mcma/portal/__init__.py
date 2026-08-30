"""mcma.portal — Playwright gateway: capabilities, interception, session vault, identity gate. Sole Playwright owner (from INC-07).

INC-07 (this increment) provides the context-level default-deny network
policy: mcma.portal.canonical (request canonicalization), mcma.portal.
contracts (RouteContract + the pure decision), mcma.portal.final_endpoints
(the permanent blocklist), and mcma.portal.interception (the async
Playwright adapter and its single public installer, install_portal_guard).
Capabilities (ReadCapability, LoginCapability, VerifiedMissionWriter) and
identity verification are INC-08/INC-09 and are not implemented here.
"""
