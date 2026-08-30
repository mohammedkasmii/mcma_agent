"""
mcma.portal.writer -- VerifiedMissionWriter (INC-09B, SAFETY_MODEL.md §1/§4,
PORTAL_CONTRACT.md §10, docs/architecture/PORTAL_ROW_WORKFLOWS.md).

The write-capable capability. Every write/native-recalc RouteContract is
validated and FROZEN before any BrowserContext exists (mcma.portal.
interception.WriterPolicyController); the network policy only ever
widens through two one-way, at-most-once transitions
(authorize_exact_mission_route, then activate_write_once) driven by a
private WriterPolicyController that the writer never holds directly --
only an AbortOnlyHandle wrapping one, which exposes exactly one method.
See mcma.portal.interception's module docstring for the full state
machine (SEARCH_READ -> MISSION_READ -> WRITE_ACTIVE -> ABORTED).

PEC's read-before-write preflight (matching every planned rubrique to
exactly one existing row) happens INSIDE open_verified_writer's
construction sequence, using rows fetched through the caller's own
reviewed read_rows contract -- never accepted as a caller-supplied
dictionary. Preflight failure aborts and closes the context before
WRITE_ACTIVE is ever reached; there is no public preflight method.

The public surface is exactly eight operations: add_normal_row,
edit_conventionne_row, read_row, verify_row, trigger_native_recalc,
read_financial_summary, verify_financial_summary, close. None of them
take a lease_handle argument -- open_verified_writer stores the single
LeaseHandle that passed construction, and every request-emitting
operation rechecks THAT stored lease (never a value a caller could
substitute later) immediately before emission and again after a
successful response/read-back.

-- Mode Normal's native financial calculation is UNCONFIRMED --
docs/architecture/PORTAL_ROW_WORKFLOWS.md §3.1: there is no confirmed
SinAuto-native function, readiness signal, or summary read-back contract
for Mode Normal. `trigger_native_recalc()` for MODE_NORMAL therefore
ALWAYS raises NativeCalculationUnconfirmed, unconditionally -- this module
contains no reference to any mock-only Mode Normal function, endpoint, or
selector name anywhere. The generation/version invalidation logic that
would apply once Mode Normal's contract is eventually confirmed is
exercised directly, in isolation, by tests/portal/writer/
test_calculation_ledger.py (a pure, page-free unit) -- no test-only
injection point exists on open_verified_writer or on the writer itself.

-- PEC's native financial calculation is a strictly loopback-only,
MOCK-ONLY verification adapter --
docs/architecture/PORTAL_ROW_WORKFLOWS.md §3.2 confirms only three
selectors (#DevisTvaRecupI as an input toggle, #DevisMontantChargeMutuelle
and #DevisMontantChargeSocietaire as summary values) and separately
requires reading "total TVA, total TTC, vétusté, franchise, remise,
montant arrêté, and base indemnité" -- none of which has a confirmed live
selector anywhere in recovered evidence. For this strictly loopback-only
INC-09B implementation, mock_server.py's /_mock/pec/native_calculation
response carries a typed `expected` FinancialSummary and a
`calculation_version` (both MOCK_ONLY/UNCONFIRMED -- see
tests/fixtures/contracts/pec_native_recalc.json and
pec_financial_summary_mock_only.json); the seven fields with no confirmed
selector are read from unmistakably synthetic `[data-mock-only-*]`
attributes, never from an invented plausible `#Devis...` id.
verify_financial_summary() compares that `expected` summary against an
INDEPENDENT fresh DOM read-back (never the same value read twice) -- a
genuine two-channel check, not the mock's DOM compared to itself. Because
`_require_loopback_host` structurally refuses any non-loopback
`allowed_host` before a browser is ever created, this whole mechanism
cannot run against a non-loopback/live host at all; a live equivalent does
not exist and is not implemented here -- it remains a G5 blocker.

-- Vétusté: amount-only input (INC-09B amendment #4) --
PortalRowIntent carries only the approved vétusté AMOUNT, never a rate --
there is no confirmed authorized upstream field for a rate. The writer
fills only MontantVetusteValide and dispatches the documented events so
the mock's client-side JS derives the displayed TauxVetusteValide FROM the
amount (never the reverse); the writer then independently recomputes the
same exact HALF_UP formula in Python (Decimal, matching Money's own
convention) and asserts the DOM's derived rate equals that computed value
exactly -- not merely that it is present/parseable. A TTC of zero (or any
other undefined derivation) fails closed. This formula is itself
MOCK_ONLY/UNCONFIRMED for the live PEC contract -- see the module
docstring section above.

-- No raw external data in exception messages --
Every exception message is built from fixed strings, a field NAME (never
a value), and/or a reason code drawn from a fixed allowlist
(_ALLOWLISTED_SERVER_REASON_CODES) -- never a raw response body, URL,
identity, mission id, registration, or monetary value. An unrecognized
server-supplied reason string is mapped to the fixed "UNKNOWN_SERVER_
REASON" code rather than echoed.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import NoReturn, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from mcma.core.money import Money
from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.capabilities import LeaseHandle, SearchIdentifiers
from mcma.portal.contracts import RouteContract, contracts_for_workflow
from mcma.portal.final_endpoints import is_permanently_blocked
from mcma.portal.identity import ExpectedIdentity, verify_identity
from mcma.portal.interception import (
    MISSION_OPEN_OPERATION_TYPE,
    AbortOnlyHandle,
    WriterPolicyController,
)
from mcma.portal.mission import (
    MissionCandidate,
    detect_observed_workflow,
    observe_identity,
    require_workflow_agreement,
    search_exactly_one,
)
from mcma.portal.session import open_guarded_context_for_writer

# --------------------------------------------------------------------- #
# Portal-local plan-binding types (mcma.domain/mcma.core only -- never
# mcma.planning/mcma.execution; same principle as identity.py's
# ExpectedIdentity mirror)
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class PortalRowIntent:
    """One approved row's exact bound values. The writer's row-operation
    methods take ONLY a rubrique_id and look these up internally -- there
    is no parameter through which a caller could supply an altered
    ht/tva/vetuste value."""

    rubrique_id: RubriqueId
    ht: Money
    tva: Money
    vetuste: Money

    def __post_init__(self) -> None:
        if not isinstance(self.rubrique_id, RubriqueId):
            raise TypeError("PortalRowIntent.rubrique_id must be a RubriqueId")
        for name in ("ht", "tva", "vetuste"):
            if not isinstance(getattr(self, name), Money):
                raise TypeError(f"PortalRowIntent.{name} must be a Money")


@dataclass(frozen=True)
class WriterPlanData:
    """The complete, exact set of approved row intents for one workflow.
    Duplicate rubrique_id values are rejected at construction -- a
    WriterPlanData can never itself be ambiguous about what a given
    rubrique_id's approved values are."""

    repair_workflow: RepairWorkflow
    row_intents: Tuple[PortalRowIntent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.repair_workflow, RepairWorkflow):
            raise TypeError("WriterPlanData.repair_workflow must be a RepairWorkflow")
        intents = tuple(self.row_intents)
        object.__setattr__(self, "row_intents", intents)
        if not all(isinstance(i, PortalRowIntent) for i in intents):
            raise TypeError("WriterPlanData.row_intents must contain only PortalRowIntent")
        seen: set = set()
        for intent in intents:
            if intent.rubrique_id in seen:
                raise ValueError("duplicate rubrique_id in WriterPlanData")
            seen.add(intent.rubrique_id)

    def intent_for(self, rubrique_id: RubriqueId) -> Optional[PortalRowIntent]:
        for intent in self.row_intents:
            if intent.rubrique_id == rubrique_id:
                return intent
        return None

    def planned_rubrique_values(self) -> frozenset:
        return frozenset(i.rubrique_id.value for i in self.row_intents)


def _workflow_key(repair_workflow: RepairWorkflow) -> str:
    """RouteContract.workflow is the bare string "MODE_NORMAL"/
    "GARAGE_CONVENTIONNE" (the enum member's .name -- the convention
    already established across every RouteContract fixture in
    INC-07/08/09A), never a RepairWorkflow instance and never .value
    ("mode_normal"). Calling contracts_for_workflow() directly with an
    enum member would silently discard every workflow-specific contract,
    since a bare Enum member never equals a string."""
    return repair_workflow.name


# --------------------------------------------------------------------- #
# Strict validation (INC-09B amendments #1/#6, round-3 item G)
# --------------------------------------------------------------------- #


def _require_valid_mission_id(id_mission: object) -> int:
    """Strict positive integer only. bool is checked first since bool is
    an int subclass in Python. The validated integer is later formatted
    via plain str(int) -- never string-interpolating a raw value -- so
    encoded separators/traversal text are structurally excluded from the
    constructed route rather than merely screened for. The error message
    never echoes the raw (possibly attacker/portal-supplied) value."""
    if isinstance(id_mission, bool) or not isinstance(id_mission, int):
        raise ValueError("id_mission must be a strict positive integer")
    if id_mission <= 0:
        raise ValueError("id_mission must be a strict positive integer")
    return id_mission


def _require_valid_calculation_version(raw) -> int:
    """Strict positive integer -- bool/float/string coercion/zero/negative
    all rejected outright, never truncated or silently coerced via a bare
    int(...) call."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("calculation_version must be a strict positive integer")
    if raw <= 0:
        raise ValueError("calculation_version must be a strict positive integer")
    return raw


_MISSION_DEEP_LINK_TEMPLATE = (
    "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id_segment}/rubrique/gestionexpert-index"
)


def _mission_route_for(id_mission: int) -> str:
    """The one fixed template, built only from a value already validated
    by _require_valid_mission_id -- str(int) can never contain a
    separator or traversal character."""
    return _MISSION_DEEP_LINK_TEMPLATE.format(id_segment=str(id_mission))


def _require_loopback_host(allowed_host: str) -> None:
    """ipaddress-based loopback validation -- rejects DNS names (including
    "localhost", a hostname requiring resolution, not a literal),
    userinfo, any path/query/fragment (a bare host:port only -- "/" is not
    accepted as an empty path), malformed/out-of-range ports, and
    non-loopback addresses. Bracketed IPv6 loopback ("[::1]:8080") is
    correctly accepted: urlsplit unbrackets it into hostname="::1"."""
    parsed = urlsplit(f"http://{allowed_host}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("allowed_host must not contain userinfo")
    if parsed.path != "" or parsed.query or parsed.fragment:
        raise ValueError("allowed_host must be a bare host:port with no path/query/fragment")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("allowed_host must include a hostname")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("allowed_host has a malformed or out-of-range port") from exc
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise ValueError("allowed_host must be a loopback IP literal, not a DNS name") from exc
    if not ip.is_loopback:
        raise ValueError("allowed_host must be a loopback address")


# --------------------------------------------------------------------- #
# Fixed server reason-code allowlist -- an unrecognized reason is mapped
# to a fixed placeholder, never echoed raw into an exception message.
# --------------------------------------------------------------------- #

_ALLOWLISTED_SERVER_REASON_CODES = frozenset(
    {
        "DIRECT_CHARGE_FIELD_WRITE_REJECTED",
        "MISSING_TEMP_ROW_ID",
        "DUPLICATE_ROW_SUBMISSION",
        "MISSING_SUBMISSION_NONCE",
        "ROW_NOT_FOUND",
        "NATIVE_CALCULATION_FAILED",
        "MISSING_CALCULATION_RESULT",
    }
)

_UNKNOWN_SERVER_REASON = "UNKNOWN_SERVER_REASON"


def _map_reason_code(raw_reason: object) -> str:
    if isinstance(raw_reason, str) and raw_reason in _ALLOWLISTED_SERVER_REASON_CODES:
        return raw_reason
    return _UNKNOWN_SERVER_REASON


# --------------------------------------------------------------------- #
# Exceptions -- every message is a fixed string plus, at most, a field
# name or an allowlisted reason code. Never a raw external value.
# --------------------------------------------------------------------- #


class WriteAborted(Exception):
    """Base for every failure that terminally aborts a VerifiedMissionWriter."""


class MissionRouteInvalid(WriteAborted):
    pass


class UnplannedRubrique(WriteAborted):
    pass


class UnplannedExistingRow(WriteAborted):
    pass


class RowAmbiguous(WriteAborted):
    pass


class RowMismatch(WriteAborted):
    pass


class RowWriteRejected(WriteAborted):
    pass


class RowWriteUncertain(WriteAborted):
    pass


class RowReadBackMismatch(WriteAborted):
    pass


class VetusteRateDerivationUndefined(WriteAborted):
    pass


class NativeCalculationUnconfirmed(WriteAborted):
    """MODE_NORMAL only. Always raised, unconditionally -- see module
    docstring."""


class NativeCalculationMissing(WriteAborted):
    pass


class NativeCalculationFailed(WriteAborted):
    pass


class NativeCalculationMalformed(WriteAborted):
    pass


class NativeCalculationIncomplete(WriteAborted):
    pass


class NativeCalculationStale(WriteAborted):
    pass


class NativeCalculationMismatch(WriteAborted):
    pass


# --------------------------------------------------------------------- #
# FinancialSummary + the pure, page-free calculation ledger
# --------------------------------------------------------------------- #

# Every field below is independently classified. The first two are
# CONFIRMED_RECOVERED_PEC_DOM_EVIDENCE (PORTAL_ROW_WORKFLOWS.md §3.2); the
# remaining seven are MOCK_ONLY/UNCONFIRMED -- named concepts from the same
# section with no confirmed live selector anywhere in recovered evidence.
# #DevisTvaRecupI is confirmed but is an input TOGGLE dispatched before
# the trigger, not a read/verify summary VALUE -- it is deliberately not
# a FinancialSummary field (see read_financial_summary()).
FINANCIAL_SUMMARY_FIELDS: Tuple[str, ...] = (
    "montant_charge_mutuelle",
    "montant_charge_societaire",
    "total_tva",
    "total_ttc",
    "vetuste",
    "franchise",
    "remise",
    "montant_arrete",
    "base_indemnite",
)


@dataclass(frozen=True)
class FinancialSummary:
    """PEC financial-summary evidence -- see FINANCIAL_SUMMARY_FIELDS for
    the exact, complete field list and per-field evidence classification.
    No "etc": this is the whole type."""

    montant_charge_mutuelle: Money
    montant_charge_societaire: Money
    total_tva: Money
    total_ttc: Money
    vetuste: Money
    franchise: Money
    remise: Money
    montant_arrete: Money
    base_indemnite: Money

    def __post_init__(self) -> None:
        for name in FINANCIAL_SUMMARY_FIELDS:
            if not isinstance(getattr(self, name), Money):
                raise TypeError(f"FinancialSummary.{name} must be a Money")


def parse_financial_summary(raw: dict) -> FinancialSummary:
    """Parses a native-calculation response's `expected` object (or a
    fresh DOM read-back's own dict) into a FinancialSummary. Missing field
    -> NativeCalculationIncomplete; unparseable value ->
    NativeCalculationMalformed. Both are distinct, fail-closed errors."""
    if not isinstance(raw, dict):
        raise NativeCalculationMalformed("financial summary payload is not an object")
    values = {}
    for name in FINANCIAL_SUMMARY_FIELDS:
        if name not in raw or raw[name] is None:
            raise NativeCalculationIncomplete(f"financial summary is missing field: {name}")
        try:
            values[name] = Money.of(str(raw[name]))
        except (TypeError, ValueError) as exc:
            raise NativeCalculationMalformed(f"financial summary field is not a valid Money value: {name}") from exc
    return FinancialSummary(**values)


@dataclass(frozen=True)
class TvaRecuperableContext:
    """#DevisTvaRecupI is a CONFIRMED input toggle (PORTAL_ROW_WORKFLOWS.md
    3.2), never a FinancialSummary Money field -- it is a boolean the
    trigger step may dispatch a change event on, kept structurally
    separate from the nine monetary summary fields."""

    checked: bool


@dataclass
class _CalculationEvidence:
    row_generation: int
    calculation_version: int
    expected: FinancialSummary


class CalculationLedger:
    """Pure, page-free, Playwright-free state machine -- no I/O of any
    kind. Tracks row-mutation generation AND the mock's own monotonic
    calculation_version; staleness is detected via EITHER signal
    independently."""

    def __init__(self) -> None:
        self.row_generation = 0
        self._last_calculation_version = 0
        self._evidence: Optional[_CalculationEvidence] = None

    def record_mutation(self) -> None:
        """Called on every ACTUAL row mutation (never a no-op skip).
        Deliberately does NOT clear `_evidence` outright -- doing so would
        make the row_generation mismatch branch in verify_fresh() dead
        code, collapsing "mutated since the last calculation" into
        "never calculated at all" (WriteAborted) instead of the more
        specific NativeCalculationStale."""
        self.row_generation += 1

    def record_trigger(self, calculation_version: int, expected: FinancialSummary) -> None:
        """Called immediately after a successful (state=success) trigger
        response is parsed. calculation_version must already have been
        validated by _require_valid_calculation_version. A version that
        does not strictly advance past the last one this ledger has seen
        is stale -- the mock's own simulate=stale mode produces exactly
        this."""
        if calculation_version <= self._last_calculation_version:
            raise NativeCalculationStale("calculation_version did not advance past the last recorded value")
        self._last_calculation_version = calculation_version
        self._evidence = _CalculationEvidence(self.row_generation, calculation_version, expected)

    def verify_fresh(self, observed: FinancialSummary) -> FinancialSummary:
        """Called with an INDEPENDENTLY read (never the same value read
        twice) observed summary."""
        if self._evidence is None:
            raise WriteAborted("verify_financial_summary called before any successful trigger")
        if self._evidence.row_generation != self.row_generation:
            raise NativeCalculationStale("a row mutation occurred after the last recorded calculation")
        if self._evidence.expected != observed:
            raise NativeCalculationMismatch("expected financial summary does not match the fresh DOM read-back")
        return observed


# --------------------------------------------------------------------- #
# Vétusté rate derivation -- Decimal/HALF_UP, matching Money's own
# established convention; independently recomputed here, not trusted
# from the DOM alone.
# --------------------------------------------------------------------- #

_TWO_DP = Decimal("0.01")


def derive_vetuste_rate(amount: Money, ttc: Money) -> Decimal:
    """rate (%) = amount / ttc * 100, HALF_UP to 2dp. TTC == 0 is an
    undefined derivation and raises VetusteRateDerivationUndefined --
    never coerced to 0.00. MOCK_ONLY/UNCONFIRMED formula for the live PEC
    contract -- see module docstring."""
    if ttc.amount == Decimal("0.00"):
        raise VetusteRateDerivationUndefined("TTC is zero; vetuste rate derivation is undefined")
    rate = (amount.amount / ttc.amount * Decimal("100")).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    return rate


# --------------------------------------------------------------------- #
# JS: fixed scripts only, caller data passed as serialized evaluate()
# arguments -- never interpolated into script text. Named by role
# (FILL vs READ) so a static test can distinguish them.
# --------------------------------------------------------------------- #

_FETCH_JSON_JS = """([url, payload]) => fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams(payload).toString()
}).then(r => r.json())"""

_FILL_NORMAL_ROW_JS = """([tempId, ht, tva]) => {
    const setAndFire = (el, value) => {
        el.focus();
        el.value = value;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('keyup', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.dispatchEvent(new Event('blur', {bubbles: true}));
    };
    setAndFire(document.getElementById('MontantHT_' + tempId), ht);
    setAndFire(document.getElementById('Taxe_' + tempId), tva);
}"""

_FILL_PEC_ROW_JS = """([id, ht, tva, vetusteAmount]) => {
    const setAndFire = (el, value) => {
        el.focus();
        el.value = value;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('keyup', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.dispatchEvent(new Event('blur', {bubbles: true}));
    };
    setAndFire(document.getElementById('MontantHTValide_' + id), ht);
    setAndFire(document.getElementById('TaxeValide_' + id), tva);
    setAndFire(document.getElementById('MontantVetusteValide_' + id), vetusteAmount);
}"""

_READ_PEC_ROW_JS = """([id]) => {
    const read = (fieldId) => {
        const el = document.getElementById(fieldId);
        return el ? el.value : null;
    };
    return {
        MontantHT: read('MontantHTValide_' + id),
        Taxe: read('TaxeValide_' + id),
        MontantTTC: read('MontantTTCValide_' + id),
        TauxVetuste: read('TauxVetusteValide_' + id),
        MontantVetuste: read('MontantVetusteValide_' + id),
    };
}"""

_READ_FINANCIAL_SUMMARY_JS = """() => {
    const readById = (id) => {
        const el = document.getElementById(id);
        return el ? el.value : null;
    };
    const readByAttr = (attr) => {
        const el = document.querySelector('[' + attr + ']');
        return el ? el.value : null;
    };
    return {
        montant_charge_mutuelle: readById('DevisMontantChargeMutuelle'),
        montant_charge_societaire: readById('DevisMontantChargeSocietaire'),
        total_tva: readByAttr('data-mock-only-total-tva'),
        total_ttc: readByAttr('data-mock-only-total-ttc'),
        vetuste: readByAttr('data-mock-only-vetuste-total'),
        franchise: readByAttr('data-mock-only-franchise'),
        remise: readByAttr('data-mock-only-remise'),
        montant_arrete: readByAttr('data-mock-only-montant-arrete'),
        base_indemnite: readByAttr('data-mock-only-base-indemnite'),
    };
}"""

_READ_TVA_RECUPERABLE_TOGGLE_JS = """() => {
    const el = document.getElementById('DevisTvaRecupI');
    return el ? !!el.checked : null;
}"""

_DISPATCH_CHANGE_JS = """(id) => {
    const el = document.getElementById(id);
    if (el) { el.dispatchEvent(new Event('change', {bubbles: true})); }
}"""

_DOM_ROW_IDS_JS = """(selector) => Array.from(document.querySelectorAll(selector)).map((tr) => tr.id)"""


# --------------------------------------------------------------------- #
# VerifiedMissionWriter
# --------------------------------------------------------------------- #

_CONSTRUCTION_TOKEN = object()


class VerifiedMissionWriter:
    """Only constructible via open_verified_writer(). The construction
    token below is an API-construction safeguard mirroring INC-08's
    Candidate owner-token pattern, not a cryptographic security boundary
    -- Python provides no true private construction, and this does not
    claim otherwise.

    Public surface: add_normal_row, edit_conventionne_row, read_row,
    verify_row, trigger_native_recalc, read_financial_summary,
    verify_financial_summary, close. Nothing else -- no lease_handle
    parameter anywhere, no preflight method, no generic write method, no
    access to the page/context/request objects or the policy control."""

    __slots__ = (
        "_context",
        "_page",
        "_abort_handle",
        "_lease_handle",
        "_expected_identity",
        "_writer_plan",
        "_allowed_host",
        "_read_rows_route",
        "_closed",
        "_terminally_aborted",
        "_ledger",
        "_pec_row_map",
    )

    def __init__(
        self,
        construction_token: object,
        context,
        page,
        abort_handle: AbortOnlyHandle,
        lease_handle: LeaseHandle,
        expected_identity: ExpectedIdentity,
        writer_plan: WriterPlanData,
        allowed_host: str,
        read_rows_route: str,
        pec_row_map: dict,
    ) -> None:
        if construction_token is not _CONSTRUCTION_TOKEN:
            raise RuntimeError(
                "VerifiedMissionWriter must be constructed via open_verified_writer()"
            )
        self._context = context
        self._page = page
        self._abort_handle = abort_handle
        self._lease_handle = lease_handle
        self._expected_identity = expected_identity
        self._writer_plan = writer_plan
        self._allowed_host = allowed_host
        self._read_rows_route = read_rows_route
        self._closed = False
        self._terminally_aborted = False
        self._ledger = CalculationLedger()
        self._pec_row_map = dict(pec_row_map)

    # -- guards ---------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("VerifiedMissionWriter is closed")
        if self._terminally_aborted:
            raise WriteAborted("writer is terminally aborted; construct a new writer")

    async def _terminal_abort(self, exc: BaseException) -> NoReturn:
        """Policy -> ABORTED/deny-all BEFORE awaiting context.close()."""
        self._terminally_aborted = True
        self._abort_handle.abort()
        try:
            await self._context.close()
        except Exception:
            pass
        raise exc

    async def _recheck_lease(self) -> None:
        try:
            await self._lease_handle.assert_valid()
        except Exception as exc:
            await self._terminal_abort(exc)

    async def _preflight_before_mutation(self) -> None:
        """Re-checked immediately before EVERY request-emitting action:
        the stored lease, identity, and workflow agreement. A caller
        cannot substitute a fresh lease here -- there is no parameter
        through which one could ever be supplied."""
        await self._recheck_lease()
        try:
            observed_identity = await observe_identity(self._page)
            verify_identity(self._expected_identity, observed_identity)
            observed_workflow = await detect_observed_workflow(self._page)
            require_workflow_agreement(self._writer_plan.repair_workflow, observed_workflow)
        except WriteAborted:
            raise
        except Exception as exc:
            await self._terminal_abort(exc)

    def _absolute_url(self, path: str) -> str:
        return f"http://{self._allowed_host}{path}"

    async def _fetch_rows(self) -> list:
        try:
            result = await self._page.evaluate(_FETCH_JSON_JS, [self._absolute_url(self._read_rows_route), {}])
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("could not fetch current rows"))
        data = result.get("data", []) if isinstance(result, dict) else []
        return list(data) if isinstance(data, list) else []

    # -- Mode Normal ------------------------------------------------------

    async def add_normal_row(self, rubrique_id: RubriqueId) -> None:
        self._ensure_open()
        if self._writer_plan.repair_workflow is not RepairWorkflow.MODE_NORMAL:
            await self._terminal_abort(WriteAborted("add_normal_row requires a MODE_NORMAL writer"))
        intent = self._writer_plan.intent_for(rubrique_id)
        if intent is None:
            await self._terminal_abort(UnplannedRubrique("rubrique_id is not in the approved plan"))

        await self._preflight_before_mutation()

        rows = await self._fetch_rows()
        planned = self._writer_plan.planned_rubrique_values()
        for row in rows:
            if str(row.get("IdRubrique")) not in planned:
                await self._terminal_abort(UnplannedExistingRow("an unplanned existing row is present"))

        matches = [r for r in rows if str(r.get("IdRubrique")) == rubrique_id.value]
        if len(matches) == 1:
            existing = matches[0]
            if Money.of(str(existing.get("MontantHT", ""))) == intent.ht and Money.of(
                str(existing.get("Taxe", ""))
            ) == intent.tva:
                return  # already satisfied -- no-op
            await self._terminal_abort(RowMismatch("an existing row disagrees with the approved intent"))
        elif len(matches) > 1:
            await self._terminal_abort(RowAmbiguous("multiple existing rows match this rubrique"))

        before_ids = set(await self._page.evaluate(_DOM_ROW_IDS_JS, "#tbodyModeNormal tr"))
        ajouter = self._page.locator("#sectionModeNormal").get_by_text("Ajouter", exact=False)
        try:
            count = await ajouter.count()
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("could not locate the Ajouter control"))
        if count != 1:
            await self._terminal_abort(RowAmbiguous("Ajouter is not scoped to exactly one element"))
        try:
            await ajouter.click()
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("could not click Ajouter"))
        after_ids = set(await self._page.evaluate(_DOM_ROW_IDS_JS, "#tbodyModeNormal tr"))
        new_ids = after_ids - before_ids
        if len(new_ids) != 1:
            await self._terminal_abort(RowAmbiguous("Ajouter did not create exactly one new row"))
        new_row_id = next(iter(new_ids))
        temp_id = new_row_id.replace("normal_row_", "", 1)

        try:
            select_locator = self._page.locator(f"#IdRubrique_{temp_id}")
            await select_locator.select_option(value=intent.rubrique_id.value)
            await self._page.evaluate(
                _FILL_NORMAL_ROW_JS, [temp_id, str(intent.ht.amount), str(intent.tva.amount)]
            )
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("could not fill the new row"))

        try:
            async with self._page.expect_response(
                lambda r: r.url.endswith("/createRapportDefDet") and r.request.method == "POST",
                timeout=5000,
            ) as response_info:
                await self._page.locator(f"#normal_row_{temp_id} >> text=OK").click()
            response = await response_info.value
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("createRapportDefDet response was not observed"))

        if response.status != 200:
            await self._terminal_abort(RowWriteRejected("createRapportDefDet returned a non-200 status"))
        try:
            body = await response.json()
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("createRapportDefDet response body was not JSON"))
        if body.get("state") != "success":
            await self._terminal_abort(RowWriteRejected(_map_reason_code(body.get("reason"))))

        self._ledger.record_mutation()

        fresh_rows = await self._fetch_rows()
        persisted = [
            r
            for r in fresh_rows
            if str(r.get("IdRubrique")) == rubrique_id.value
            and Money.of(str(r.get("MontantHT", ""))) == intent.ht
            and Money.of(str(r.get("Taxe", ""))) == intent.tva
        ]
        if len(persisted) != 1:
            await self._terminal_abort(RowReadBackMismatch("exact read-back after createRapportDefDet failed"))

        await self._recheck_lease()

    # -- Garage Conventionne / PEC ---------------------------------------

    async def edit_conventionne_row(self, rubrique_id: RubriqueId) -> None:
        self._ensure_open()
        if self._writer_plan.repair_workflow is not RepairWorkflow.GARAGE_CONVENTIONNE:
            await self._terminal_abort(WriteAborted("edit_conventionne_row requires a GARAGE_CONVENTIONNE writer"))
        intent = self._writer_plan.intent_for(rubrique_id)
        if intent is None:
            await self._terminal_abort(UnplannedRubrique("rubrique_id is not in the approved plan"))
        cached_id_devis_det = self._pec_row_map.get(rubrique_id.value)
        if cached_id_devis_det is None:
            await self._terminal_abort(UnplannedRubrique("rubrique_id was not resolved during preflight"))

        await self._preflight_before_mutation()

        rows = await self._fetch_rows()
        matches = [r for r in rows if str(r.get("IdRubrique")) == rubrique_id.value]
        if len(matches) != 1:
            await self._terminal_abort(RowAmbiguous("the planned rubrique no longer matches exactly one row"))
        current = matches[0]
        if current.get("IdDevisDet") != cached_id_devis_det:
            await self._terminal_abort(RowAmbiguous("the cached row mapping no longer matches the fresh read"))

        if (
            Money.of(str(current.get("MontantHT", ""))) == intent.ht
            and Money.of(str(current.get("Taxe", ""))) == intent.tva
            and Money.of(str(current.get("MontantVetuste", ""))) == intent.vetuste
        ):
            return  # diff-before-write: already exactly equal -- no-op

        id_devis_det = cached_id_devis_det
        try:
            await self._page.locator(f"#row_val_{id_devis_det} >> text=edit").click()
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("could not click the row's edit action"))

        try:
            await self._page.evaluate(
                _FILL_PEC_ROW_JS,
                [id_devis_det, str(intent.ht.amount), str(intent.tva.amount), str(intent.vetuste.amount)],
            )
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("could not fill the row's fields"))

        ttc = intent.ht + intent.tva
        try:
            expected_rate = derive_vetuste_rate(intent.vetuste, ttc)
        except VetusteRateDerivationUndefined:
            expected_rate = None

        try:
            rendered = await self._page.evaluate(_READ_PEC_ROW_JS, [id_devis_det])
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("could not read the row's rendered fields"))

        rendered_rate_raw = rendered.get("TauxVetuste")
        if expected_rate is None:
            if rendered_rate_raw not in (None, ""):
                await self._terminal_abort(
                    VetusteRateDerivationUndefined("TTC is zero but a vetuste rate was rendered")
                )
        else:
            if rendered.get("MontantTTC") in (None, ""):
                await self._terminal_abort(VetusteRateDerivationUndefined("TTC was not rendered"))
            if rendered_rate_raw in (None, ""):
                await self._terminal_abort(VetusteRateDerivationUndefined("vetuste rate was not rendered"))
            try:
                rendered_rate = Decimal(str(rendered_rate_raw))
            except Exception:
                await self._terminal_abort(VetusteRateDerivationUndefined("vetuste rate is not a valid decimal"))
            if rendered_rate != expected_rate:
                await self._terminal_abort(
                    VetusteRateDerivationUndefined("rendered vetuste rate disagrees with the exact formula result")
                )

        try:
            async with self._page.expect_response(
                lambda r: r.url.endswith("/updateDevisDet") and r.request.method == "POST",
                timeout=5000,
            ) as response_info:
                await self._page.locator(f"#row_val_{id_devis_det} >> text=OK").click()
            response = await response_info.value
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("updateDevisDet response was not observed"))

        if response.status != 200:
            await self._terminal_abort(RowWriteRejected("updateDevisDet returned a non-200 status"))
        try:
            body = await response.json()
        except Exception as exc:
            await self._terminal_abort(RowWriteUncertain("updateDevisDet response body was not JSON"))
        if body.get("state") != "success":
            await self._terminal_abort(RowWriteRejected(_map_reason_code(body.get("reason"))))

        self._ledger.record_mutation()

        fresh_rows = await self._fetch_rows()
        fresh_matches = [r for r in fresh_rows if r.get("IdDevisDet") == id_devis_det]
        if len(fresh_matches) != 1:
            await self._terminal_abort(RowReadBackMismatch("exact read-back after updateDevisDet failed"))
        persisted = fresh_matches[0]
        if Money.of(str(persisted.get("MontantHT", ""))) != intent.ht:
            await self._terminal_abort(RowReadBackMismatch("MontantHT"))
        if Money.of(str(persisted.get("Taxe", ""))) != intent.tva:
            await self._terminal_abort(RowReadBackMismatch("Taxe"))
        if Money.of(str(persisted.get("MontantVetuste", ""))) != intent.vetuste:
            await self._terminal_abort(RowReadBackMismatch("MontantVetuste"))
        if expected_rate is not None:
            try:
                if Decimal(str(persisted.get("TauxVetuste", ""))) != expected_rate:
                    await self._terminal_abort(RowReadBackMismatch("TauxVetuste"))
            except Exception:
                await self._terminal_abort(RowReadBackMismatch("TauxVetuste"))

        await self._recheck_lease()

    # -- Read-back / verification (shared) --------------------------------

    async def read_row(self, rubrique_id: RubriqueId) -> dict:
        """Never a first-row/positional fallback -- zero or multiple
        matches for this rubrique fails closed."""
        self._ensure_open()
        rows = await self._fetch_rows()
        matches = [r for r in rows if str(r.get("IdRubrique")) == rubrique_id.value]
        if len(matches) != 1:
            await self._terminal_abort(RowAmbiguous("read_row did not find exactly one matching row"))
        return dict(matches[0])

    async def verify_row(self, rubrique_id: RubriqueId) -> None:
        self._ensure_open()
        intent = self._writer_plan.intent_for(rubrique_id)
        if intent is None:
            await self._terminal_abort(UnplannedRubrique("rubrique_id is not in the approved plan"))
        row = await self.read_row(rubrique_id)
        if Money.of(str(row.get("MontantHT", ""))) != intent.ht:
            await self._terminal_abort(RowReadBackMismatch("MontantHT"))
        if Money.of(str(row.get("Taxe", ""))) != intent.tva:
            await self._terminal_abort(RowReadBackMismatch("Taxe"))
        if self._writer_plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            if Money.of(str(row.get("MontantVetuste", ""))) != intent.vetuste:
                await self._terminal_abort(RowReadBackMismatch("MontantVetuste"))
            ttc = intent.ht + intent.tva
            try:
                expected_rate = derive_vetuste_rate(intent.vetuste, ttc)
            except VetusteRateDerivationUndefined:
                expected_rate = None
            if expected_rate is not None:
                try:
                    if Decimal(str(row.get("TauxVetuste", ""))) != expected_rate:
                        await self._terminal_abort(RowReadBackMismatch("TauxVetuste"))
                except Exception:
                    await self._terminal_abort(RowReadBackMismatch("TauxVetuste"))

    # -- Native financial calculation -------------------------------------

    async def trigger_native_recalc(self) -> None:
        self._ensure_open()
        if self._writer_plan.repair_workflow is RepairWorkflow.MODE_NORMAL:
            await self._terminal_abort(
                NativeCalculationUnconfirmed(
                    "MODE_NORMAL native financial recalculation has no confirmed contract"
                )
            )

        await self._preflight_before_mutation()

        try:
            await self._page.evaluate(_DISPATCH_CHANGE_JS, "DevisTvaRecupI")
        except Exception:
            pass

        try:
            async with self._page.expect_response(
                lambda r: r.url.endswith("/_mock/pec/native_calculation") and r.request.method == "POST",
                timeout=5000,
            ) as response_info:
                await self._page.evaluate("DevisCalculerMontantCharge()")
            response = await response_info.value
        except Exception as exc:
            await self._terminal_abort(NativeCalculationMissing("no native-calculation response observed"))

        try:
            body = await response.json()
        except Exception as exc:
            await self._terminal_abort(NativeCalculationMissing("native-calculation response body was not JSON"))

        if body.get("state") != "success":
            reason = _map_reason_code(body.get("reason"))
            if body.get("reason") == "MISSING_CALCULATION_RESULT":
                await self._terminal_abort(NativeCalculationMissing(reason))
            await self._terminal_abort(NativeCalculationFailed(reason))

        if "calculation_version" not in body or "expected" not in body:
            await self._terminal_abort(
                NativeCalculationIncomplete("native-calculation response missing calculation_version/expected")
            )

        try:
            version = _require_valid_calculation_version(body["calculation_version"])
        except ValueError as exc:
            await self._terminal_abort(NativeCalculationMalformed("calculation_version is not a valid positive integer"))

        try:
            expected = parse_financial_summary(body["expected"])
        except WriteAborted as exc:
            await self._terminal_abort(exc)

        try:
            self._ledger.record_trigger(version, expected)
        except NativeCalculationStale as exc:
            await self._terminal_abort(exc)

    async def _read_financial_summary_dom(self) -> FinancialSummary:
        first = await self._page.evaluate(_READ_FINANCIAL_SUMMARY_JS)
        second = await self._page.evaluate(_READ_FINANCIAL_SUMMARY_JS)
        if first != second:
            raise NativeCalculationMalformed("financial summary DOM read was unstable (torn read)")
        return parse_financial_summary(first)

    async def read_financial_summary(self) -> Tuple[FinancialSummary, TvaRecuperableContext]:
        self._ensure_open()
        try:
            summary = await self._read_financial_summary_dom()
            checked = await self._page.evaluate(_READ_TVA_RECUPERABLE_TOGGLE_JS)
        except WriteAborted as exc:
            await self._terminal_abort(exc)
        except Exception as exc:
            await self._terminal_abort(NativeCalculationMalformed("could not read the financial summary DOM"))
        return summary, TvaRecuperableContext(checked=bool(checked))

    async def verify_financial_summary(self) -> FinancialSummary:
        self._ensure_open()
        summary, _ = await self.read_financial_summary()
        try:
            self._ledger.verify_fresh(summary)
        except WriteAborted as exc:
            await self._terminal_abort(exc)
        return summary

    # -- lifecycle --------------------------------------------------------

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._context.close()
        except Exception:
            pass


# --------------------------------------------------------------------- #
# open_verified_writer -- the staged construction sequence
# --------------------------------------------------------------------- #


def _validate_write_contract(contract: RouteContract, allowed_host: str, workflow_key: str) -> None:
    if contract.host != allowed_host:
        raise ValueError("write/native-recalc contract host must equal allowed_host")
    if contract.capability not in ("row_write", "native_recalc"):
        raise ValueError("write/native-recalc contract capability is invalid")
    if is_permanently_blocked(contract.route):
        raise ValueError("write/native-recalc contract targets a permanently blocked route")
    if contract.workflow != workflow_key:
        raise ValueError(
            "write/native-recalc contract must name the exact workflow "
            "(never shared/None and never the other workflow)"
        )


async def _fetch_rows_during_construction(page, allowed_host: str, read_rows_route: str) -> list:
    url = f"http://{allowed_host}{read_rows_route}"
    result = await page.evaluate(_FETCH_JSON_JS, [url, {}])
    data = result.get("data", []) if isinstance(result, dict) else []
    return list(data) if isinstance(data, list) else []


async def open_verified_writer(
    browser,
    lease_handle: LeaseHandle,
    expected_identity: ExpectedIdentity,
    writer_plan: WriterPlanData,
    identifiers: SearchIdentifiers,
    contracts: Sequence[RouteContract],
    allowed_host: str,
    *,
    context_options: dict | None = None,
) -> VerifiedMissionWriter:
    if not isinstance(writer_plan, WriterPlanData):
        raise TypeError("open_verified_writer() requires a WriterPlanData")
    if not isinstance(expected_identity, ExpectedIdentity):
        raise TypeError("open_verified_writer() requires an ExpectedIdentity")

    _require_loopback_host(allowed_host)

    await lease_handle.assert_valid()

    workflow_key = _workflow_key(writer_plan.repair_workflow)
    scoped = contracts_for_workflow(workflow_key, tuple(contracts))

    read_contracts = tuple(c for c in scoped if c.capability == "read")
    write_contracts = tuple(c for c in scoped if c.capability in ("row_write", "native_recalc"))
    for c in write_contracts:
        _validate_write_contract(c, allowed_host, workflow_key)

    search_page_matches = [c for c in read_contracts if c.method == "GET" and c.operation_type == "search_page"]
    if len(search_page_matches) != 1:
        raise ValueError(
            "exactly one reviewed GET read contract with operation_type='search_page' is required"
        )
    search_page_route = search_page_matches[0].route

    read_rows_matches = [c for c in read_contracts if c.method == "POST" and c.operation_type == "read_rows"]
    if len(read_rows_matches) != 1:
        raise ValueError(
            "exactly one reviewed POST read contract with operation_type='read_rows' is required"
        )
    read_rows_route = read_rows_matches[0].route

    controller = WriterPolicyController(
        search_read_contracts=read_contracts,
        frozen_write_contracts=write_contracts,
        allowed_host=allowed_host,
    )
    abort_handle = AbortOnlyHandle(controller)

    context = await open_guarded_context_for_writer(browser, controller, allowed_host, context_options)
    pec_row_map: dict = {}
    try:
        page = await context.new_page()
        await page.goto(f"http://{allowed_host}{search_page_route}")

        candidate: MissionCandidate = await search_exactly_one(page, allowed_host, identifiers)
        id_mission = _require_valid_mission_id(candidate.id_mission)
        mission_route = _mission_route_for(id_mission)
        mission_contract = RouteContract(
            host=allowed_host,
            route=mission_route,
            method="GET",
            query_fields=frozenset(),
            content_type=None,
            body_fields=frozenset(),
            capability="read",
            operation_type=MISSION_OPEN_OPERATION_TYPE,
            workflow=None,
        )
        controller.authorize_exact_mission_route(mission_contract, expected_route=mission_route)

        await page.goto(f"http://{allowed_host}{mission_route}")

        observed_identity = await observe_identity(page)
        verify_identity(expected_identity, observed_identity)

        observed_workflow = await detect_observed_workflow(page)
        require_workflow_agreement(writer_plan.repair_workflow, observed_workflow)

        if writer_plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            rows = await _fetch_rows_during_construction(page, allowed_host, read_rows_route)
            resolved_ids: set = set()
            for intent in writer_plan.row_intents:
                matches = [r for r in rows if str(r.get("IdRubrique")) == intent.rubrique_id.value]
                if len(matches) != 1:
                    raise RowAmbiguous("preflight did not find exactly one existing row for a planned rubrique")
                id_devis_det = matches[0].get("IdDevisDet")
                if not isinstance(id_devis_det, int) or isinstance(id_devis_det, bool):
                    raise RowMismatch("preflight resolved a malformed IdDevisDet")
                if id_devis_det in resolved_ids:
                    raise RowAmbiguous("preflight resolved a duplicate IdDevisDet across planned rubriques")
                resolved_ids.add(id_devis_det)
                pec_row_map[intent.rubrique_id.value] = id_devis_det

        controller.activate_write_once()
    except Exception:
        controller.abort_deny_all()
        await context.close()
        raise

    return VerifiedMissionWriter(
        _CONSTRUCTION_TOKEN,
        context,
        page,
        abort_handle,
        lease_handle,
        expected_identity,
        writer_plan,
        allowed_host,
        read_rows_route,
        pec_row_map,
    )
