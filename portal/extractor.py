"""
portal/extractor.py — Category-Scoped Alert Extraction
=======================================================
Wraps the proven extraction logic in browser/notifications.py with the
discriminated result type required by PROJECT_ARCHITECTURE_BLUEPRINT.md §8.2.

The defect this exists to fix:

    browser/notifications.py returns a bare [] when a category fails both retry
    attempts, and records it with count: 0. A FAILED category and a genuinely
    EMPTY one are byte-identical in the output. If the lifecycle reconciler
    treats a failed category as successful-and-empty, every claim in it is
    counted missing and archived after three ticks.

So every category now reports SUCCESS / EMPTY / FAILED, and only SUCCESS or
EMPTY may drive lifecycle reconciliation.

Transport note (§4.1): this still drives Playwright, because the httpx spike has
not been run. Unlike the old API path it opens ONE browser context per poll cycle
rather than one per HTTP request, which removes the "five employees, five
Chromiums" problem. Swapping in httpx later means replacing _fetch_category only.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from browser.notifications import _fetch_category_rows
from browser.mission_navigator import check_session_validity

SUCCESS = "SUCCESS"
EMPTY = "EMPTY"
FAILED = "FAILED"


@dataclass
class CategoryResult:
    """One alert category's extraction outcome. Never a bare list."""
    code: str
    name: str
    outcome: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def may_reconcile(self) -> bool:
        """
        True only when the portal actually answered for this category.
        §8.1 — a FAILED category must never advance the lifecycle.
        """
        return self.outcome in (SUCCESS, EMPTY)

    def to_row(self) -> Dict[str, Any]:
        return {
            "category_code": self.code,
            "category_name": self.name,
            "outcome": self.outcome,
            "alerts_seen": len(self.items),
            "error": self.error,
        }


@dataclass
class AccountPollResult:
    """Every category for one account in one poll cycle."""
    account_id: str
    outcome: str                       # SUCCESS | PARTIAL | AUTH_FAILED | UNREACHABLE
    categories: List[CategoryResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def total_alerts(self) -> int:
        return sum(len(c.items) for c in self.categories)

    @property
    def failed_categories(self) -> List[CategoryResult]:
        return [c for c in self.categories if c.outcome == FAILED]


async def discover_categories(page, dashboard_url: str) -> List[Dict[str, str]]:
    """Reads the alert categories from the navbar (#listeAlertes)."""
    await page.goto(dashboard_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)

    if not await check_session_validity(page):
        raise PermissionError("Session MCMA expirée ou invalide.")

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

    return await page.evaluate(r"""() => {
        const results = [];
        const links = document.querySelectorAll(
            '#listeAlertes a[href*="notification/alerte/"], ' +
            '#listeAlertes a[href*="notification/notification/alerte/"]');
        links.forEach(a => {
            const text = a.textContent.trim();
            const badge = a.querySelector('.badge')?.textContent?.trim() || '';
            const match = a.href.match(/alerte\/([A-Za-z0-9\-]+)/i);
            const codeAlerte = match ? match[1] : '';
            let cleanTitle = badge ? text.replace(badge, '').trim() : text;
            cleanTitle = cleanTitle.replace(/\s+/g, ' ').trim();
            if (a.href && !results.some(r => r.codeAlerte === codeAlerte)) {
                results.push({
                    title: cleanTitle || 'ALERTE',
                    codeAlerte: codeAlerte,
                    href: a.href,
                });
            }
        });
        return results;
    }""")


async def _fetch_category(page, code: str, name: str, url: str) -> CategoryResult:
    """
    Extracts one category and classifies the outcome.

    An exception, or a None return, means FAILED. An empty list from a call that
    did not raise means the category is genuinely EMPTY — the portal answered and
    there was nothing in it.
    """
    try:
        rows = await _fetch_category_rows(page, code_alerte=code, title=name, category_url=url)
    except Exception as e:
        return CategoryResult(code=code, name=name, outcome=FAILED, error=str(e)[:300])

    if rows is None:
        return CategoryResult(code=code, name=name, outcome=FAILED,
                              error="Extraction returned no result object.")
    if len(rows) == 0:
        return CategoryResult(code=code, name=name, outcome=EMPTY, items=[])
    return CategoryResult(code=code, name=name, outcome=SUCCESS, items=rows)


async def poll_account(page, account_id: str, dashboard_url: str) -> AccountPollResult:
    """
    Extracts every alert category for one account.

    Outcome is PARTIAL — not SUCCESS — when any category failed, so the
    reconciler knows some categories are ineligible for archiving this tick.
    """
    try:
        categories = await discover_categories(page, dashboard_url)
    except PermissionError as e:
        return AccountPollResult(account_id=account_id, outcome="AUTH_FAILED", error=str(e))
    except Exception as e:
        return AccountPollResult(account_id=account_id, outcome="UNREACHABLE", error=str(e)[:300])

    results: List[CategoryResult] = []
    for cat in categories:
        results.append(
            await _fetch_category(page, cat["codeAlerte"], cat["title"], cat["href"])
        )

    outcome = "PARTIAL" if any(c.outcome == FAILED for c in results) else "SUCCESS"
    return AccountPollResult(account_id=account_id, outcome=outcome, categories=results)


def to_legacy_payload(result: AccountPollResult) -> Dict[str, Any]:
    """Renders the old logs/mcma_notifications.json shape, for compatibility."""
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_categories": len(result.categories),
        "total_alerts": result.total_alerts,
        "categories": [
            {
                "category_name": c.name,
                "code_alerte": c.code,
                "count": len(c.items),
                "items": c.items,
            }
            for c in result.categories
        ],
    }
