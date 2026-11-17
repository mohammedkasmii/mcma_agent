"""
mcma.portal.mode_normal_canary -- the supervised Mode Normal golden canary
(docs/implementation/execution/MODE_NORMAL_GOLDEN_CANARY.md).

A SEPARATE production adapter. The generic VerifiedMissionWriter
(mcma.portal.writer) keeps every one of its loopback/mock protections
untouched -- _require_loopback_host, http-only URLs, frozen route
contracts -- and remains the path every other EXECUTE uses. This module
is reachable only when the central server's opt-in
(Settings.mode_normal_golden_canary_enabled) has dispatched an EXECUTE
envelope carrying the MODE_NORMAL_GOLDEN_CANARY execution profile.

What it reuses, unchanged:
  - navigation & identity: mcma.portal.capabilities.ReadCapability's
    production search()/open()/observe_identity() (the DRY_RUN path), with
    this module's network policy standing in as its structural
    mission-authorization controller; mcma.portal.identity.verify_identity;
    mcma.portal.mission.detect_observed_workflow/require_workflow_agreement;
  - DOM mechanics: mcma.portal.mode_normal_live.ModeNormalLiveDriver's
    golden primitives, called in the golden order of add_rubrique_row()
    (#VehRepareI -> Ajouter -> #IdRubrique/#MontantHT/#Taxe with the event
    cascade -> column-7 checkmark), but with EVERY primitive's result
    checked -- the golden composite discards them, which a supervised
    production canary cannot;
  - native calculation: the golden TRIGGER_CALCULATIONS_JS, after a
    read-only presence probe of the four golden functions;
  - rendered-table read-back: writer._READ_NORMAL_ROWS_JS.

What it never does: click Valider/Cloture/Enregistrer/GED (absent by
construction, and the final endpoints are denied by the network policy at
every moment); write #MontantChargeMutuelle/#MontantChargeSocietaire (only
read); call any endpoint itself (no fetch/XHR is issued by this module --
the only requests in a row window are the portal's own, fired by its own
checkmark handler).

Outcomes: READY_FOR_HUMAN_REVIEW only when every planned row reads back
exactly once with exact HT/TVA, every planned header field reads back,
the native calculation ran, and two independent summary reads both
reconcile TVA and TTC with the approved plan. Every other path is
WRITE_ABORTED (or IDENTITY_FAILED before any mutation). After an abort
past the mission page, the visible browser is HELD (network fully denied,
no further automation) until the employee closes it or the hold timeout
expires, so the state can be reviewed.
"""

from __future__ import annotations

import asyncio
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Awaitable, Callable, Optional

from mcma.domain.enums import RepairWorkflow
from mcma.domain.normalize import normalize_text
from mcma.domain.rubriques import MODE_NORMAL_TVA_RATES, RUBRIQUE_CATALOG
from mcma.portal.browser import launch_browser
from mcma.portal.canary_network import ModeNormalCanaryNetworkPolicy, install_canary_guard
from mcma.portal.capabilities import LeaseHandle, ReadCapability, SearchIdentifiers, portal_origin
from mcma.portal.identity import ExpectedIdentity, verify_identity
from mcma.portal.interception import hardened_context_options
from mcma.portal.mission import detect_observed_workflow, observe_identity, require_workflow_agreement
from mcma.portal.mode_normal_live import (
    ID_RUBRIQUE_SELECTOR,
    MONTANT_HT_SELECTOR,
    TAXE_SELECTOR,
    WAIT_BEFORE_CHECKMARK_MS,
    ModeNormalLiveDriver,
)
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST, identity_read_contracts
from mcma.portal.workstation_execute import (
    PHASE_VERIFYING,
    PHASE_WRITING,
    WRITE_OUTCOME_IDENTITY_FAILED,
    WRITE_OUTCOME_READY_FOR_HUMAN_REVIEW,
    WRITE_OUTCOME_WRITE_ABORTED,
)
from mcma.portal.workstation_sessions import WORKSTATION_ACCOUNT_IDS
from mcma.portal.writer import McmaWriterAccountContext, WriterPlanData
from mcma.portal.writer import _READ_NORMAL_ROWS_JS as READ_RENDERED_ROWS_JS

CANARY_ACCOUNT_IDS = frozenset(WORKSTATION_ACCOUNT_IDS)  # MCMA Oujda / MCMA Nador only
CANARY_RUBRIQUE_VALUES = frozenset(r.value for r in MODE_NORMAL_TVA_RATES)
ABORT_HOLD_SECONDS = 30 * 60
READBACK_ATTEMPTS = 8
READBACK_INTERVAL_MS = 500

GOLDEN_CALCULATION_FUNCTIONS = (
    "CalculerMontantDommage", "CalculerMntArrete", "CalculerMontantTTC", "CalculerMontantVetuste",
)
PROBE_CALCULATIONS_JS = (
    "(names) => names.filter((n) => typeof window[n] !== 'function')"
)
EDITING_ROW_COUNT_JS = (
    "() => ({ht: document.querySelectorAll('#MontantHT').length, "
    "rub: document.querySelectorAll('#IdRubrique').length})"
)
READ_EDITING_ROW_JS = """() => {
    const v = (sel) => { const el = document.querySelector(sel); return el ? el.value : null; };
    return {rubrique: v('#IdRubrique'), ht: v('#MontantHT'), taxe: v('#Taxe')};
}"""
READ_TOTALS_JS = """() => {
    const read = (sel) => { const el = document.querySelector(sel);
        return el ? (el.value !== undefined ? el.value : el.textContent) : null; };
    return {total_tva: read('#MontantTVA'), total_ttc: read('#MontantTTC')};
}"""
READ_FIELD_JS = "(sel) => { const el = document.querySelector(sel); return el ? el.value : null; }"
FIELD_TAG_JS = "(sel) => { const el = document.querySelector(sel); return el ? el.tagName.toLowerCase() : null; }"

OnReadyForReview = Callable[[], Awaitable[None]]
OnPhase = Callable[[str], None]
OnEvidence = Callable[[dict], None]


class CanaryAbort(Exception):
    """Internal: carries a FIXED reason code (never a dossier value)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _IdentityRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------- #
# Pure helpers (unit-tested directly)
# --------------------------------------------------------------------- #

_AMOUNT_SUFFIX = re.compile(r"(?i)\s*(mad|dhs|dh)\.?$")


def parse_portal_amount(raw: object) -> Optional[Decimal]:
    """Exact parse of an amount as the portal renders it ("5000.00",
    "5 000,00", "5.000,00", "5,000.00", "240", optional DH/MAD suffix).
    Anything ambiguous or unrecognized is None -- never a guess."""
    if raw is None:
        return None
    s = str(raw).replace(" ", " ").replace(" ", " ").strip()
    s = _AMOUNT_SUFFIX.sub("", s).replace(" ", "")
    if not s:
        return None
    try:
        if re.fullmatch(r"\d+", s):
            return Decimal(s)
        if re.fullmatch(r"\d+[.,]\d{1,2}", s):
            return Decimal(s.replace(",", "."))
        if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{1,2}", s):
            return Decimal(s.replace(".", "").replace(",", "."))
        if re.fullmatch(r"\d{1,3}(,\d{3})+\.\d{1,2}", s):
            return Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None
    return None


def _catalog_rubrique_of(cell: object) -> Optional[str]:
    """Which catalog rubrique a rendered first-column cell denotes: its id,
    its catalog label, or "<id> <label>" / "<id> - <label>". None when it
    matches none or more than one."""
    text = normalize_text(str(cell or ""))
    if not text:
        return None
    matches = set()
    for value, label in RUBRIQUE_CATALOG.items():
        norm_label = normalize_text(label)
        if text in (value, norm_label, f"{value} {norm_label}"):
            matches.add(value)
    return next(iter(matches)) if len(matches) == 1 else None


def classify_table(rows: object, writer_plan: WriterPlanData) -> dict:
    """Validates EVERY saved row currently rendered against the approved
    plan and returns {rubrique_value: row} for those present. Raises
    CanaryAbort on: unrecognized/unplanned rubrique, a duplicate rubrique,
    or a planned rubrique whose rendered HT/TVA differs from the plan."""
    if not isinstance(rows, list):
        raise CanaryAbort("ROWS_UNREADABLE")
    present: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CanaryAbort("ROWS_UNREADABLE")
        rubrique = _catalog_rubrique_of(row.get("rubrique_cell"))
        if rubrique is None:
            raise CanaryAbort("UNRECOGNIZED_EXISTING_ROW")
        intent = next((i for i in writer_plan.row_intents if i.rubrique_id.value == rubrique), None)
        if intent is None:
            raise CanaryAbort("UNEXPECTED_EXISTING_ROW")
        if rubrique in present:
            raise CanaryAbort("DUPLICATE_RUBRIQUE_ROW")
        ht = parse_portal_amount(row.get("MontantHT"))
        tva = parse_portal_amount(row.get("Taxe"))
        if ht is None or tva is None or ht != intent.ht.amount or tva != intent.tva.amount:
            raise CanaryAbort("EXISTING_ROW_MISMATCH")
        present[rubrique] = row
    return present


def canary_precondition_refusal(
    writer_plan: object, writer_account: object, permit: object, host: str,
) -> Optional[str]:
    """Portal-layer re-check of the canary preconditions, BEFORE any browser
    exists (the API, the dispatcher and the runner composition each already
    checked their own share). A fixed reason code, or None."""
    if host != DEFAULT_SINAUTO_HOST:
        return "HOST_NOT_PINNED"
    if not isinstance(writer_plan, WriterPlanData):
        return "PLAN_TYPE"
    if writer_plan.repair_workflow is not RepairWorkflow.MODE_NORMAL:
        return "WORKFLOW_NOT_MODE_NORMAL"
    if not writer_plan.row_intents:
        return "PLAN_EMPTY"
    for intent in writer_plan.row_intents:
        if intent.rubrique_id.value not in CANARY_RUBRIQUE_VALUES:
            return "RUBRIQUE_OUTSIDE_TVA_PROFILE"
        if intent.ht.is_negative or intent.tva.is_negative or intent.ht.amount <= 0:
            return "ROW_AMOUNT_INVALID"
        rate = next(r for k, r in MODE_NORMAL_TVA_RATES.items() if k.value == intent.rubrique_id.value)
        if rate == 0 and intent.tva.amount != 0:
            return "ZERO_RATE_ROW_HAS_TVA"
        if rate > 0 and intent.tva.amount == 0:
            return "TAXABLE_ROW_HAS_NO_TVA"
    if not isinstance(writer_account, McmaWriterAccountContext):
        return "ACCOUNT_CONTEXT"
    if writer_account.account_id not in CANARY_ACCOUNT_IDS:
        return "ACCOUNT_NOT_MCMA_CANARY"
    if getattr(permit, "account_id", None) != writer_account.account_id:
        return "ACCOUNT_PERMIT_MISMATCH"
    return None


def _amount_equal(raw: object, expected: Decimal) -> bool:
    parsed = parse_portal_amount(raw)
    return parsed is not None and parsed == expected


# --------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------- #


class _Run:
    def __init__(self, page, driver, policy, permit, expected_identity, writer_plan, closed: asyncio.Event,
                 *, readback_attempts: int, readback_interval_ms: int):
        self.page = page
        self.driver = driver
        self.policy = policy
        self.permit = permit
        self.expected_identity = expected_identity
        self.plan = writer_plan
        self.closed = closed
        self.readback_attempts = readback_attempts
        self.readback_interval_ms = readback_interval_ms
        self.rows_written = 0
        self.mutated = False

    def guard(self) -> None:
        if self.closed.is_set():
            raise CanaryAbort("BROWSER_CLOSED")
        if self.policy.has_violation:
            raise CanaryAbort("NETWORK_VIOLATION")

    async def lease(self) -> None:
        try:
            await self.permit.assert_valid()
        except Exception:
            raise CanaryAbort("LEASE_INVALID") from None

    async def recheck_identity(self) -> None:
        try:
            verify_identity(self.expected_identity, await observe_identity(self.page))
            require_workflow_agreement(RepairWorkflow.MODE_NORMAL, await detect_observed_workflow(self.page))
        except Exception:
            raise CanaryAbort("IDENTITY_OR_WORKFLOW_CHANGED") from None

    async def evaluate(self, script, arg=None, *, reason: str):
        try:
            return await (self.page.evaluate(script) if arg is None else self.page.evaluate(script, arg))
        except Exception:
            raise CanaryAbort(reason) from None

    async def read_table(self) -> dict:
        return classify_table(await self.evaluate(READ_RENDERED_ROWS_JS, reason="ROWS_UNREADABLE"), self.plan)

    # -- one row ---------------------------------------------------------

    async def write_row(self, index: int, intent) -> None:
        rubrique = intent.rubrique_id.value
        await self.lease()
        self.guard()
        await self.recheck_identity()
        before = await self.read_table()
        if rubrique in before:
            return  # already present with exact amounts -- no mutation
        self.guard()

        # Golden order (ModeNormalLiveDriver.add_rubrique_row), every step checked.
        self.mutated = True
        if not await self.driver.ensure_vehicle_repairable():
            raise CanaryAbort("VEH_REPARE_UNAVAILABLE")
        await self.driver.click_ajouter()
        self.guard()
        counts = await self.evaluate(EDITING_ROW_COUNT_JS, reason="EDITING_ROW_UNREADABLE")
        if not isinstance(counts, dict) or counts.get("ht") != 1 or counts.get("rub") != 1:
            raise CanaryAbort("EDITING_ROW_NOT_UNIQUE")
        if not await self.driver.safe_select_option(ID_RUBRIQUE_SELECTOR, rubrique):
            raise CanaryAbort("RUBRIQUE_SELECT_FAILED")
        if not await self.driver.safe_fill_input(MONTANT_HT_SELECTOR, str(intent.ht.amount)):
            raise CanaryAbort("MONTANT_HT_FILL_FAILED")
        typed_tva = intent.tva.amount != 0  # golden guard: a zero tax is not typed
        if typed_tva and not await self.driver.safe_fill_input(TAXE_SELECTOR, str(intent.tva.amount)):
            raise CanaryAbort("TAXE_FILL_FAILED")
        await self.page.wait_for_timeout(WAIT_BEFORE_CHECKMARK_MS)
        self.guard()
        editing = await self.evaluate(READ_EDITING_ROW_JS, reason="EDITING_ROW_UNREADABLE")
        if not isinstance(editing, dict) or str(editing.get("rubrique") or "").strip() != rubrique:
            raise CanaryAbort("EDITING_RUBRIQUE_MISMATCH")
        if not _amount_equal(editing.get("ht"), intent.ht.amount):
            raise CanaryAbort("EDITING_HT_MISMATCH")
        taxe_raw = editing.get("taxe")
        if typed_tva:
            if not _amount_equal(taxe_raw, intent.tva.amount):
                raise CanaryAbort("EDITING_TAXE_MISMATCH")
        elif taxe_raw not in (None, "") and not _amount_equal(taxe_raw, Decimal("0")):
            raise CanaryAbort("EDITING_TAXE_MISMATCH")

        await self.lease()
        self.policy.open_row_window(index)
        try:
            await self.driver.click_row_checkmark()
            await self._await_exact_readback(intent, before)
        finally:
            self.policy.close_row_window()
        self.guard()
        self.rows_written += 1
        await self.lease()

    async def _await_exact_readback(self, intent, before: dict) -> None:
        rubrique = intent.rubrique_id.value
        for attempt in range(self.readback_attempts):
            self.guard()
            raw = await self.evaluate(READ_RENDERED_ROWS_JS, reason="ROWS_UNREADABLE")
            try:
                after = classify_table(raw, self.plan)
            except CanaryAbort as exc:
                if exc.reason in ("UNEXPECTED_EXISTING_ROW", "DUPLICATE_RUBRIQUE_ROW", "EXISTING_ROW_MISMATCH",
                                  "UNRECOGNIZED_EXISTING_ROW"):
                    raise CanaryAbort(f"READBACK_{exc.reason}") from None
                raise
            if rubrique in after:
                if set(after) != set(before) | {rubrique}:
                    raise CanaryAbort("READBACK_ROW_SET_CHANGED")
                counts = await self.evaluate(EDITING_ROW_COUNT_JS, reason="EDITING_ROW_UNREADABLE")
                if isinstance(counts, dict) and counts.get("ht") == 0 and counts.get("rub") == 0:
                    return
            if attempt + 1 < self.readback_attempts:
                await self.page.wait_for_timeout(self.readback_interval_ms)
        raise CanaryAbort("READBACK_ROW_NOT_PERSISTED")

    # -- header fields, calculation, summary -----------------------------

    async def fill_and_verify_fields(self) -> None:
        for intent in self.plan.form_field_intents:
            selector = f"#{intent.selector.value}"
            await self.lease()
            self.guard()
            count = await self.evaluate(f"() => document.querySelectorAll('{selector}').length", reason="FIELD_UNREADABLE")
            if count != 1:
                raise CanaryAbort("FIELD_NOT_UNIQUE")
            tag = await self.evaluate(FIELD_TAG_JS, selector, reason="FIELD_UNREADABLE")
            self.mutated = True
            if tag == "select":
                ok = await self.driver.safe_select_option(selector, intent.value)
            else:
                ok = await self.driver.safe_fill_input(selector, intent.value)
            if not ok:
                raise CanaryAbort("FIELD_FILL_FAILED")
            self.guard()
        for intent in self.plan.form_field_intents:
            selector = f"#{intent.selector.value}"
            observed = await self.evaluate(READ_FIELD_JS, selector, reason="FIELD_UNREADABLE")
            if observed == intent.value:
                continue
            expected_amount = parse_portal_amount(intent.value)
            if expected_amount is None or not _amount_equal(observed, expected_amount):
                raise CanaryAbort("FIELD_READBACK_MISMATCH")

    async def calculate_and_verify(self) -> None:
        await self.lease()
        self.guard()
        await self.recheck_identity()
        missing = await self.evaluate(PROBE_CALCULATIONS_JS, list(GOLDEN_CALCULATION_FUNCTIONS), reason="CALC_PROBE_FAILED")
        if not isinstance(missing, list) or missing:
            raise CanaryAbort("NATIVE_CALCULATION_MISSING")
        try:
            await self.driver.trigger_native_calculations()
        except Exception:
            raise CanaryAbort("NATIVE_CALCULATION_FAILED") from None
        self.guard()
        await self.page.wait_for_timeout(self.readback_interval_ms)

        expected_ht = sum((i.ht.amount for i in self.plan.row_intents), Decimal("0"))
        expected_tva = sum((i.tva.amount for i in self.plan.row_intents), Decimal("0"))
        expected_ttc = expected_ht + expected_tva
        first = await self.evaluate(READ_TOTALS_JS, reason="SUMMARY_UNREADABLE")
        self.guard()
        table = await self.read_table()
        if set(table) != {i.rubrique_id.value for i in self.plan.row_intents}:
            raise CanaryAbort("FINAL_ROW_SET_MISMATCH")
        second = await self.evaluate(READ_TOTALS_JS, reason="SUMMARY_UNREADABLE")
        for summary in (first, second):
            if not isinstance(summary, dict):
                raise CanaryAbort("SUMMARY_UNREADABLE")
            if not _amount_equal(summary.get("total_tva"), expected_tva):
                raise CanaryAbort("SUMMARY_TVA_MISMATCH")
            if not _amount_equal(summary.get("total_ttc"), expected_ttc):
                raise CanaryAbort("SUMMARY_TTC_MISMATCH")
        self.guard()
        await self.lease()


async def run_mode_normal_golden_canary(
    storage_state: dict,
    *,
    expected_identity: ExpectedIdentity,
    writer_plan: WriterPlanData,
    identifiers: SearchIdentifiers,
    writer_account: McmaWriterAccountContext,
    permit: LeaseHandle,
    on_ready_for_review: OnReadyForReview,
    on_phase: OnPhase = lambda phase: None,
    on_evidence: OnEvidence = lambda evidence: None,
    host: str = DEFAULT_SINAUTO_HOST,
    launcher=launch_browser,
    driver_factory=ModeNormalLiveDriver,
    abort_hold_seconds: float = ABORT_HOLD_SECONDS,
    readback_attempts: int = READBACK_ATTEMPTS,
    readback_interval_ms: int = READBACK_INTERVAL_MS,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Returns READY_FOR_HUMAN_REVIEW, IDENTITY_FAILED or WRITE_ABORTED (the
    executor's WRITER_ALLOWED_RESULTS). Does not return until the visible
    browser is closed (or, after an abort, the hold timeout elapses);
    cancellation closes it and propagates."""
    evidence: dict = {"outcome": None, "reason": None, "rows_written": 0, "records": []}

    def emit(outcome: str, reason: Optional[str], policy=None, run=None) -> None:
        evidence["outcome"] = outcome
        evidence["reason"] = reason
        evidence["rows_written"] = run.rows_written if run is not None else 0
        evidence["records"] = list(policy.evidence()) if policy is not None else []
        try:
            on_evidence(dict(evidence))
        except Exception:
            pass

    refusal = canary_precondition_refusal(writer_plan, writer_account, permit, host)
    if refusal is not None:
        emit(WRITE_OUTCOME_WRITE_ABORTED, f"PRECONDITION_{refusal}")
        return WRITE_OUTCOME_WRITE_ABORTED
    try:
        await permit.assert_valid()
    except Exception:
        emit(WRITE_OUTCOME_WRITE_ABORTED, "PRECONDITION_LEASE_INVALID")
        return WRITE_OUTCOME_WRITE_ABORTED

    search_contracts = identity_read_contracts(host)
    search_page_route = next(c.route for c in search_contracts if c.operation_type == "search_page")

    async with launcher(headless=False) as browser:
        policy = ModeNormalCanaryNetworkPolicy(search_contracts, host=host, clock=clock)
        context = await browser.new_context(
            **hardened_context_options({"storage_state": storage_state, "accept_downloads": False})
        )
        closed = asyncio.Event()
        run: Optional[_Run] = None

        def _on_closed(*_args) -> None:
            if not closed.is_set():
                closed.set()

        async def _close_context() -> None:
            try:
                await context.close()
            except Exception:
                pass

        try:
            page = await context.new_page()
            context.on("close", _on_closed)
            page.on("close", _on_closed)
            await install_canary_guard(context, policy, page)
            driver = driver_factory(page)
            run = _Run(page, driver, policy, permit, expected_identity, writer_plan, closed,
                       readback_attempts=readback_attempts, readback_interval_ms=readback_interval_ms)

            # -- 1. production search + exact mission open (no mutation) --
            try:
                await page.goto(f"{portal_origin(host)}{search_page_route}")
                run.guard()
                reader = ReadCapability(context, page, host, mission_policy_controller=policy)
                candidates = await reader.search(identifiers)
                if len(candidates) != 1:
                    raise _IdentityRefused("CANDIDATE_NOT_UNIQUE")
                await reader.open(candidates[0])
                run.guard()
                verify_identity(expected_identity, await reader.observe_identity())
                require_workflow_agreement(RepairWorkflow.MODE_NORMAL, await detect_observed_workflow(page))
            except CanaryAbort:
                raise
            except _IdentityRefused as exc:
                policy.abort()
                emit(WRITE_OUTCOME_IDENTITY_FAILED, exc.reason, policy, run)
                await _close_context()
                return WRITE_OUTCOME_IDENTITY_FAILED
            except Exception:
                policy.abort()
                reason = "NETWORK_VIOLATION" if policy.has_violation else "IDENTITY_OR_NAVIGATION_FAILED"
                outcome = WRITE_OUTCOME_WRITE_ABORTED if policy.has_violation else WRITE_OUTCOME_IDENTITY_FAILED
                emit(outcome, reason, policy, run)
                await _close_context()
                return outcome
            run.guard()

            # -- 2. rows, golden sequence, exact read-back each --
            on_phase(PHASE_WRITING)
            for index, intent in enumerate(writer_plan.row_intents):
                await run.write_row(index, intent)
            # -- 3. approved header fields --
            await run.fill_and_verify_fields()
            # -- 4. native calculation + independent summary verification --
            on_phase(PHASE_VERIFYING)
            await run.calculate_and_verify()
            run.guard()

            policy.enter_review()
            emit(WRITE_OUTCOME_READY_FOR_HUMAN_REVIEW, None, policy, run)
            await on_ready_for_review()
            await closed.wait()
            return WRITE_OUTCOME_READY_FOR_HUMAN_REVIEW

        except CanaryAbort as exc:
            policy.abort()
            emit(WRITE_OUTCOME_WRITE_ABORTED, exc.reason, policy, run)
            if not closed.is_set():
                try:
                    await asyncio.wait_for(closed.wait(), timeout=abort_hold_seconds)
                except asyncio.TimeoutError:
                    pass
            return WRITE_OUTCOME_WRITE_ABORTED
        except asyncio.CancelledError:
            policy.abort()
            emit(WRITE_OUTCOME_WRITE_ABORTED, "CANCELLED", policy, run)
            raise
        except Exception:
            # Unexpected: fail closed, never READY.
            policy.abort()
            emit(WRITE_OUTCOME_WRITE_ABORTED, "INTERNAL_ERROR", policy, run)
            if run is not None and run.mutated and not closed.is_set():
                try:
                    await asyncio.wait_for(closed.wait(), timeout=abort_hold_seconds)
                except asyncio.TimeoutError:
                    pass
            return WRITE_OUTCOME_WRITE_ABORTED
        finally:
            await _close_context()
