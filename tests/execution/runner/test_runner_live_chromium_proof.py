"""
Pilot-integration correction (sections 3/4) -- real-Chromium proof for
mcma.execution.runner: the actual composition of mcma.execution.jobs's
DRY_RUN/EXECUTE state machines with genuine mcma.portal/mcma.persistence
wiring (real account lease, real vault-backed session load, real
ReadCapability/VerifiedMissionWriter against the loopback mock).

DOM-level writer behavior (row fill, read-back, native recalc) is already
exhaustively proven by tests/portal/writer/*_live_chromium_proof.py --
these tests instead prove the RUNNER's own composition: real lease
acquire/release lifecycle, real job-state transitions driven by real
portal calls (not injected stubs), and ActiveReviewRegistry registration/
browser-close handoff. Every negative guard here is paired with a
positive control in the SAME guarded context (mismatched identity vs. a
fresh matching one; a second concurrent lease attempt vs. the same
account free again after release).
"""

import pytest

from mcma.execution.browser_handoff import ActiveReviewRegistry
from mcma.execution.jobs import (
    confirm_review_completed,
    enqueue_dry_run,
    enqueue_execute,
    run_execute_planning,
)
from mcma.execution.runner import (
    RunnerConfig,
    _rebuild_plan,
    process_one_planned_execute,
    process_one_queued_dry_run,
    process_queued_dry_run_jobs,
)
from mcma.persistence.leases import LeaseNotHeld, acquire_lease
from mcma.persistence.repositories.jobs import AutomationJobsRepository
from runner_test_support import (
    ALLOWED_HOST,
    INSTANCE_ID,
    MCMA_OUJDA_ACCOUNT_ID,
    MODE_NORMAL_TYPED_INPUT,
    PEC_TYPED_INPUT,
    conn,  # noqa: F401
    crypto_backend,  # noqa: F401
    encryptor,  # noqa: F401
    live_mock_server,  # noqa: F401
    run_async,
    seed_mcma_oujda_session,
    vault_dir,  # noqa: F401
)

pytestmark = [pytest.mark.egress_proof, pytest.mark.requires_egress_isolation]


def _cfg(vault_dir, crypto_backend) -> RunnerConfig:
    return RunnerConfig(
        instance_id=INSTANCE_ID,
        allowed_host=ALLOWED_HOST,
        vault_dir=vault_dir,
        crypto_backend=crypto_backend,
        active_review_registry=ActiveReviewRegistry(),
    )


def _enqueue_dry_run(conn, encryptor, *, typed_input, key, account_id=MCMA_OUJDA_ACCOUNT_ID):
    import json

    from mcma.execution.inputs import compute_content_hash
    from mcma.mapping.wexia import parse_wexia
    from mcma.planning.plan import detect_workflow
    from mcma.planning.registry import workflow_name_for

    parsed = parse_wexia(typed_input)
    workflow_name = workflow_name_for(detect_workflow(parsed))
    typed_input_bytes = json.dumps(typed_input, sort_keys=True).encode("utf-8")
    return enqueue_dry_run(
        conn,
        account_id=account_id,
        requested_by_user_id="operator-1",
        workflow_name=workflow_name,
        input_hash=compute_content_hash(typed_input_bytes),
        typed_input_bytes=typed_input_bytes,
        idempotency_key=key,
        encryptor=encryptor,
    )


def test_dry_run_reaches_dry_run_verified_via_a_real_read_only_identity_check(
    conn, vault_dir, crypto_backend, encryptor, live_mock_server
):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    job_id = _enqueue_dry_run(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="normal-1")
    cfg = _cfg(vault_dir, crypto_backend)

    async def _run():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                return await process_one_queued_dry_run(conn, job_id, browser=browser, cfg=cfg, encryptor=encryptor)
            finally:
                await browser.close()

    status = run_async(_run())
    assert status == "DRY_RUN_VERIFIED"
    assert AutomationJobsRepository(conn).get(job_id)["status"] == "DRY_RUN_VERIFIED"
    # The lease must not outlive a successful read-only check.
    lease = acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance")
    lease.release()


def test_dry_run_fails_closed_to_identity_failed_on_a_genuine_mismatch(
    conn, vault_dir, crypto_backend, encryptor, live_mock_server
):
    """Negative control paired with the positive control above in the
    SAME guarded context: the PEC mission's real matricule does not match
    a Mode-Normal-shaped typed_input's registration once the plan expects
    a DIFFERENT plate than what the search will actually find scoped to
    it -- here we simulate this the direct way the state machine itself
    is built to handle: a registration with no matching candidate at all."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    mismatched = dict(MODE_NORMAL_TYPED_INPUT)
    mismatched["vehicule"] = {"license_plate": "00000-Z-00"}  # no such mission on the mock
    job_id = _enqueue_dry_run(conn, encryptor, typed_input=mismatched, key="mismatch-1")
    cfg = _cfg(vault_dir, crypto_backend)

    async def _run():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                return await process_one_queued_dry_run(conn, job_id, browser=browser, cfg=cfg, encryptor=encryptor)
            finally:
                await browser.close()

    status = run_async(_run())
    assert status == "IDENTITY_FAILED"
    lease = acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance")
    lease.release()


def test_process_queued_dry_run_jobs_discovers_and_drains_every_queued_job(
    conn, vault_dir, crypto_backend, encryptor, live_mock_server
):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    _enqueue_dry_run(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="drain-1")
    _enqueue_dry_run(conn, encryptor, typed_input=PEC_TYPED_INPUT, key="drain-2")
    cfg = _cfg(vault_dir, crypto_backend)

    async def _run():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                return await process_queued_dry_run_jobs(conn, browser=browser, cfg=cfg, encryptor=encryptor)
            finally:
                await browser.close()

    outcomes = run_async(_run())
    assert outcomes == ("DRY_RUN_VERIFIED", "DRY_RUN_VERIFIED")
    # Draining twice more finds nothing left QUEUED -- never reprocesses.
    assert run_async(_run()) == ()


def _execute_job_planned(conn, encryptor, *, typed_input, key, account_id=MCMA_OUJDA_ACCOUNT_ID):
    dry_run_job_id = _enqueue_dry_run(
        conn, encryptor, typed_input=typed_input, key=f"{key}-dry", account_id=account_id
    )
    # DRY_RUN_VERIFIED is required before an EXECUTE may reference it as
    # parent -- set directly here (the identity gate itself is proven by
    # the DRY_RUN tests above; this focuses on EXECUTE's own wiring).
    from mcma.execution.jobs import transition

    transition(conn, dry_run_job_id, "PLANNING")
    parent_row = AutomationJobsRepository(conn).get(dry_run_job_id)
    plan = _rebuild_plan(conn, parent_row, encryptor)
    transition(conn, dry_run_job_id, "DRY_RUN_VERIFIED", plan_hash=plan.provenance.plan_hash)

    parent = AutomationJobsRepository(conn).get(dry_run_job_id)
    execute_job_id = enqueue_execute(
        conn,
        account_id=account_id,
        requested_by_user_id="operator-1",
        workflow_name=parent["workflow_name"],
        input_hash=parent["input_hash"],
        typed_input_bytes=parent_row_bytes(conn, dry_run_job_id, encryptor),
        idempotency_key=f"{key}-exec",
        encryptor=encryptor,
        parent_job_id=dry_run_job_id,
        authorized_by_user_id="operator-1",
    )

    def _rebuild():
        row = AutomationJobsRepository(conn).get(execute_job_id)
        return _rebuild_plan(conn, row, encryptor)

    run_execute_planning(conn, execute_job_id, rebuild_plan_from_retained_input=_rebuild)
    return execute_job_id


def parent_row_bytes(conn, job_id, encryptor):
    from mcma.execution.inputs import retrieve_and_verify_job_input

    row = AutomationJobsRepository(conn).get(job_id)
    return retrieve_and_verify_job_input(conn, job_id, row["input_hash"], encryptor)


def test_execute_reaches_ready_for_human_review_and_registers_with_the_review_registry(
    conn, vault_dir, crypto_backend, encryptor, live_mock_server
):
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    execute_job_id = _execute_job_planned(conn, encryptor, typed_input=MODE_NORMAL_TYPED_INPUT, key="exec-normal")
    cfg = _cfg(vault_dir, crypto_backend)

    async def _run():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                status = await process_one_planned_execute(conn, execute_job_id, browser=browser, cfg=cfg, encryptor=encryptor)
                assert status == "READY_FOR_HUMAN_REVIEW"
                assert AutomationJobsRepository(conn).get(execute_job_id)["status"] == "READY_FOR_HUMAN_REVIEW"

                # Section 4: the lease is held (a second job cannot use the account).
                assert cfg.active_review_registry.is_account_active(MCMA_OUJDA_ACCOUNT_ID)
                with pytest.raises(LeaseNotHeld):
                    acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance")
            finally:
                await browser.close()

    run_async(_run())


def test_browser_close_after_ready_awaits_confirmation_and_keeps_the_lease_held(
    conn, vault_dir, crypto_backend, encryptor, live_mock_server
):
    """Pilot-runner correction (requirement 5): closing the review window
    is NOT the end of the handoff. This test previously asserted the
    opposite -- that the lease was free again the instant the employee
    closed the browser -- because the runner's own _on_close called
    lease.release() unconditionally after transition_on_browser_closed,
    overriding that function's documented contract ("deliberately NOT on
    the AWAITING_HUMAN_CONFIRMATION path -- it stays held until
    confirm_review_completed/report_review_problem so no second job can
    concurrently use the same shared portal account while a human is
    still mid-review"). Releasing at close reopens exactly the window
    section 4 exists to prevent: the employee has closed the window but
    has not yet confirmed, and a second job could take the account while
    the first job's outcome is still unrecorded. The lease is now
    surrendered only by the explicit human action."""
    seed_mcma_oujda_session(conn, vault_dir, crypto_backend)
    execute_job_id = _execute_job_planned(conn, encryptor, typed_input=PEC_TYPED_INPUT, key="exec-pec")
    cfg = _cfg(vault_dir, crypto_backend)

    async def _run():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                status = await process_one_planned_execute(conn, execute_job_id, browser=browser, cfg=cfg, encryptor=encryptor)
                assert status == "READY_FOR_HUMAN_REVIEW"
                handle = cfg.active_review_registry.get(execute_job_id)
                # The employee closes their own visible browser -- the
                # application itself never initiates this close.
                await handle._context.close()
            finally:
                await browser.close()

    run_async(_run())
    assert AutomationJobsRepository(conn).get(execute_job_id)["status"] == "AWAITING_HUMAN_CONFIRMATION"
    # The review session itself is over -- the window is gone.
    assert not cfg.active_review_registry.is_account_active(MCMA_OUJDA_ACCOUNT_ID)
    # But the account is still this job's until a human says otherwise.
    with pytest.raises(LeaseNotHeld):
        acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance")

    # Positive control: the explicit human action IS what frees it.
    assert confirm_review_completed(
        conn, execute_job_id, confirmed_by_user_id="operator-1"
    ) == "HUMAN_CONFIRMED_COMPLETE"
    freed = acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, "another-instance")
    freed.release()
