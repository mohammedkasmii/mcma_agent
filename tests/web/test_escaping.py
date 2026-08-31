"""INC-19 -- test_portal_data_is_escaped_not_innerHTML: claimant-
controlled content can never break out of the DOM tree via
renderNotificationRow/List. Real Chromium DOM (not a Python
reimplementation of the JS)."""

import pytest

from web_test_support import run_async

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]

XSS_PAYLOAD = "<img src=x onerror=window.__xss_fired=true>"
SCRIPT_PAYLOAD = "<script>window.__xss_fired=true</script>"
QUOTE_BREAKOUT_PAYLOAD = '"><svg onload=window.__xss_fired=true>'


async def _render_and_check(page, payload):
    return await page.evaluate(
        """(payload) => {
            window.__xss_fired = false;
            const row = window.mcmaDashboard.renderNotificationRow({
                reference: payload,
                seen_at: '2026-01-01',
                account_entity: 'MCMA',
                account_scope: 'OUJDA',
            });
            document.body.appendChild(row);
            return {
                fired: window.__xss_fired,
                hasImg: row.querySelector('img') !== null,
                hasScript: row.querySelector('script') !== null,
                hasSvg: row.querySelector('svg') !== null,
                text: row.textContent,
            };
        }""",
        payload,
    )


def test_portal_data_is_escaped_not_innerHTML(dashboard_page):
    """A <script>/quote in a field cannot break out (the named required
    test): a claimant-controlled reference containing a live script tag
    is rendered as inert text -- it never executes, and no <script>
    element is ever created in the DOM."""

    async def _run():
        return await dashboard_page(lambda page: _render_and_check(page, SCRIPT_PAYLOAD))

    result = run_async(_run())
    assert result["fired"] is False
    assert result["hasScript"] is False
    assert SCRIPT_PAYLOAD in result["text"]  # present as literal text, not parsed as markup


def test_img_onerror_payload_never_executes(dashboard_page):
    async def _run():
        return await dashboard_page(lambda page: _render_and_check(page, XSS_PAYLOAD))

    result = run_async(_run())
    assert result["fired"] is False
    assert result["hasImg"] is False
    assert XSS_PAYLOAD in result["text"]


def test_attribute_breakout_payload_never_executes(dashboard_page):
    async def _run():
        return await dashboard_page(lambda page: _render_and_check(page, QUOTE_BREAKOUT_PAYLOAD))

    result = run_async(_run())
    assert result["fired"] is False
    assert result["hasSvg"] is False
    assert QUOTE_BREAKOUT_PAYLOAD in result["text"]


def test_escape_html_helper_neutralizes_tags(dashboard_page):
    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate("(payload) => window.mcmaDashboard.escapeHtml(payload)", "<b>bold</b>")
        )

    escaped = run_async(_run())
    assert "<b>" not in escaped
    assert "&lt;b&gt;" in escaped


def test_notification_list_render_clears_previous_content_without_innerHTML(dashboard_page):
    """renderNotificationList must clear via .textContent (never a raw
    innerHTML='' + string-concatenation re-render), proven by rendering
    twice and confirming the DOM subtree only ever contains legitimate
    child elements, never leftover/duplicated unescaped markup."""

    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """() => {
                    const ul = document.createElement('ul');
                    document.body.appendChild(ul);
                    window.mcmaDashboard.renderNotificationList(ul, [
                        {reference: '<b>one</b>', account_entity: 'MCMA', account_scope: 'OUJDA'},
                    ]);
                    window.mcmaDashboard.renderNotificationList(ul, [
                        {reference: '<b>two</b>', account_entity: 'MCMA', account_scope: 'NADOR'},
                    ]);
                    return {
                        rowCount: ul.querySelectorAll('.notification-row').length,
                        hasBold: ul.querySelector('b') !== null,
                        text: ul.textContent,
                    };
                }"""
            )
        )

    result = run_async(_run())
    assert result["rowCount"] == 1  # second render replaced, did not append to, the first
    assert result["hasBold"] is False
    assert "<b>two</b>" in result["text"]
