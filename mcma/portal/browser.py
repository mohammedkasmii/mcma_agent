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
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcma.core.client_certificate import SinautoClientCertificate

# Context options a certificate-bearing browser never lets a caller set:
# the certificate itself is fixed by the composition root, a proxy would
# route the certificate-bearing connection elsewhere, and
# ignore_https_errors would let the driver present the certificate to a
# server whose own certificate it did not verify.
_REFUSED_CONTEXT_OPTIONS = ("client_certificates", "proxy")


class ClientCertificateBrowser:
    """Wraps a Playwright Browser so that EVERY context it opens carries
    the SinAuto client certificate for exactly one origin, with HTTPS
    verification on. Used only by the central notification service.

    Pages must be opened through new_context() (where the portal guard is
    installed too); Browser.new_page() would create an implicit context
    and is refused."""

    __slots__ = ("_browser", "_certificate")

    def __init__(self, browser, certificate: "SinautoClientCertificate") -> None:
        self._browser = browser
        self._certificate = certificate

    @property
    def client_certificate_origin(self) -> str:
        return self._certificate.origin

    async def new_context(self, **options):
        for name in _REFUSED_CONTEXT_OPTIONS:
            if name in options:
                raise ValueError(f"{name} may not be set on a client-certificate browser context")
        if options.get("ignore_https_errors"):
            raise ValueError("ignore_https_errors may not be enabled on a client-certificate browser context")
        options["ignore_https_errors"] = False
        options["client_certificates"] = self._certificate.playwright_client_certificates()
        return await self._browser.new_context(**options)

    async def new_page(self, **_options):
        raise RuntimeError(
            "new_page() is refused on a client-certificate browser; open a guarded context instead"
        )

    def is_connected(self) -> bool:
        return self._browser.is_connected()

    @property
    def contexts(self):
        return self._browser.contexts

    async def close(self, **options) -> None:
        await self._browser.close(**options)

    async def self_test(self) -> None:
        """Opens and closes one certificate-bearing context with no page
        and no navigation. Playwright's driver loads the certificate when
        the context is created, so a passphrase it rejects or an encoding
        its OpenSSL cannot read fails HERE, at launch, with a fixed
        message -- never later as a silent unauthenticated poll."""
        # Imported here so workstation/local callers of this module load
        # nothing new.
        from mcma.core.client_certificate import ClientCertificateError

        try:
            context = await self.new_context()
            await context.close()
        except Exception:
            raise ClientCertificateError(
                "the browser could not load the SinAuto client certificate"
            ) from None

    def __repr__(self) -> str:
        return f"ClientCertificateBrowser(origin={self._certificate.origin!r})"


@asynccontextmanager
async def launch_browser(
    *, headless: bool = False, client_certificate: Optional["SinautoClientCertificate"] = None,
):
    """Async context manager yielding one Chromium browser for the life
    of the process. Both the browser and the Playwright driver are closed
    on exit, including on exception -- a leaked driver survives the
    Python process on Windows and holds the profile directory open.

    Must be entered on the same event loop the runner will use: Playwright's
    async API is bound to the loop it was started on.

    `client_certificate` is passed ONLY by the central server's
    notification service. When given, the yielded object is a
    ClientCertificateBrowser that has already passed its self-test; when
    omitted (every workstation/local caller), behaviour is unchanged and the
    plain Browser is yielded.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        try:
            if client_certificate is None:
                yield browser
            else:
                guarded = ClientCertificateBrowser(browser, client_certificate)
                await guarded.self_test()
                yield guarded
        finally:
            await browser.close()
