"""
mcma.portal.browser -- the process's ONE Playwright browser lifecycle
(composition-root support).

Why this module exists at all: the job runner needs a live `browser`
object, but the import-linter contract "Single owner: only mcma.portal
imports playwright" forbids `mcma.app` (and everything else) from
importing playwright directly. A composition root that wrote
`async_playwright()` itself would break that contract. So the launch/
close lifecycle lives here, beside every other Playwright-touching
module, and the app layer receives an already-launched browser handle
without ever naming Playwright.

HEADFUL BY DEFAULT, deliberately. Every test in this repository launches
headless because no human is watching. Production is the opposite case:
the whole human-browser handoff (WORKFLOW_STATE_MODEL.md's READY_FOR_
HUMAN_REVIEW, section 4) depends on the employee SEEING the window the
agent prepared, reviewing it, and closing it themselves -- a headless
browser would make the handoff invisible and the employee's close event,
which is what drives transition_on_browser_closed, impossible to
produce. `headless=True` is therefore an explicit opt-in for automated
runs, never the default.

This module launches a browser and nothing else. It applies no route
contracts, opens no context, and holds no session: every safety control
(default-deny interception, allowed_host binding, identity/workflow
verification, lease checks) lives in mcma.portal.capabilities /
mcma.portal.writer and is applied per-context by those modules. A bare
browser here can reach nothing on its own.
"""

from __future__ import annotations

from contextlib import asynccontextmanager


@asynccontextmanager
async def launch_browser(*, headless: bool = False):
    """Async context manager yielding one Chromium browser for the life
    of the process. Both the browser and the Playwright driver are closed
    on exit, including on exception -- a leaked driver survives the
    Python process on Windows and holds the profile directory open.

    Must be entered on the same event loop the runner will use: Playwright's
    async API is bound to the loop it was started on.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        try:
            yield browser
        finally:
            await browser.close()
