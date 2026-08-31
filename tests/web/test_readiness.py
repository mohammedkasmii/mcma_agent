"""INC-19 -- test_readiness_label_reflects_real_check_not_finally_block:
the readiness label always reflects the REAL job status the server
returned (or an explicit error state on failure) -- there is no
try/finally fallback that could show a ready-sounding label regardless
of outcome, and no code path derives readiness from a file's existence."""

import pytest

from web_test_support import run_async

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]


def test_readiness_label_reflects_real_check_not_finally_block(dashboard_page):
    """A failed fetch (simulated -- no real network involved) must show an
    explicit error state, never a label from STATUS_LABELS that could be
    mistaken for success."""

    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """async () => {
                    const label = document.createElement('p');
                    const failingFetch = () => Promise.reject(new Error('network down'));
                    await window.mcmaDashboard.updateReadinessDisplay(failingFetch, label, 'job-1');
                    return label.textContent;
                }"""
            )
        )

    text = run_async(_run())
    assert "ready" not in text.lower()
    assert "completed" not in text.lower()
    assert "check connection" in text.lower()


def test_readiness_label_reflects_the_real_returned_status_when_ready(dashboard_page):
    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """async () => {
                    const label = document.createElement('p');
                    const fakeFetch = () => Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({jobs: [{job_id: 'job-1', status: 'READY_FOR_HUMAN_REVIEW'}]}),
                    });
                    await window.mcmaDashboard.updateReadinessDisplay(fakeFetch, label, 'job-1');
                    return label.textContent;
                }"""
            )
        )

    text = run_async(_run())
    assert "ready" in text.lower()


def test_readiness_label_is_truthful_for_a_write_aborted_job(dashboard_page):
    """A genuinely failed workflow (WRITE_ABORTED) must never be labeled
    as ready/success."""

    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """async () => {
                    const label = document.createElement('p');
                    const fakeFetch = () => Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({jobs: [{job_id: 'job-1', status: 'WRITE_ABORTED'}]}),
                    });
                    await window.mcmaDashboard.updateReadinessDisplay(fakeFetch, label, 'job-1');
                    return label.textContent;
                }"""
            )
        )

    text = run_async(_run())
    assert "abort" in text.lower()
    assert "ready" not in text.lower()


def test_http_ok_false_never_shows_a_ready_label(dashboard_page):
    async def _run():
        return await dashboard_page(
            lambda page: page.evaluate(
                """async () => {
                    const label = document.createElement('p');
                    const fakeFetch = () => Promise.resolve({ ok: false, status: 500 });
                    await window.mcmaDashboard.updateReadinessDisplay(fakeFetch, label, 'job-1');
                    return label.textContent;
                }"""
            )
        )

    text = run_async(_run())
    assert "ready" not in text.lower()
    assert "500" in text
