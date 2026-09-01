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
from mcma.domain.enums import FormFieldSelector, RepairWorkflow
from mcma.domain.normalize import normalize_text
from mcma.domain.rubriques import RUBRIQUE_CATALOG
from mcma.domain.values import FormFieldIntent, RubriqueId
from mcma.portal.capabilities import LeaseHandle, SearchIdentifiers
from mcma.portal.contracts import RouteContract, contracts_for_workflow
from mcma.portal.mode_normal_live import ModeNormalLiveDriver
from mcma.portal.mode_normal_live import (
    READ_FINANCIAL_SUMMARY_JS as _NORMAL_SUMMARY_JS,
)
from mcma.portal.pec_live import PecLiveDriver, UnmatchedRubrique, match_all_rubriques
from mcma.portal.pec_live import (
    READ_FINANCIAL_SUMMARY_JS as _PEC_SUMMARY_JS,
)
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
    # Correction batch (section 7, pilot-integration): the five
    # confirmed non-table header fields for THIS workflow. Empty by
    # default -- existing callers/tests that never plan a form field are
    # unaffected.
    form_field_intents: Tuple[FormFieldIntent, ...] = ()

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

        form_field_intents = tuple(self.form_field_intents)
        object.__setattr__(self, "form_field_intents", form_field_intents)
        if not all(isinstance(i, FormFieldIntent) for i in form_field_intents):
            raise TypeError("WriterPlanData.form_field_intents must contain only FormFieldIntent")
        seen_selectors: set = set()
        for intent in form_field_intents:
            if intent.selector in seen_selectors:
                raise ValueError("duplicate FormFieldSelector in WriterPlanData")
            seen_selectors.add(intent.selector)
            # Workflow applicability explicit (section 7 design
            # requirement): a field planned for a DIFFERENT workflow than
            # this WriterPlanData's own can never silently reach the DOM.
            if self.repair_workflow not in intent.applicable_workflows:
                raise ValueError(
                    f"FormFieldIntent {intent.selector!r} is not applicable to {self.repair_workflow!r}"
                )

    def intent_for(self, rubrique_id: RubriqueId) -> Optional[PortalRowIntent]:
        for intent in self.row_intents:
            if intent.rubrique_id == rubrique_id:
                return intent
        return None

    def planned_rubrique_values(self) -> frozenset:
        return frozenset(i.rubrique_id.value for i in self.row_intents)

    def label_for(self, rubrique_id: RubriqueId) -> str:
        """The catalog label for a planned rubrique.

        PEC matches the garage's Table 2 rows by their DISPLAYED label,
        which is what the golden implementation did -- the real table
        exposes no rubrique id per row. RUBRIQUE_CATALOG is the same
        source the golden code fell back to."""
        return RUBRIQUE_CATALOG.get(rubrique_id.value, "")


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


class AccountNotMcmaWritable(WriteAborted):
    """Correction batch (owner amendment, MAMDA read-only enforcement,
    defense-in-depth layer 3): raised before any browser context exists,
    either because require_mcma_writer_account() itself was called with a
    non-MCMA/inactive account, or because open_verified_writer() was
    handed an McmaWriterAccountContext whose account_id does not match the
    LeaseHandle actually being used."""


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
# McmaWriterAccountContext -- MAMDA read-only enforcement, layer 3
# (correction batch / owner amendment). mcma.portal must never import
# mcma.persistence (sibling layers) -- this module cannot look up an
# account's entity itself. Instead, open_verified_writer() refuses to
# accept a bare account_id/LeaseHandle: it requires this typed context,
# constructible ONLY via require_mcma_writer_account() below, which takes
# the entity/active SCALARS the caller (mcma.execution, which DOES import
# mcma.persistence and has just re-read the row) already looked up. A
# generic account identifier alone can never reach the writer factory.
# --------------------------------------------------------------------- #

_MCMA_WRITER_ACCOUNT_TOKEN = object()


class McmaWriterAccountContext:
    """Carries only an account_id -- never credentials or session material.
    Its mere existence attests that require_mcma_writer_account() already
    confirmed entity=='MCMA' and active=True for THIS account_id. Like
    VerifiedMissionWriter's construction_token (see that class's
    docstring), this is an API-usability safeguard, not a cryptographic
    boundary -- Python provides no true private construction.

    Fable-review-2 correction (LOW finding): this was previously a frozen
    @dataclass, which `dataclasses.replace(ctx, account_id="other")`
    could use to mint a context for an ARBITRARY account_id while
    carrying over the original's valid `_token` (replace() copies every
    field not explicitly overridden, private ones included). A plain
    __slots__ class -- the exact idiom VerifiedMissionWriter's own
    _CONSTRUCTION_TOKEN already uses -- has no dataclass machinery for
    `replace()` to operate on at all."""

    __slots__ = ("account_id", "_token")

    def __init__(self, account_id: str, token: object) -> None:
        if token is not _MCMA_WRITER_ACCOUNT_TOKEN:
            raise RuntimeError(
                "McmaWriterAccountContext must be constructed via require_mcma_writer_account()"
            )
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "_token", token)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"McmaWriterAccountContext is immutable (cannot set {name!r})")


def require_mcma_writer_account(account_id: str, *, entity: str, active: bool) -> McmaWriterAccountContext:
    """The ONLY way to construct an McmaWriterAccountContext. `entity` and
    `active` must come from a fresh read of the accounts row (never a
    cached/assumed value) -- MAMDA supports notifications only and must
    never reach a writer (SAFETY_MODEL.md correction batch, defense in
    depth layer 3; layers 1/2 are the API and mcma.execution's own
    independent re-check, neither of which this module trusts alone)."""
    if entity != "MCMA":
        raise AccountNotMcmaWritable(f"account {account_id!r} is not an MCMA account (entity={entity!r})")
    if not active:
        raise AccountNotMcmaWritable(f"account {account_id!r} is not active")
    return McmaWriterAccountContext(account_id, _MCMA_WRITER_ACCOUNT_TOKEN)


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

    def record_native_calculation(self, expected: FinancialSummary) -> None:
        """Called after the PORTAL'S OWN calculation functions have run.

        Replaces record_trigger() on the live path. record_trigger relied
        on a server envelope carrying calculation_version and an expected
        summary; that envelope is the mock's invention and the real portal
        computes in the page, so there is nothing equivalent to receive.

        BE CLEAR ABOUT WHAT THIS LOSES. The monotonic version counter is
        gone, so a portal that silently returned a cached result would no
        longer be caught by a version that failed to advance. What IS kept
        is the property that actually guards against writing stale
        figures: the summary read immediately after the trigger is stored
        against the current row_generation, verify_fresh() re-reads it
        independently, and any mutation in between still raises
        NativeCalculationStale. Detecting a cached recalculation is now a
        job for the onsite capture, not something this can assert."""
        self._evidence = _CalculationEvidence(self.row_generation, 0, expected)

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

_READ_TVA_RECUPERABLE_TOGGLE_JS = """() => {
    const el = document.getElementById('DevisTvaRecupI');
    return el ? !!el.checked : null;
}"""

def _financial_summary_from_dom(values: dict) -> FinancialSummary:
    """Builds the summary from the PORTAL'S OWN fields.

    The previous reader pulled seven of nine values from
    `[data-mock-only-*]` attributes -- deliberately synthetic markers that
    exist only in this repository's mock, so the production path could
    never have read a real summary at all. The golden commits read the
    portal's real ids, and those are what the drivers return.

    A missing field is an error rather than a zero: a summary with silent
    zeroes in it would compare equal to nothing and pass verification."""
    def money(name):
        raw = values.get(name)
        if raw is None or str(raw).strip() == "":
            raise ValueError(f"financial summary field {name!r} was not present")
        return Money.of(str(raw))

    return FinancialSummary(
        montant_charge_mutuelle=money("charge_mutuelle"),
        montant_charge_societaire=money("charge_societaire"),
        total_tva=money("total_tva"),
        total_ttc=money("total_ttc"),
        vetuste=money("vetuste"),
        franchise=money("franchise"),
        remise=money("remise"),
        montant_arrete=money("montant_arrete"),
        base_indemnite=money("base_indemnite"),
    )


_DISPATCH_CHANGE_JS = """(id) => {
    const el = document.getElementById(id);
    if (el) { el.dispatchEvent(new Event('change', {bubbles: true})); }
}"""

# Mode Normal persisted rows, read from the rendered table the golden
# commit used (#tableRapportDet / table.dataTable). Column order follows
# the portal's own layout: rubrique, HT, taxe.
_READ_NORMAL_ROWS_JS = """() => {
    const rows = document.querySelectorAll(
        '#tableRapportDet tbody tr, table.dataTable tbody tr'
    );
    const out = [];
    rows.forEach((tr, index) => {
        if (tr.querySelector('#MontantHT, #IdRubrique')) return;  // the editing row
        const tds = tr.querySelectorAll('td');
        const cell = i => (tds[i] ? (tds[i].innerText || '').trim() : '');
        // Column order is the portal's own header: Rubrique | HT | Taxe |
        // TTC | Taux Vet. | Mt Vet. | Action.
        out.push({
            index: index,
            rubrique_cell: cell(0),
            MontantHT: cell(1),
            Taxe: cell(2)
        });
    });
    return out;
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
        # Golden DOM drivers. Declared here because __slots__ is a
        # deliberate guard against ad-hoc attributes on a safety-critical
        # object, and these are not an exception to it.
        "_normal_driver",
        "_pec_driver",
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
        # Golden drivers own the DOM mechanics; this writer keeps every
        # authorization decision and calls them only once a mutation is
        # permitted.
        self._normal_driver = ModeNormalLiveDriver(page)
        self._pec_driver = PecLiveDriver(page)

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
        """Reads the rows the portal is actually displaying.

        This used to fetch a JSON endpoint that returns a tidy list with
        IdRubrique and IdDevisDet on every row. No such endpoint exists on
        SinAuto -- it is a convenience this repository's mock invented, and
        neither golden commit uses one. Both golden implementations read
        the rendered table, so that is what happens here."""
        try:
            if self._writer_plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
                rows = await self._pec_driver.enumerate_rows()
            else:
                rows = await self._page.evaluate(_READ_NORMAL_ROWS_JS)
        except Exception:
            await self._terminal_abort(RowWriteUncertain("could not read the current rows"))
        return list(rows) if isinstance(rows, list) else []

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
        planned_labels = {
            normalize_text(self._writer_plan.label_for(i.rubrique_id))
            for i in self._writer_plan.row_intents
        }
        for row in rows:
            cell = str(row.get("rubrique_cell", "")).strip()
            if cell not in planned and normalize_text(cell) not in planned_labels:
                await self._terminal_abort(UnplannedExistingRow("an unplanned existing row is present"))

        matches = [r for r in rows if self._row_matches(r, rubrique_id)]
        if len(matches) == 1:
            existing = matches[0]
            if Money.of(str(existing.get("MontantHT", ""))) == intent.ht and Money.of(
                str(existing.get("Taxe", ""))
            ) == intent.tva:
                return  # already satisfied -- no-op
            await self._terminal_abort(RowMismatch("an existing row disagrees with the approved intent"))
        elif len(matches) > 1:
            await self._terminal_abort(RowAmbiguous("multiple existing rows match this rubrique"))

        # Live-tested SinAuto interaction recovered from 9a2c57c. The
        # mutation itself is the golden DOM lifecycle: check #VehRepareI,
        # click the real Ajouter control, fill the unsuffixed row fields
        # with the golden event cascade, then click the 7th-column
        # checkmark by both golden methods and wait for the AJAX redraw.
        #
        # It is deliberately NOT gated on a network response.
        # createRapportDefDet appears in NEITHER golden commit -- only in
        # this repository's mock -- so requiring it would abort a write
        # that actually succeeded. The read-back below is what decides.
        try:
            await self._normal_driver.add_rubrique_row(
                intent.rubrique_id.value, str(intent.ht.amount), str(intent.tva.amount)
            )
        except Exception:
            await self._terminal_abort(RowWriteUncertain("the golden row lifecycle did not complete"))

        self._ledger.record_mutation()

        # Verification is now the ONLY evidence the write landed, so it is
        # exact: the row must exist once, with both amounts equal.
        fresh_rows = await self._fetch_rows()
        # The first column is whatever the portal DISPLAYS there: the mock
        # renders the numeric id, the real page renders the label. Matching
        # on only one of them would pass here and fail against SinAuto, so
        # both are accepted -- the same reason PEC matches by label.
        persisted = [
            r
            for r in fresh_rows
            if self._row_matches(r, rubrique_id)
            and Money.of(str(r.get("MontantHT", ""))) == intent.ht
            and Money.of(str(r.get("Taxe", ""))) == intent.tva
        ]
        if len(persisted) != 1:
            await self._terminal_abort(
                RowReadBackMismatch("the row was not present exactly once after the checkmark")
            )

        await self._recheck_lease()

    # -- Garage Conventionne / PEC ---------------------------------------

    async def edit_conventionne_row(self, rubrique_id: RubriqueId) -> None:
        self._ensure_open()
        if self._writer_plan.repair_workflow is not RepairWorkflow.GARAGE_CONVENTIONNE:
            await self._terminal_abort(WriteAborted("edit_conventionne_row requires a GARAGE_CONVENTIONNE writer"))
        intent = self._writer_plan.intent_for(rubrique_id)
        if intent is None:
            await self._terminal_abort(UnplannedRubrique("rubrique_id is not in the approved plan"))
        target_label = self._pec_row_map.get(rubrique_id.value)
        if target_label is None:
            await self._terminal_abort(UnplannedRubrique("rubrique_id was not matched during preflight"))

        await self._preflight_before_mutation()

        # Live-tested PEC interaction recovered from 8e5e4e6. The row is
        # re-located by its DISPLAYED LABEL every time, never by an index
        # kept from before the last redraw -- the table is rebuilt after
        # each save, so a stale index is a reference to a different row.
        live_index = await self._pec_driver.relocate_row(target_label)
        if live_index < 0:
            await self._terminal_abort(RowAmbiguous("the planned row is no longer present in Table 2"))

        rows = await self._fetch_rows()
        current = next((r for r in rows if r.get("index") == live_index), None)
        if current is None:
            await self._terminal_abort(RowAmbiguous("the relocated row could not be read back"))

        if (
            Money.of(str(current.get("current_ht", ""))) == intent.ht
            and Money.of(str(current.get("current_taxe", ""))) == intent.tva
        ):
            return  # diff-before-write: already exactly equal -- no-op

        pencil = await self._pec_driver.click_pencil(live_index)
        if not pencil.get("ok"):
            await self._terminal_abort(RowWriteUncertain("could not open the row for editing"))

        expected_rate = derive_vetuste_rate(intent.ht, intent.vetuste)
        filled = await self._pec_driver.fill_editing_row(
            str(intent.ht.amount),
            str(intent.tva.amount),
            "" if expected_rate is None else str(expected_rate),
            str(intent.vetuste.amount),
        )
        if not filled.get("ht", {}).get("found") or not filled.get("taxe", {}).get("found"):
            await self._terminal_abort(RowWriteUncertain("the editable row fields were not present"))

        # The ONLY network fact the golden code established is that a
        # response arrives whose URL CONTAINS "updateDevisDet". It never
        # asserted the path, the method or a JSON body, so none of those
        # are required -- and a missing response is not treated as failure,
        # because the golden code fell back to clicking directly and let
        # the read-back decide. Which is exactly what happens below.
        await self._pec_driver.click_save_and_await_update(live_index)

        self._ledger.record_mutation()

        # Re-locate again after the redraw, then verify exactly.
        verify_index = await self._pec_driver.relocate_row(target_label)
        if verify_index < 0:
            await self._terminal_abort(RowReadBackMismatch("the row vanished after saving"))
        fresh_rows = await self._fetch_rows()
        persisted = next((r for r in fresh_rows if r.get("index") == verify_index), None)
        if persisted is None:
            await self._terminal_abort(RowReadBackMismatch("the saved row could not be read back"))
        if Money.of(str(persisted.get("current_ht", ""))) != intent.ht:
            await self._terminal_abort(RowReadBackMismatch("MontantHT"))
        if Money.of(str(persisted.get("current_taxe", ""))) != intent.tva:
            await self._terminal_abort(RowReadBackMismatch("Taxe"))

        await self._recheck_lease()

    # -- Read-back / verification (shared) --------------------------------

    def _row_matches(self, row: dict, rubrique_id: RubriqueId) -> bool:
        """Does this displayed row belong to this rubrique?

        Mode Normal reads the rendered table, whose first column is
        whatever the portal PRINTS there -- the numeric id in the mock,
        the label on the real page. PEC rows carry only a label. Matching
        on one or the other alone would pass in one environment and fail
        in the other, so both are accepted, and the label comparison is
        normalized exactly as PEC's is."""
        expected_label = normalize_text(self._writer_plan.label_for(rubrique_id))
        for key in ("rubrique_cell", "rubrique_label", "IdRubrique"):
            raw = row.get(key)
            if raw is None:
                continue
            value = str(raw).strip()
            if value == rubrique_id.value:
                return True
            if expected_label and normalize_text(value) == expected_label:
                return True
        return False

    async def read_row(self, rubrique_id: RubriqueId) -> dict:
        """Never a first-row/positional fallback -- zero or multiple
        matches for this rubrique fails closed."""
        self._ensure_open()
        rows = await self._fetch_rows()
        matches = [r for r in rows if self._row_matches(r, rubrique_id)]
        if len(matches) != 1:
            await self._terminal_abort(RowAmbiguous("read_row did not find exactly one matching row"))
        return dict(matches[0])

    async def verify_row(self, rubrique_id: RubriqueId) -> None:
        self._ensure_open()
        intent = self._writer_plan.intent_for(rubrique_id)
        if intent is None:
            await self._terminal_abort(UnplannedRubrique("rubrique_id is not in the approved plan"))
        row = await self.read_row(rubrique_id)
        # PEC rows come from the golden enumerator (current_ht/current_taxe);
        # Mode Normal rows from the rendered table (MontantHT/Taxe).
        ht_raw = row.get("MontantHT", row.get("current_ht", ""))
        taxe_raw = row.get("Taxe", row.get("current_taxe", ""))
        if Money.of(str(ht_raw)) != intent.ht:
            await self._terminal_abort(RowReadBackMismatch("MontantHT"))
        if Money.of(str(taxe_raw)) != intent.tva:
            await self._terminal_abort(RowReadBackMismatch("Taxe"))
        if self._writer_plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            vetuste_raw = row.get("MontantVetuste", row.get("current_vetuste", ""))
            if Money.of(str(vetuste_raw)) != intent.vetuste:
                await self._terminal_abort(RowReadBackMismatch("MontantVetuste"))
            ttc = intent.ht + intent.tva
            try:
                expected_rate = derive_vetuste_rate(intent.vetuste, ttc)
            except VetusteRateDerivationUndefined:
                expected_rate = None
            if expected_rate is not None:
                try:
                    taux_raw = row.get("TauxVetuste", row.get("current_taux_vetuste", ""))
                    if Decimal(str(taux_raw)) != expected_rate:
                        await self._terminal_abort(RowReadBackMismatch("TauxVetuste"))
                except Exception:
                    await self._terminal_abort(RowReadBackMismatch("TauxVetuste"))

    # -- Non-table header fields (section 7, pilot-integration correction) -

    async def fill_form_fields(self) -> None:
        """Fills every FormFieldIntent from the approved plan (zero or
        more -- a plan with none is a legitimate no-op) via real DOM
        events (Playwright .fill()/.select_option(), which dispatch the
        same input/change events a human's keystrokes would). Fixed
        selector allowlist only (FormFieldSelector's enum members) --
        this method cannot be called with a caller-supplied selector
        string; the intents come entirely from the already-approved
        WriterPlanData. No direct charge-mutuelle/sociétaire or final-
        action selector exists in FormFieldSelector's member list, so
        neither can ever reach this method."""
        self._ensure_open()
        for intent in self._writer_plan.form_field_intents:
            await self._fill_one_form_field(intent)
        await self._recheck_lease()

    async def _fill_one_form_field(self, intent: FormFieldIntent) -> None:
        selector = f"#{intent.selector.value}"
        locator = self._page.locator(selector)
        try:
            count = await locator.count()
        except Exception:
            await self._terminal_abort(RowWriteUncertain(f"could not locate {selector}"))
        if count != 1:
            await self._terminal_abort(RowAmbiguous(f"{selector} is not scoped to exactly one element"))
        try:
            tag_name = await locator.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            await self._terminal_abort(RowWriteUncertain(f"could not inspect {selector}"))
        try:
            if tag_name == "select":
                await locator.select_option(intent.value)
            else:
                await locator.fill(intent.value)
        except Exception:
            await self._terminal_abort(RowWriteUncertain(f"could not fill {selector}"))

    async def verify_form_fields(self) -> None:
        """Exact DOM read-back (section 7 design requirement) BEFORE
        READY_FOR_HUMAN_REVIEW -- an INDEPENDENT fresh read of each
        planned field, never the value verify_row/fill_form_fields
        already held in memory. Non-table fields may not persist until
        the human performs the manual portal action, which is exactly
        why the browser stays open through READY_FOR_HUMAN_REVIEW/
        AWAITING_HUMAN_CONFIRMATION rather than being closed here."""
        self._ensure_open()
        for intent in self._writer_plan.form_field_intents:
            selector = f"#{intent.selector.value}"
            locator = self._page.locator(selector)
            try:
                observed = await locator.evaluate("el => el.value")
            except Exception:
                await self._terminal_abort(RowReadBackMismatch(f"could not read back {selector}"))
            if observed != intent.value:
                await self._terminal_abort(RowReadBackMismatch(f"{selector} read-back mismatch"))

    # -- Native financial calculation -------------------------------------

    async def trigger_native_recalc(self) -> None:
        """Invokes the PORTAL'S OWN calculation functions.

        Both workflows are supported now. Mode Normal used to abort with
        NativeCalculationUnconfirmed unconditionally, on the belief that no
        mechanism was known -- but 9a2c57c contains one that was exercised
        successfully against real dossiers (CalculerMontantDommage,
        CalculerMntArrete, CalculerMontantTTC, CalculerMontantVetuste plus
        an event sweep), and PEC's DevisCalculerMontantCharge() likewise
        comes from 8e5e4e6.

        No mock endpoint is involved. The previous implementation required
        a POST to /_mock/pec/native_calculation returning a JSON envelope;
        that endpoint exists only in this repository's mock and the real
        portal computes in the page. What is asserted instead is that the
        function was actually present and ran -- a portal that does not
        expose it fails closed rather than silently skipping the step.

        This never writes the charge split. #MontantChargeMutuelle and
        #MontantChargeSocietaire are the portal's to compute and are only
        ever read back (BUSINESS_RULES.md B.3), even though the golden
        Mode Normal source wrote them directly.
        """
        self._ensure_open()
        await self._preflight_before_mutation()

        driver = (
            self._normal_driver
            if self._writer_plan.repair_workflow is RepairWorkflow.MODE_NORMAL
            else self._pec_driver
        )
        try:
            result = await driver.trigger_native_calculations()
        except Exception:
            await self._terminal_abort(
                NativeCalculationMissing("the portal's calculation functions could not be invoked")
            )

        if self._writer_plan.repair_workflow is RepairWorkflow.GARAGE_CONVENTIONNE:
            state = (result or {}).get("devisCalc")
            if state == "not_present":
                await self._terminal_abort(
                    NativeCalculationMissing("DevisCalculerMontantCharge is not present on this page")
                )
            if state != "executed":
                await self._terminal_abort(
                    NativeCalculationFailed("DevisCalculerMontantCharge did not complete")
                )

        try:
            summary = _financial_summary_from_dom(await driver.read_financial_summary())
        except Exception:
            await self._terminal_abort(
                NativeCalculationIncomplete("the portal's financial summary could not be read")
            )
        self._ledger.record_native_calculation(summary)

    async def read_financial_summary(self):
        """The portal's own summary, plus the TVA-recoverable toggle.

        Reads the REAL portal ids the golden commits used. The previous
        implementation pulled seven of nine values from
        `[data-mock-only-*]` attributes, so this method could never have
        worked against SinAuto at all."""
        self._ensure_open()
        driver = (
            self._normal_driver
            if self._writer_plan.repair_workflow is RepairWorkflow.MODE_NORMAL
            else self._pec_driver
        )
        try:
            values = await driver.read_financial_summary()
            summary = _financial_summary_from_dom(values)
        except Exception:
            await self._terminal_abort(
                NativeCalculationIncomplete("the portal's financial summary could not be read")
            )
        try:
            tva_recuperable = await self._page.evaluate(_READ_TVA_RECUPERABLE_TOGGLE_JS)
        except Exception:
            tva_recuperable = None
        return summary, tva_recuperable

    async def verify_financial_summary(self) -> FinancialSummary:
        self._ensure_open()
        driver = (
            self._normal_driver
            if self._writer_plan.repair_workflow is RepairWorkflow.MODE_NORMAL
            else self._pec_driver
        )
        try:
            # Read INDEPENDENTLY -- never the value captured at trigger time.
            summary = _financial_summary_from_dom(await driver.read_financial_summary())
        except Exception:
            await self._terminal_abort(
                NativeCalculationIncomplete("the portal's financial summary could not be re-read")
            )
        try:
            self._ledger.verify_fresh(summary)
        except WriteAborted as exc:
            await self._terminal_abort(exc)
        return summary

    # -- lifecycle --------------------------------------------------------

    @property
    def is_closed(self) -> bool:
        """True once close() has been called on this writer. Read-only:
        exposes no context/page object and cannot drive anything."""
        return self._closed

    @property
    def is_terminally_aborted(self) -> bool:
        """True once this writer has aborted itself (policy deny-all
        engaged, context being closed by _terminal_abort). Read-only.

        Pilot-runner correction (section 4): _terminal_abort sets this
        BEFORE awaiting context.close(), so a close-callback subscriber
        can always distinguish "the writer tore itself down and the write
        path is already recording the outcome" from "the employee closed
        the review window". Without that distinction both look identical
        from context.on('close'), and an internal abort would race a
        write-failure transition against a browser-closed transition for
        the same job."""
        return self._terminally_aborted

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._context.close()
        except Exception:
            pass

    def register_close_callback(self, on_close) -> None:
        """Pilot-integration correction (section 4): the ONE way a caller
        can observe this writer's browser context closing (the employee
        closing the window themselves) without ever holding the context
        object -- a thin passthrough to Playwright's own context.on(
        "close", ...). Satisfies mcma.execution.browser_handoff.
        BrowserHandle's Protocol shape exactly (structurally, no import),
        so a VerifiedMissionWriter can be registered with
        ActiveReviewRegistry directly. This is a subscription, not
        access: `on_close` receives no arguments and cannot inspect or
        drive the context/page in any way."""
        self._context.on("close", lambda *_: on_close())


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
    writer_account: McmaWriterAccountContext,
    context_options: dict | None = None,
) -> VerifiedMissionWriter:
    if not isinstance(writer_plan, WriterPlanData):
        raise TypeError("open_verified_writer() requires a WriterPlanData")
    if not isinstance(expected_identity, ExpectedIdentity):
        raise TypeError("open_verified_writer() requires an ExpectedIdentity")
    if not isinstance(writer_account, McmaWriterAccountContext):
        raise TypeError(
            "open_verified_writer() requires an McmaWriterAccountContext -- "
            "see require_mcma_writer_account() (MAMDA read-only enforcement, layer 3)"
        )
    if writer_account.account_id != lease_handle.account_id:
        raise AccountNotMcmaWritable(
            f"writer_account.account_id {writer_account.account_id!r} does not match "
            f"lease_handle.account_id {lease_handle.account_id!r}"
        )

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
            # Live-tested PEC preflight recovered from 8e5e4e6. The garage's
            # rows are matched by their DISPLAYED LABEL -- exact, then a
            # known alias, then a substring relation -- because the real
            # Table 2 does not expose an IdRubrique or IdDevisDet per row.
            # The previous implementation required both, which is a
            # convenience this repository's mock invented.
            #
            # All-or-nothing, and BEFORE write is activated: if one planned
            # rubrique has no row, the writer never becomes usable at all.
            # Half-editing a dossier because the fourth line had no match is
            # worse than editing none of it, and the portal has no undo.
            pec_driver = PecLiveDriver(page)
            if not await pec_driver.table_present():
                raise RowAmbiguous("Table 2 (#DevisDetTableVal) is not present on this mission")
            table_rows = await pec_driver.enumerate_rows()
            if not table_rows:
                raise RowAmbiguous("Table 2 is present but has no rows to edit")
            planned = [
                (intent.rubrique_id.value, writer_plan.label_for(intent.rubrique_id))
                for intent in writer_plan.row_intents
            ]
            try:
                matches = match_all_rubriques(planned, table_rows)
            except UnmatchedRubrique as exc:
                raise RowAmbiguous(str(exc)) from exc
            for match in matches:
                pec_row_map[match["rubrique_id"]] = match["target_label"]

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
