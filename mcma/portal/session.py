"""
mcma.portal.session -- shared BrowserContext opening helper for portal
capabilities (INC-08). Every context is hardened and guarded (INC-07)
BEFORE any page is created or navigated by the capabilities in
mcma.portal.capabilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from mcma.portal.contracts import RouteContract
from mcma.portal.interception import hardened_context_options, install_portal_guard

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.async_api import Browser, BrowserContext


async def open_guarded_context(
    browser: "Browser",
    contracts: Sequence[RouteContract],
    allowed_host: str,
    context_options: dict | None = None,
) -> "BrowserContext":
    """Opens one BrowserContext, hardens its creation options, and installs
    the INC-07 default-deny guard on it -- before any page exists. If
    context creation fails there is nothing to close; if guard installation
    fails, install_portal_guard itself closes the context and re-raises
    (INC-07 guarantee) -- this function does not need to duplicate that.

    `contracts` is copied into an immutable tuple FIRST (INC-08 amendment
    #4): a caller mutating their original list/sequence after this call
    must never change the policy that gets installed.
    """
    frozen_contracts = tuple(contracts)
    options = hardened_context_options(context_options)
    context = await browser.new_context(**options)
    await install_portal_guard(context, frozen_contracts, allowed_host)
    return context
