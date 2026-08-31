"""
Pilot-integration correction (section 3) -- a fast, LOCAL (non-egress)
proof of mcma.execution.runner's DRY_RUN composition using hand-written
fake Playwright objects (no real browser, no real network) -- the same
convention tests/portal/capabilities/capabilities_test_support.py and
tests/portal/writer/writer_test_support.py already establish. This
exercises the runner's OWN wiring (real SQLite, real vault-backed
session, real account lease, real run_dry_run_planning/
run_dry_run_identity_check composition) end-to-end without requiring the
loopback-only isolated-CI mechanism test_runner_live_chromium_proof.py
needs -- it runs in every local/CI pass, `-m "not egress_proof"` included.
"""

from mcma.execution.browser_handoff import ActiveReviewRegistry
from mcma.execution.runner import RunnerConfig, process_one_queued_dry_run, process_queued_dry_run_jobs
from mcma.persistence.leases import acquire_lease
from runner_test_support import (
    ALLOWED_HOST,
    INSTANCE_ID,
    MCMA_OUJDA_ACCOUNT_ID,
    MODE_NORMAL_TYPED_INPUT,
    conn,  # noqa: F401
    crypto_backend,  # noqa: F401
    encryptor,  # noqa: F401
    run_async,
    seed_mcma_oujda_session,
    vault_dir,  # noqa: F401
)
from test_runner_live_chromium_proof import _enqueue_dry_run

_MODE_NORMAL_SEARCH_RESULT = {
    "data": [
        {"IdMission": 612001, "Matricule": "77001-C-3", "ReferenceMission": "R-1", "Societaire": "S-1"},
    ]
}
_MATCHING_IDENTITY = {"registration": "77001-C-3", "id_sinistre": "699001"}
_MISMATCHED_IDENTITY = {"registration": "99999-Z-99", "id_sinistre": "000000"}


class FakePage:
    def __init__(self, evaluate_results):
        self.goto_calls = []
        self.evaluate_calls = []
        self._evaluate_results = list(evaluate_results)

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    async def evaluate(self, script, arg=None):
        self.evaluate_calls.append((script, arg))
        return self._evaluate_results.pop(0)


class FakeContext:
    def __init__(self, evaluate_results):
        self._evaluate_results = evaluate_results
        self.route_calls = []
        self.ws_route_calls = []
        self.closed_count = 0
        self.pages_created = []

    async def route(self, pattern, handler):
        self.route_calls.append((pattern, handler))

    async def route_web_socket(self, pattern, handler):
        self.ws_route_calls.append((pattern, handler))

    async def new_page(self):
        page = FakePage(self._evaluate_results)
        self.pages_created.append(page)
        return page

    async def close(self, **kwargs):
        self.closed_count += 1


class FakeBrowser:
    def __init__(self, evaluate_results):
        self._evaluate_results = evaluate_results
        self.contexts_created = []

    async def new_context(self, **options):
        context = FakeContext(self._evaluate_results)
        self.contexts_created.append(context)
        return context


def _cfg(vault_dir, crypto_backend) -> RunnerConfig:
    return RunnerConfig(
        instance_id=INSTANCE_ID,
        allowed_host=ALLOWED_HOST,
        vault_dir=vault_dir,
        crypto_backend=crypto_backend,
        active_review_registry=ActiveReviewRegistry(),
    )


def test_dry_run_reaches_dry_run_verified_with_a_matching_fake_identity(conn, vault_dir, crypto_backend, encryptor):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _enqueue_dry_run(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="fake-normal-1")
    browser = FakeBrowser([_MODE_NORMAL_SEARCH_RESULT, _MATCHING_IDENTITY])
    cfg = _cfg(vault_dir, crypto_backend)

    status = run_async(_run(job_id, browser, cfg, conn, encryptor))
    assert status == "DRY_RUN_VERIFIED"
    assert browser.contexts_created[0].closed_count == 1  # the reader closes its own context
    # The lease must not outlive a successful check -- free again right away.
    lease = acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance")
    lease.release()


def test_dry_run_fails_closed_to_identity_failed_on_a_fake_mismatch(conn, vault_dir, crypto_backend, encryptor):
    """Negative control paired with the positive control above in the
    same guarded setup -- only the observed identity differs."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _enqueue_dry_run(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="fake-mismatch-1")
    browser = FakeBrowser([_MODE_NORMAL_SEARCH_RESULT, _MISMATCHED_IDENTITY])
    cfg = _cfg(vault_dir, crypto_backend)

    status = run_async(_run(job_id, browser, cfg, conn, encryptor))
    assert status == "IDENTITY_FAILED"
    lease = acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance")
    lease.release()


def test_dry_run_fails_closed_when_search_finds_zero_candidates(conn, vault_dir, crypto_backend, encryptor):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _enqueue_dry_run(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="fake-zero-1")
    browser = FakeBrowser([{"data": []}])
    cfg = _cfg(vault_dir, crypto_backend)

    status = run_async(_run(job_id, browser, cfg, conn, encryptor))
    assert status == "IDENTITY_FAILED"


def test_process_queued_dry_run_jobs_drains_the_queue_via_fakes(conn, vault_dir, crypto_backend, encryptor):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    _enqueue_dry_run(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="fake-drain-1")
    browser = FakeBrowser([_MODE_NORMAL_SEARCH_RESULT, _MATCHING_IDENTITY])
    cfg = _cfg(vault_dir, crypto_backend)

    outcomes = run_async(process_queued_dry_run_jobs(conn, browser=browser, cfg=cfg, encryptor=encryptor))
    assert outcomes == ("DRY_RUN_VERIFIED",)
    assert run_async(process_queued_dry_run_jobs(conn, browser=browser, cfg=cfg, encryptor=encryptor)) == ()


async def _run(job_id, browser, cfg, conn, encryptor):
    return await process_one_queued_dry_run(conn, job_id, browser=browser, cfg=cfg, encryptor=encryptor)
