"""mcma.portal.workstation_execute -- Phase 1C-C Pass 2A. Unit-level: a
fake writer/browser stand in for the real Playwright objects, and
mcma.portal.workstation_execute.open_verified_writer/launch_browser are
monkeypatched so this file never launches a real browser or contacts any
portal (real or mock). See test_writer_*_live_chromium_proof.py under
tests/portal/writer/ for the reviewed loopback-Chromium proof that
VerifiedMissionWriter's own construction/mutation behavior is genuine --
this file is about mcma.portal.workstation_execute's OWN orchestration
(headless config, permit threading, phase/review-callback ordering,
Mode Normal gating, fail-closed cleanup), not about re-proving writer.py
itself."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import List

import pytest

import mcma.portal.workstation_execute as workstation_execute
from mcma.core.money import Money
from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.identity import IdentityMismatch
from mcma.portal.writer import PortalRowIntent, RowAmbiguous, UnmatchedRubrique, WriterPlanData, WriteAborted


class FakeWriter:
    """Narrow stand-in for VerifiedMissionWriter -- only the methods
    _perform_writes/_verify_writes/PortalReviewSession actually call."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: List[str] = []
        self._fail_on = fail_on
        self._closed = False
        self._close_callback = None

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if self._fail_on == name:
            raise WriteAborted(f"{name} aborted")

    async def add_normal_row(self, rubrique_id):
        self._record("add_normal_row")

    async def edit_conventionne_row(self, rubrique_id):
        self._record("edit_conventionne_row")

    async def fill_form_fields(self):
        self._record("fill_form_fields")

    async def trigger_native_recalc(self):
        self._record("trigger_native_recalc")

    async def verify_row(self, rubrique_id):
        self._record("verify_row")

    async def verify_form_fields(self):
        self._record("verify_form_fields")

    async def verify_financial_summary(self):
        self._record("verify_financial_summary")

    async def close(self):
        self.calls.append("close")
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    def register_close_callback(self, on_close) -> None:
        self._close_callback = on_close

    def simulate_employee_close(self) -> None:
        assert self._close_callback is not None, "no callback registered yet"
        self._close_callback()


class FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _row_intents(n: int = 1):
    return tuple(
        PortalRowIntent(
            rubrique_id=RubriqueId(str(100 + i)),
            ht=Money(Decimal("10.00")), tva=Money(Decimal("2.00")), vetuste=Money(Decimal("0.00")),
        )
        for i in range(n)
    )


def _writer_plan(workflow: RepairWorkflow = RepairWorkflow.GARAGE_CONVENTIONNE, n_rows: int = 1) -> WriterPlanData:
    return WriterPlanData(repair_workflow=workflow, row_intents=_row_intents(n_rows), form_field_intents=())


def _patch_launch_browser(monkeypatch, browser: FakeBrowser, *, captured_headless: dict):
    @asynccontextmanager
    async def _fake_launch_browser(*, headless: bool = False):
        captured_headless["value"] = headless
        try:
            yield browser
        finally:
            await browser.close()

    monkeypatch.setattr(workstation_execute, "launch_browser", _fake_launch_browser)


def _patch_open_verified_writer(monkeypatch, result):
    """`result` is either a FakeWriter instance to return, or an
    exception instance/class to raise."""

    async def _fake_open_verified_writer(browser, permit, expected_identity, writer_plan, identifiers, contracts, allowed_host, *, writer_account, context_options=None):
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, type) and issubclass(result, BaseException):
            raise result("simulated construction failure")
        return result

    monkeypatch.setattr(workstation_execute, "open_verified_writer", _fake_open_verified_writer)


class FakePermit:
    def __init__(self) -> None:
        self.account_id = "acct-mcma-oujda"

    async def assert_valid(self) -> None:
        return None


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# Visible browser configuration (requirement I / test list item 2)
# --------------------------------------------------------------------- #


def test_the_browser_is_launched_headless_false(monkeypatch):
    writer = FakeWriter()
    browser = FakeBrowser()
    captured: dict = {}
    _patch_launch_browser(monkeypatch, browser, captured_headless=captured)
    _patch_open_verified_writer(monkeypatch, writer)

    async def _on_ready():
        writer.simulate_employee_close()

    async def _go():
        return await workstation_execute.run_workstation_execute_write(
            {"cookies": [], "origins": []},
            expected_identity=None,
            writer_plan=_writer_plan(),
            identifiers=None,
            contracts=(),
            allowed_host="127.0.0.1:8080",
            writer_account=None,
            permit=FakePermit(),
            on_ready_for_review=_on_ready,
        )

    result = _run(_go())
    assert result == "READY_FOR_HUMAN_REVIEW"
    assert captured["value"] is False


# --------------------------------------------------------------------- #
# DPAPI session passthrough (requirement I / test list item 3)
# --------------------------------------------------------------------- #


def test_the_exact_storage_state_given_is_passed_to_open_verified_writer(monkeypatch):
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    seen = {}

    async def _fake_open(browser_, permit, expected_identity, writer_plan, identifiers, contracts, allowed_host, *, writer_account, context_options=None):
        seen["context_options"] = context_options
        return writer

    monkeypatch.setattr(workstation_execute, "open_verified_writer", _fake_open)
    storage_state = {"cookies": [{"name": "sess", "value": "MARKER"}], "origins": []}

    async def _on_ready():
        writer.simulate_employee_close()

    _run(workstation_execute.run_workstation_execute_write(
        storage_state, expected_identity=None, writer_plan=_writer_plan(), identifiers=None, contracts=(),
        allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(), on_ready_for_review=_on_ready,
    ))
    assert seen["context_options"] == {"storage_state": storage_state}
    assert seen["context_options"]["storage_state"] is storage_state


# --------------------------------------------------------------------- #
# Wrong identity/workflow/row-matching fails before mutation
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("exc", [IdentityMismatch("plate mismatch"), RowAmbiguous("no match"), UnmatchedRubrique("999")])
def test_identity_or_row_matching_failure_never_mutates_and_reports_identity_failed(monkeypatch, exc):
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, exc)

    async def _never_ready():
        raise AssertionError("on_ready_for_review must never be called")

    result = _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None, writer_plan=_writer_plan(), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_never_ready,
    ))
    assert result == "IDENTITY_FAILED"
    assert browser.closed is True  # launch_browser's own async-with always closes it


# --------------------------------------------------------------------- #
# WriteAborted during writing/verifying fails closed, closes the writer
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("fail_on", ["edit_conventionne_row", "fill_form_fields", "trigger_native_recalc", "verify_row", "verify_financial_summary"])
def test_write_aborted_at_any_step_fails_closed_and_closes_the_writer(monkeypatch, fail_on):
    writer = FakeWriter(fail_on=fail_on)
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)

    async def _never_ready():
        raise AssertionError("on_ready_for_review must never be called once a write step has aborted")

    result = _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None, writer_plan=_writer_plan(), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_never_ready,
    ))
    assert result == "WRITE_ABORTED"
    assert "close" in writer.calls


def test_employee_closing_the_browser_during_writing_fails_closed(monkeypatch):
    """The employee closes the visible browser WHILE rows are still being
    written -- detected via the SAME close tracker used for human review,
    even though the write step itself may not raise WriteAborted."""
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)

    # Close the browser as a side effect of the FIRST mutation -- proves
    # the check runs even when the mutating call itself succeeds. The
    # default plan is GARAGE_CONVENTIONNE, which mutates via
    # edit_conventionne_row (never add_normal_row).
    original_edit = writer.edit_conventionne_row

    async def _edit_then_close(rubrique_id):
        await original_edit(rubrique_id)
        writer.simulate_employee_close()

    writer.edit_conventionne_row = _edit_then_close

    async def _never_ready():
        raise AssertionError("on_ready_for_review must never be called after an early browser close")

    result = _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None,
        writer_plan=_writer_plan(RepairWorkflow.GARAGE_CONVENTIONNE), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_never_ready,
    ))
    assert result == "WRITE_ABORTED"


# --------------------------------------------------------------------- #
# Successful write reports finish BEFORE waiting for browser close
# --------------------------------------------------------------------- #


def test_on_ready_for_review_is_awaited_before_waiting_for_the_browser_to_close(monkeypatch):
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)
    order = []

    async def _on_ready():
        order.append("on_ready_for_review")
        # The browser is NOT yet closed at this point -- proves this
        # callback runs before the wait, not after.
        assert writer._closed is False
        writer.simulate_employee_close()
        order.append("browser_closed_signalled")

    result = _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None, writer_plan=_writer_plan(), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_on_ready,
    ))
    assert result == "READY_FOR_HUMAN_REVIEW"
    assert order == ["on_ready_for_review", "browser_closed_signalled"]
    assert "close" in writer.calls  # writer closed on the way out, after review


def test_phase_callback_reports_writing_then_verifying_in_order(monkeypatch):
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)
    phases = []

    async def _on_ready():
        writer.simulate_employee_close()

    _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None, writer_plan=_writer_plan(), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_on_ready, on_phase=phases.append,
    ))
    assert phases == [workstation_execute.PHASE_WRITING, workstation_execute.PHASE_VERIFYING]


# --------------------------------------------------------------------- #
# Mode Normal production blocking (requirement H / test list item)
# --------------------------------------------------------------------- #


def test_mode_normal_is_blocked_before_its_first_mutation_by_default(monkeypatch):
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)

    async def _never_ready():
        raise AssertionError("on_ready_for_review must never be called for a blocked Mode Normal write")

    result = _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None,
        writer_plan=_writer_plan(RepairWorkflow.MODE_NORMAL), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_never_ready,
    ))
    assert result == "WRITE_ABORTED"
    assert writer.calls == ["close"]  # never add_normal_row -- refused before the first mutation
    assert workstation_execute.MODE_NORMAL_NATIVE_CALCULATION_CONFIRMED is False  # the fixed, non-overridden default


def test_mode_normal_can_be_exercised_with_an_explicit_test_only_override(monkeypatch):
    """Requirement H: loopback/mock tests may still exercise Mode Normal's
    existing add-row behavior via the explicit override -- never a
    default any composition root uses."""
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)

    async def _on_ready():
        writer.simulate_employee_close()

    result = _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None,
        writer_plan=_writer_plan(RepairWorkflow.MODE_NORMAL), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_on_ready, mode_normal_native_calculation_confirmed=True,
    ))
    assert result == "READY_FOR_HUMAN_REVIEW"
    assert "add_normal_row" in writer.calls
    assert "trigger_native_recalc" not in writer.calls  # never for Mode Normal, confirmed or not


def test_garage_conventionne_triggers_native_recalc_and_verifies_the_summary(monkeypatch):
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)

    async def _on_ready():
        writer.simulate_employee_close()

    _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None,
        writer_plan=_writer_plan(RepairWorkflow.GARAGE_CONVENTIONNE), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_on_ready,
    ))
    assert writer.calls == [
        "edit_conventionne_row", "fill_form_fields", "trigger_native_recalc",
        "verify_row", "verify_form_fields", "verify_financial_summary", "close",
    ]


# --------------------------------------------------------------------- #
# Never a wider writer surface than the fixed golden operations
# --------------------------------------------------------------------- #


def test_only_the_fixed_golden_operations_are_ever_called_never_a_final_action(monkeypatch):
    writer = FakeWriter()
    browser = FakeBrowser()
    _patch_launch_browser(monkeypatch, browser, captured_headless={})
    _patch_open_verified_writer(monkeypatch, writer)

    async def _on_ready():
        writer.simulate_employee_close()

    _run(workstation_execute.run_workstation_execute_write(
        {"cookies": [], "origins": []}, expected_identity=None,
        writer_plan=_writer_plan(RepairWorkflow.GARAGE_CONVENTIONNE), identifiers=None,
        contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
        on_ready_for_review=_on_ready,
    ))
    allowed = {
        "edit_conventionne_row", "add_normal_row", "fill_form_fields", "trigger_native_recalc",
        "verify_row", "verify_form_fields", "verify_financial_summary", "close",
    }
    assert set(writer.calls) <= allowed


# --------------------------------------------------------------------- #
# Shutdown (task cancellation) closes the writer/browser
# --------------------------------------------------------------------- #


def test_cancelling_the_task_during_review_wait_closes_the_writer():
    """Requirement F: application shutdown (modelled here as cancelling
    the asyncio task this coroutine runs on, exactly as job_worker.py's
    own _run_execute_lifecycle does) closes the writer -- via
    run_workstation_execute_write's own finally block -- even though the
    employee never closed the browser themselves."""
    writer = FakeWriter()
    browser = FakeBrowser()

    async def _go():
        import mcma.portal.workstation_execute as we

        @asynccontextmanager
        async def _fake_launch_browser(*, headless: bool = False):
            try:
                yield browser
            finally:
                await browser.close()

        async def _fake_open(*a, **kw):
            return writer

        we.launch_browser = _fake_launch_browser
        we.open_verified_writer = _fake_open

        reached_review = asyncio.Event()

        async def _on_ready():
            reached_review.set()

        task = asyncio.ensure_future(we.run_workstation_execute_write(
            {"cookies": [], "origins": []}, expected_identity=None, writer_plan=_writer_plan(), identifiers=None,
            contracts=(), allowed_host="127.0.0.1:8080", writer_account=None, permit=FakePermit(),
            on_ready_for_review=_on_ready,
        ))
        # Let the task run all the way to (and past) on_ready_for_review
        # and into review.wait_until_closed() -- the FIRST await that
        # genuinely suspends (the employee never closes the browser in
        # this test) -- before cancelling it.
        await reached_review.wait()
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert writer.is_closed is True

    _run(_go())
