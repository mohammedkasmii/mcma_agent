"""INC-19 -- shared Playwright fixture for tests/web/*. Loads mcma/web/
app.js into a blank page (no server, no network) so its pure/DOM-facing
functions can be called directly via page.evaluate() -- this is real
browser DOM behavior (textContent/innerHTML escaping), not a Python
reimplementation of the JS."""

from pathlib import Path

import pytest

APP_JS_PATH = Path(__file__).resolve().parents[2] / "mcma" / "web" / "app.js"


def run_async(coro):
    import asyncio

    return asyncio.run(coro)


@pytest.fixture()
def dashboard_page():
    """Yields an async function `with_page(callback)` that opens a fresh
    headless page with app.js loaded, runs `callback(page)`, and closes
    the browser -- avoids requiring an async fixture (this project's
    Playwright tests are all run_async(...)-driven, not pytest-asyncio)."""

    async def _with_page(callback):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto("about:blank")
                await page.add_script_tag(path=str(APP_JS_PATH))
                return await callback(page)
            finally:
                await browser.close()

    return _with_page
