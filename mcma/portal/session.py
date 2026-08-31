"""
mcma.portal.session -- shared BrowserContext opening helper for portal
capabilities (INC-08). Every context is hardened and guarded (INC-07)
BEFORE any page is created or navigated by the capabilities in
mcma.portal.capabilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from mcma.portal.contracts import RouteContract
from mcma.portal.interception import (
    WriterPolicyController,
    hardened_context_options,
    install_login_guard,
    install_phased_portal_guard,
    install_portal_guard,
)

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


async def open_guarded_context_for_login(
    browser: "Browser",
    allowed_host: str,
    context_options: dict | None = None,
) -> "BrowserContext":
    """For LoginCapability only. Same hardened context options as every
    other capability; the difference is the policy installed on it, which
    permits the portal's own sign-in flow on ONE host while keeping every
    final endpoint permanently blocked (see install_login_guard)."""
    options = hardened_context_options(context_options)
    context = await browser.new_context(**options)
    await install_login_guard(context, allowed_host)
    return context


async def open_guarded_context_for_writer(
    browser: "Browser",
    controller: WriterPolicyController,
    allowed_host: str,
    context_options: dict | None = None,
) -> "BrowserContext":
    """INC-09B: opens one BrowserContext for mcma.portal.writer, hardens
    its creation options, and installs the phased (explicit-state-machine)
    guard bound to an ALREADY-CONSTRUCTED WriterPolicyController -- the
    controller (and the validated/frozen write-contract tuple it holds)
    must exist before this is ever called, since amendment #1 requires the
    complete row_write/native_recalc contract tuple to be validated and
    frozen before any BrowserContext is created. `open_guarded_context`
    above is completely unaffected by this addition."""
    options = hardened_context_options(context_options)
    context = await browser.new_context(**options)
    await install_phased_portal_guard(context, controller, allowed_host)
    return context
