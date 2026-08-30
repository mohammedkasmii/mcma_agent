"""
INC-06 correction #1 — the mock must be fully offline and self-contained: it
will later run inside the loopback-only Chromium environment (INC-07+), so no
external CDN/host reference may exist anywhere in the served HTML.
"""

import re

EXTERNAL_URL = re.compile(r"""(src|href)\s*=\s*["']https?://[^"']+["']""", re.IGNORECASE)


def _assert_no_external_urls(html: str):
    matches = EXTERNAL_URL.findall(html)
    assert not matches, f"external resource reference(s) found: {matches}"
    assert "cdnjs" not in html.lower()
    assert "cdn.jsdelivr" not in html.lower()
    assert "code.jquery.com" not in html.lower()
    assert "bootstrapcdn" not in html.lower()
    assert "googleapis.com" not in html.lower()
    assert "gstatic.com" not in html.lower()


def test_no_external_resource_urls_in_mission_page(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    assert resp.status_code == 200
    _assert_no_external_urls(resp.text)


def test_no_external_resource_urls_in_mission_search_page(client):
    resp = client.get("/SinAuto_MCMA/expertise/frontexpert/")
    assert resp.status_code == 200
    _assert_no_external_urls(resp.text)


def test_no_external_resource_urls_in_login_page(client):
    resp = client.get("/SinAuto_MCMA/login")
    assert resp.status_code == 200
    _assert_no_external_urls(resp.text)
