"""
mcma.portal.capabilities -- LoginCapability and ReadCapability (INC-08,
ADR-0003, SAFETY_MODEL.md §1).

Neither capability exposes a write method, a generic request()/evaluate()
method, the raw BrowserContext/Page, or any path to a writer.
VerifiedMissionWriter and identity verification are INC-09 and do not exist
here. Persistence, lease acquisition, and the DPAPI session vault are
INC-11/INC-13 and are not implemented here either -- LoginCapability does
not acquire, hold, or validate an account lease at all (SAFETY_MODEL.md §1
defines its constructor as `portal.open_login_session(account_id)`, with no
LeaseHandle); it produces only in-memory SessionMaterial and cannot store or
replace a stored session -- that happens later, lease-guarded, in the
INC-13 vault write path (SAFETY_MODEL.md §7). ReadCapability DOES receive a
LeaseHandle and validates it via `assert_valid()` before any context is
created, but this module still never acquires or persists a lease itself.

The four ReadCapability operations (search/open/scrape/read_rows) are
deliberately narrow: typed/validated caller input only, fixed internal
routes and scripts, caller data passed only as serialized page.evaluate()
arguments -- never interpolated into script text, a route, or a selector.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, Sequence, runtime_checkable
from urllib.parse import quote

from mcma.domain.enums import RepairWorkflow
from mcma.portal.contracts import RouteContract
from mcma.portal.final_endpoints import is_permanently_blocked
from mcma.portal.session import open_guarded_context

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.async_api import Browser


# --------------------------------------------------------------------- #
# Shared contract-scope guard
# --------------------------------------------------------------------- #


def _require_only_capability(contracts: Sequence[RouteContract], expected_capability: str) -> None:
    """Fail closed BEFORE any browser context is created if a contract is
    outside its capability's allowed scope, or targets a permanently
    blocked route (defense in depth on top of the per-request check that
    already runs on every live request -- mcma.portal.contracts.
    evaluate_request)."""
    for contract in contracts:
        if contract.capability != expected_capability:
            raise ValueError(
                f"contract capability {contract.capability!r} is not allowed here "
                f"(expected only {expected_capability!r}): {contract.route}"
            )
        if is_permanently_blocked(contract.route):
            raise ValueError(f"contract route is permanently blocked: {contract.route!r}")


def _validate_positive_finite(value, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive, finite number: {value!r}")


# --------------------------------------------------------------------- #
# LeaseHandle (INC-08 amendment #2 -- account_id alone does not prove
# ownership; assert_valid() is the structural proof this module requires)
# --------------------------------------------------------------------- #


@runtime_checkable
class LeaseHandle(Protocol):
    """Structural placeholder for the per-account lease handle acquired by
    execution via persistence (INC-11). This module never acquires,
    reacquires, or persists a lease -- it only threads one through and
    calls assert_valid() before creating any context."""

    account_id: str

    async def assert_valid(self) -> None:
        """Raises if the lease is not currently valid/held."""
        ...


class LeaseInvalid(Exception):
    def __init__(self, account_id: str):
        super().__init__(f"lease for account {account_id!r} is not valid")
        self.account_id = account_id


# --------------------------------------------------------------------- #
# SessionMaterial (INC-08 amendment #1)
# --------------------------------------------------------------------- #


class SessionMaterial:
    """In-memory-only session material produced by
    LoginCapability.perform_manual_login (SAFETY_MODEL.md §7 correction
    #6): the human performs the login and OTP themselves; this only
    captures the resulting browser storage state. Never persisted here.

    Deliberately has no JSON serialization, no file-writing method, a
    redacted repr/str (storage state never appears), and no public
    `storage_state` attribute -- so cookies/tokens cannot leak into logs,
    debuggers, or exception text. `consume_for_handoff()` is the single
    explicit operation the future INC-13 vault uses to take the raw
    material once for validation/encryption; a second call raises rather
    than handing the material out again."""

    __slots__ = ("_account_id", "_storage_state", "_consumed")

    def __init__(self, account_id: str, storage_state: dict):
        self._account_id = account_id
        self._storage_state = storage_state
        self._consumed = False

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def consumed(self) -> bool:
        return self._consumed

    def consume_for_handoff(self) -> dict:
        if self._consumed:
            raise RuntimeError(
                f"SessionMaterial for account {self._account_id!r} was already consumed"
            )
        self._consumed = True
        return self._storage_state

    def __repr__(self) -> str:
        return f"SessionMaterial(account_id={self._account_id!r}, consumed={self._consumed})"

    def __str__(self) -> str:
        return self.__repr__()


# --------------------------------------------------------------------- #
# LoginCapability (INC-08 amendment #6 -- narrow, onboarding-only)
# --------------------------------------------------------------------- #

_LOGIN_ROUTE = "/SinAuto_MCMA/login"
_LOGGED_IN_MARKER_JS = """(selectors) => selectors.some(sel => document.querySelector(sel) !== null)"""
LOGGED_IN_MARKERS = ("#formRecherche", "#ReferenceCie", "a[href*='logout']")


class LoginTimedOut(Exception):
    def __init__(self, account_id: str):
        super().__init__(f"manual login for account {account_id!r} timed out")
        self.account_id = account_id


class LoginCapability:
    """Desktop onboarding tool only (SAFETY_MODEL.md §1). Navigates ONLY to
    its fixed reviewed login route and polls ONLY the fixed logged-in
    markers above. It never accepts a credential argument, never fills a
    form, never accepts an arbitrary URL/selector, and never opens a
    mission page -- the human performs login and OTP themselves."""

    def __init__(self, context, page, account_id: str):
        self._context = context
        self._page = page
        self._account_id = account_id
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("LoginCapability is closed")

    async def perform_manual_login(
        self,
        *,
        poll_interval_seconds: float = 1.0,
        timeout_seconds: float = 300.0,
        sleep=None,
    ) -> SessionMaterial:
        self._ensure_open()
        _validate_positive_finite(poll_interval_seconds, "poll_interval_seconds")
        _validate_positive_finite(timeout_seconds, "timeout_seconds")
        sleep = sleep or asyncio.sleep
        elapsed = 0.0
        while True:
            if await self._is_logged_in():
                storage_state = await self._context.storage_state()
                return SessionMaterial(self._account_id, storage_state)
            if elapsed >= timeout_seconds:
                raise LoginTimedOut(self._account_id)
            await sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds

    async def _is_logged_in(self) -> bool:
        return bool(await self._page.evaluate(_LOGGED_IN_MARKER_JS, list(LOGGED_IN_MARKERS)))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._context.close()


async def open_login_session(
    browser: "Browser",
    account_id: str,
    contracts: Sequence[RouteContract],
    allowed_host: str,
    *,
    context_options: dict | None = None,
) -> LoginCapability:
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("account_id must be a non-empty string")
    frozen_contracts = tuple(contracts)
    _require_only_capability(frozen_contracts, "auth")
    context = await open_guarded_context(browser, frozen_contracts, allowed_host, context_options)
    try:
        page = await context.new_page()
        await page.goto(f"http://{allowed_host}{_LOGIN_ROUTE}")
    except Exception:
        await context.close()
        raise
    return LoginCapability(context, page, account_id)


# --------------------------------------------------------------------- #
# ReadCapability (INC-08 amendment #3 -- no generic escape hatches)
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class SearchIdentifiers:
    """Typed/validated search input -- never a raw caller-supplied dict."""

    matricule: str = ""
    reference_cie: str = ""

    def __post_init__(self):
        if not isinstance(self.matricule, str) or not isinstance(self.reference_cie, str):
            raise TypeError("SearchIdentifiers fields must be strings")
        if not self.matricule.strip() and not self.reference_cie.strip():
            raise ValueError("SearchIdentifiers requires at least one non-empty identifier")


class ApprovedField(Enum):
    """The closed set of scrapeable fields; each maps internally to one
    fixed, reviewed CSS selector -- a caller never supplies a selector."""

    MATRICULE_VEH = "MATRICULE_VEH"
    REFERENCE_DOSSIER = "REFERENCE_DOSSIER"
    MODE_REPARATION = "MODE_REPARATION"
    REF_SINISTRE = "REF_SINISTRE"


_APPROVED_FIELD_SELECTORS = {
    ApprovedField.MATRICULE_VEH: "#MatriculeVeh",
    ApprovedField.REFERENCE_DOSSIER: "#ReferenceDossier",
    ApprovedField.MODE_REPARATION: "#modeReparation",
    ApprovedField.REF_SINISTRE: "#hdrRefSinistre",
}


class Candidate:
    """An opaque search result. Only mintable by ReadCapability.search() --
    every Candidate carries the owner_token of the specific ReadCapability
    instance that minted it, and ReadCapability.open() rejects any
    Candidate whose token does not match. Deliberately carries no
    route/URL field of any kind: open() derives navigation from
    `id_mission` (a percent-escaped scalar) through one fixed internal
    template only."""

    __slots__ = ("_id_mission", "_matricule", "_reference_mission", "_societaire", "_owner_token")

    def __init__(self, *, id_mission, matricule, reference_mission, societaire, owner_token):
        self._id_mission = id_mission
        self._matricule = matricule
        self._reference_mission = reference_mission
        self._societaire = societaire
        self._owner_token = owner_token

    @property
    def id_mission(self):
        return self._id_mission

    @property
    def matricule(self):
        return self._matricule

    @property
    def reference_mission(self):
        return self._reference_mission

    @property
    def societaire(self):
        return self._societaire


_SEARCH_ROUTE = "/SinAuto_MCMA/expertise/FrontExpert/listeMissions"
_MISSION_DEEP_LINK_TEMPLATE = (
    "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id_sinistre}/rubrique/gestionexpert-index"
)
_ROW_LIST_ROUTES = {
    RepairWorkflow.MODE_NORMAL: "/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
    RepairWorkflow.GARAGE_CONVENTIONNE: "/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet",
}

_FETCH_JSON_JS = """([url, payload]) => fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams(payload).toString()
}).then(r => r.json())"""

_SCRAPE_JS = """(pairs) => {
    const out = {};
    for (const [name, sel] of pairs) {
        const el = document.querySelector(sel);
        out[name] = el ? (el.value !== undefined ? el.value : el.textContent) : null;
    }
    return out;
}"""


class ReadCapability:
    """Deny-by-default (SAFETY_MODEL.md §1). Exposes ONLY search, open,
    scrape, read_rows, and close. No write method, no generic request()/
    evaluate(), no raw context/page, no upgrade-to-writer path. Every
    operation reaches the portal only through a fixed internal route and a
    fixed internal script; caller input is always passed as a serialized
    page.evaluate() argument, never interpolated into script text, a
    route, or a selector."""

    def __init__(self, context, page, allowed_host: str):
        self._context = context
        self._page = page
        self._allowed_host = allowed_host
        self._closed = False
        self._capability_token = object()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ReadCapability is closed")

    def _absolute_url(self, path: str) -> str:
        return f"http://{self._allowed_host}{path}"

    async def _fetch_json(self, route: str, payload: dict) -> dict:
        return await self._page.evaluate(_FETCH_JSON_JS, [self._absolute_url(route), payload])

    async def search(self, identifiers: SearchIdentifiers) -> tuple[Candidate, ...]:
        self._ensure_open()
        if not isinstance(identifiers, SearchIdentifiers):
            raise TypeError("search() requires a SearchIdentifiers instance")
        payload = {"Matricule": identifiers.matricule, "ReferenceCie": identifiers.reference_cie}
        result = await self._fetch_json(_SEARCH_ROUTE, payload)
        rows = result.get("data", []) if isinstance(result, dict) else []
        candidates = []
        for row in rows:
            if not isinstance(row, dict) or "IdMission" not in row:
                continue
            candidates.append(
                Candidate(
                    id_mission=row.get("IdMission"),
                    matricule=row.get("Matricule"),
                    reference_mission=row.get("ReferenceMission"),
                    societaire=row.get("Societaire"),
                    owner_token=self._capability_token,
                )
            )
        return tuple(candidates)

    async def open(self, candidate: Candidate) -> None:
        self._ensure_open()
        if not isinstance(candidate, Candidate):
            raise TypeError("open() only accepts a Candidate, never a caller-supplied URL/string")
        if candidate._owner_token is not self._capability_token:
            raise ValueError(
                "open() only accepts a Candidate returned by this capability's own search()"
            )
        id_segment = quote(str(candidate.id_mission), safe="")
        path = _MISSION_DEEP_LINK_TEMPLATE.format(id_sinistre=id_segment)
        await self._page.goto(self._absolute_url(path))

    async def scrape(self, fields: Sequence[ApprovedField]) -> dict:
        self._ensure_open()
        fields = tuple(fields)
        if isinstance(fields, (str, bytes)) or not fields or not all(
            isinstance(f, ApprovedField) for f in fields
        ):
            raise TypeError("scrape() only accepts one or more ApprovedField members")
        pairs = [(f.value, _APPROVED_FIELD_SELECTORS[f]) for f in fields]
        return await self._page.evaluate(_SCRAPE_JS, pairs)

    async def read_rows(self, workflow: RepairWorkflow) -> tuple[dict, ...]:
        self._ensure_open()
        if not isinstance(workflow, RepairWorkflow):
            raise TypeError("read_rows() requires a RepairWorkflow member")
        route = _ROW_LIST_ROUTES.get(workflow)
        if route is None:  # pragma: no cover - exhaustive today; defensive against future members
            raise ValueError(f"no confirmed row-list route for workflow: {workflow!r}")
        result = await self._fetch_json(route, {})
        data = result.get("data", []) if isinstance(result, dict) else []
        return tuple(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._context.close()


async def open_reader(
    browser: "Browser",
    lease_handle: LeaseHandle,
    contracts: Sequence[RouteContract],
    allowed_host: str,
    *,
    context_options: dict | None = None,
) -> ReadCapability:
    if not isinstance(lease_handle, LeaseHandle):
        raise TypeError("open_reader() requires a LeaseHandle")
    await lease_handle.assert_valid()
    frozen_contracts = tuple(contracts)
    _require_only_capability(frozen_contracts, "read")
    context = await open_guarded_context(browser, frozen_contracts, allowed_host, context_options)
    try:
        page = await context.new_page()
    except Exception:
        await context.close()
        raise
    return ReadCapability(context, page, allowed_host)
