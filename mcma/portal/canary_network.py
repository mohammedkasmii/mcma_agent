"""
mcma.portal.canary_network -- the network policy for the supervised Mode
Normal golden canary ONLY (docs/implementation/execution/
MODE_NORMAL_GOLDEN_CANARY.md).

Why a separate policy exists at all. Every agent-driven context elsewhere
is exact-contract default-deny (mcma.portal.contracts.evaluate_request).
The real SinAuto mission page cannot work under that: it loads its own
jQuery/Select2/DataTables/calculation scripts, and the golden row save
(the 7th-column checkmark, 9a2c57c) fires an AJAX request whose path,
method and body were never captured (LIVE_WRITE_EVIDENCE_MATRIX.md:
UNCONFIRMED_NETWORK_DETAIL). The owner explicitly authorized this bounded
policy for the canary alone; it is never installed by the generic writer,
DRY_RUN, login, PEC or notification paths, which keep their own guards
unchanged.

The policy, phase by phase (anything not listed is DENIED and recorded as
a VIOLATION, which the canary turns into WRITE_ABORTED):

  ALWAYS       exact pinned host over https only; permanently blocked final
               endpoints and charge-split paths denied at every moment; no
               websocket, no sub-frame request, no popup, no other host.
  SEARCH       the exact reviewed search-page document and search POST
               (sinauto_contracts.identity_read_contracts), plus same-host
               static GETs (script/stylesheet/image/font).
  MISSION      the ONE exact mission document authorized for the single
               search candidate, plus same-host static GETs. No XHR/fetch.
  ROW_WINDOW   MISSION, plus same-host XHR/fetch from the top-level page,
               GET/POST only, non-navigation, non-multipart, at most
               ROW_WINDOW_MAX_REQUESTS requests and ROW_WINDOW_MAX_SECONDS
               long. Opened for one planned row immediately before its
               golden checkmark click; closed right after exact read-back.
  REVIEW       after READY_FOR_HUMAN_REVIEW: same-host static GETs only.
  ABORTED      deny everything.

Native calculation never gets a window: it runs in MISSION, so any
request it would emit is denied and becomes a violation.

Evidence. Every decision is recorded as SAFE METADATA only: phase, row
index, method, a normalized path (numeric/opaque segments replaced, query
dropped), resource type, decision, reason code, relative timing, response
status, and request body FIELD NAMES plus a hash of those names. Never a
value, cookie, header, credential, claimant datum or raw body.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence
from urllib.parse import parse_qsl, urlsplit

from mcma.portal.canonical import canonicalize_request
from mcma.portal.contracts import Decision, RouteContract, evaluate_request
from mcma.portal.final_endpoints import is_permanently_blocked
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST

ROW_WINDOW_MAX_REQUESTS = 6
ROW_WINDOW_MAX_SECONDS = 20.0
MAX_EVIDENCE_RECORDS = 500

STATIC_RESOURCE_TYPES = frozenset({"script", "stylesheet", "image", "font"})
WINDOW_RESOURCE_TYPES = frozenset({"xhr", "fetch"})
WINDOW_METHODS = frozenset({"GET", "POST"})

# Charge-split fields are the portal's to compute (BUSINESS_RULES.md B.3).
# Any request whose path names them is denied in every phase.
_CHARGE_SPLIT_PATH_MARKERS = ("chargemutuelle", "chargesocietaire", "montantcharge")


class CanaryPhase(Enum):
    SEARCH = "SEARCH"
    MISSION = "MISSION"
    ROW_WINDOW = "ROW_WINDOW"
    REVIEW = "REVIEW"
    ABORTED = "ABORTED"


class CanaryPolicyError(RuntimeError):
    """A phase transition the policy does not permit (programming error or
    an attempt to widen it out of order). Always fails closed."""


@dataclass(frozen=True)
class RequestFacts:
    """What the policy needs to know about one request -- extracted from a
    Playwright Request by the handler, constructible directly in tests."""

    url: str
    method: str
    resource_type: str
    is_navigation: bool
    is_main_frame: bool
    content_type: Optional[str] = None
    body: Optional[str] = None


@dataclass
class EvidenceRecord:
    phase: str
    row_index: Optional[int]
    method: str
    path: str
    resource_type: str
    decision: str
    reason: str
    t_ms: int
    body_field_names: tuple = ()
    body_fields_hash: Optional[str] = None
    status: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "phase": self.phase, "row_index": self.row_index, "method": self.method,
            "path": self.path, "resource_type": self.resource_type, "decision": self.decision,
            "reason": self.reason, "t_ms": self.t_ms, "body_field_names": list(self.body_field_names),
            "body_fields_hash": self.body_fields_hash, "status": self.status,
        }


# --------------------------------------------------------------------- #
# Safe-metadata helpers
# --------------------------------------------------------------------- #

_SAFE_SEGMENT = re.compile(r"^[A-Za-z_-]{1,64}$")
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,64}$")
_METHOD_RE = re.compile(r"^[A-Z]{1,10}$")

# Dynamic route values are not necessarily numeric.  In particular, a
# portal may use an opaque alphabetic mission/reference value after one of
# these route labels.  The evidence must retain the route *shape*, never
# that value.
_IDENTIFIER_PATH_MARKERS = frozenset({
    "id", "idsinistre", "idmission", "iddossier", "mission", "missions",
    "dossier", "dossiers", "matricule", "immatriculation", "reference",
    "ref", "numero", "number",
})


def normalize_evidence_path(path: str) -> str:
    """Retains route words while replacing a numeric/opaque segment, or a
    value immediately following an identifier route marker, with ``{v}``.

    The second rule matters for values such as ``idSinistre/ABCD``: an
    identifier need not contain a digit to be sensitive.
    """
    segments = [s for s in (path or "").split("/") if s]
    normalized: list[str] = []
    previous_was_identifier_marker = False
    for segment in segments:
        if previous_was_identifier_marker or not _SAFE_SEGMENT.match(segment):
            normalized.append("{v}")
        else:
            normalized.append(segment)
        previous_was_identifier_marker = segment.lower() in _IDENTIFIER_PATH_MARKERS
    return "/" + "/".join(normalized)


def body_field_names(content_type: Optional[str], body: Optional[str]) -> tuple:
    """Top-level field NAMES only, never values. Unparseable or unsafe names
    are dropped (counted as `{unsafe}` once)."""
    if not body:
        return ()
    ctype = (content_type or "").split(";")[0].strip().lower()
    names: list = []
    try:
        if ctype == "application/json":
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                names = [str(k) for k in parsed.keys()]
        elif ctype in ("application/x-www-form-urlencoded", ""):
            names = [k for k, _ in parse_qsl(body, keep_blank_values=True)]
    except Exception:
        return ("{unparsed}",)
    safe = sorted({n for n in names if _SAFE_FIELD_NAME.match(n)})
    if len(safe) != len(set(names)):
        safe.append("{unsafe}")
    return tuple(safe[:50])


def _names_hash(names: tuple) -> Optional[str]:
    if not names:
        return None
    return hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------- #
# The policy
# --------------------------------------------------------------------- #


class ModeNormalCanaryNetworkPolicy:
    """Phased decision engine. Transitions only ever move forward:
    SEARCH -> MISSION -> (ROW_WINDOW <-> MISSION)* -> REVIEW, and any phase
    -> ABORTED (terminal). Satisfies ReadCapability's structural
    `authorize_exact_mission_route` hook, so the production search/open
    path (mcma.portal.capabilities.ReadCapability) is reused unchanged."""

    def __init__(
        self,
        search_contracts: Sequence[RouteContract],
        *,
        host: str = DEFAULT_SINAUTO_HOST,
        clock: Callable[[], float] = time.monotonic,
        max_window_requests: int = ROW_WINDOW_MAX_REQUESTS,
        max_window_seconds: float = ROW_WINDOW_MAX_SECONDS,
    ) -> None:
        if host != DEFAULT_SINAUTO_HOST:
            raise CanaryPolicyError("the canary policy is pinned to the production SinAuto host")
        contracts = tuple(search_contracts)
        if not contracts or any(c.capability != "read" or c.host != host for c in contracts):
            raise CanaryPolicyError("search contracts must be reviewed read contracts for the pinned host")
        self._host = host
        self._search_contracts = contracts
        self._mission_contract: Optional[RouteContract] = None
        self._phase = CanaryPhase.SEARCH
        self._clock = clock
        self._t0 = clock()
        self._max_window_requests = max_window_requests
        self._max_window_seconds = max_window_seconds
        self._window_row: Optional[int] = None
        self._window_opened_at = 0.0
        self._window_count = 0
        self._violations: list = []
        self._evidence: list = []
        self._last_record: Optional[EvidenceRecord] = None

    # -- state -----------------------------------------------------------

    @property
    def phase(self) -> CanaryPhase:
        return self._phase

    @property
    def violations(self) -> tuple:
        return tuple(self._violations)

    @property
    def last_record(self) -> Optional[EvidenceRecord]:
        return self._last_record

    @property
    def has_violation(self) -> bool:
        return bool(self._violations)

    def evidence(self) -> tuple:
        return tuple(r.as_dict() for r in self._evidence)

    def record_violation(self, reason: str) -> None:
        """Out-of-band violations (popup, websocket, browser close)."""
        self._violations.append(reason)
        self._append(EvidenceRecord(
            phase=self._phase.value, row_index=self._window_row, method="-", path="-",
            resource_type="-", decision="VIOLATION", reason=reason, t_ms=self._elapsed_ms(),
        ))

    # -- transitions -----------------------------------------------------

    def authorize_exact_mission_route(self, mission_route_contract: RouteContract, *, expected_route: str) -> None:
        """Called by ReadCapability.open() for the ONE validated candidate."""
        contract = mission_route_contract
        if self._phase is not CanaryPhase.SEARCH or self._mission_contract is not None:
            raise CanaryPolicyError("the mission route may be authorized once, from SEARCH only")
        if (
            contract.host != self._host or contract.route != expected_route or contract.method != "GET"
            or contract.capability != "read" or contract.body_fields or contract.query_fields
            or is_permanently_blocked(contract.route)
        ):
            raise CanaryPolicyError("mission contract is not an exact read of the pinned host")
        self._mission_contract = contract
        self._phase = CanaryPhase.MISSION

    def open_row_window(self, row_index: int) -> None:
        if self._phase is not CanaryPhase.MISSION:
            raise CanaryPolicyError("a row window may open only from MISSION")
        if self.has_violation:
            raise CanaryPolicyError("a row window may not open after a violation")
        self._phase = CanaryPhase.ROW_WINDOW
        self._window_row = row_index
        self._window_opened_at = self._clock()
        self._window_count = 0

    def close_row_window(self) -> None:
        if self._phase is CanaryPhase.ROW_WINDOW:
            self._phase = CanaryPhase.MISSION
        self._window_row = None

    def enter_review(self) -> None:
        if self._phase is not CanaryPhase.MISSION or self.has_violation:
            raise CanaryPolicyError("review may be entered only from a clean MISSION phase")
        self._phase = CanaryPhase.REVIEW

    def abort(self) -> None:
        self._phase = CanaryPhase.ABORTED
        self._window_row = None

    # -- the decision ----------------------------------------------------

    def decide(self, facts: RequestFacts) -> bool:
        """True = allow. Every denial is recorded; every denial outside
        REVIEW/ABORTED is also a violation."""
        allowed, reason, path = self._evaluate(facts)
        names = body_field_names(facts.content_type, facts.body) if facts.body else ()
        method = facts.method.upper() if _METHOD_RE.match((facts.method or "").upper()) else "{v}"
        resource_type = facts.resource_type if _SAFE_SEGMENT.match(facts.resource_type or "") else "{v}"
        record = EvidenceRecord(
            phase=self._phase.value, row_index=self._window_row, method=method,
            path=normalize_evidence_path(path), resource_type=resource_type,
            decision="ALLOW" if allowed else "DENY", reason=reason, t_ms=self._elapsed_ms(),
            body_field_names=names, body_fields_hash=_names_hash(names),
        )
        self._append(record)
        if not allowed and self._phase not in (CanaryPhase.REVIEW, CanaryPhase.ABORTED):
            self._violations.append(reason)
        self._last_record = record
        return allowed

    def _evaluate(self, facts: RequestFacts) -> tuple:
        try:
            parsed = urlsplit(facts.url)
        except ValueError:
            return False, "UNPARSEABLE_URL", ""
        raw_path = parsed.path or "/"
        if parsed.scheme != "https":
            return False, "NOT_HTTPS", raw_path
        if parsed.username is not None or parsed.password is not None:
            return False, "USERINFO", raw_path
        try:
            port = parsed.port
        except ValueError:
            return False, "BAD_PORT", raw_path
        if (parsed.hostname or "").lower() != self._host or port not in (None, 443):
            return False, "CROSS_ORIGIN", raw_path
        # Path-only canonicalization (query and body are judged separately
        # below), so the blocklist sees the same canonical path the rest of
        # the portal layer does.
        canonical = canonicalize_request(
            raw_url=f"https://{self._host}{raw_path}", raw_method="GET",
            raw_content_type=None, raw_body=None,
        )
        if canonical is None:
            return False, "UNCANONICAL_PATH", raw_path
        path = canonical.path
        if is_permanently_blocked(path):
            return False, "FINAL_ENDPOINT", path
        if any(marker in path.lower() for marker in _CHARGE_SPLIT_PATH_MARKERS):
            return False, "CHARGE_SPLIT", path
        if self._phase is CanaryPhase.ABORTED:
            return False, "ABORTED", path
        if not facts.is_main_frame:
            return False, "SUB_FRAME", path
        method = (facts.method or "").upper()

        # Same-host static resources: allowed in every live phase.
        if (
            method == "GET" and facts.resource_type in STATIC_RESOURCE_TYPES
            and not facts.is_navigation and not facts.body
        ):
            return True, "STATIC", path
        if self._phase is CanaryPhase.REVIEW:
            return False, "REVIEW_ONLY_STATIC", path

        # Exact reviewed contracts (search page/search POST, then the one
        # mission document) -- matched by the existing exact evaluator.
        exact = self._exact_contracts()
        full = canonicalize_request(
            raw_url=facts.url, raw_method=method, raw_content_type=facts.content_type,
            raw_body=facts.body,
        )
        if full is not None and evaluate_request(full, exact, self._host) is Decision.ALLOW:
            if facts.is_navigation and facts.resource_type != "document":
                return False, "UNEXPECTED_NAVIGATION", path
            return True, "EXACT_CONTRACT", path

        if self._phase is CanaryPhase.ROW_WINDOW:
            return self._evaluate_window(facts, method, path)
        if facts.is_navigation or facts.resource_type == "document":
            return False, "UNEXPECTED_NAVIGATION", path
        if facts.resource_type in WINDOW_RESOURCE_TYPES:
            return False, "XHR_OUTSIDE_WINDOW", path
        return False, "UNEXPECTED_REQUEST", path

    def _evaluate_window(self, facts: RequestFacts, method: str, path: str) -> tuple:
        if facts.is_navigation or facts.resource_type == "document":
            return False, "UNEXPECTED_NAVIGATION", path
        if facts.resource_type not in WINDOW_RESOURCE_TYPES:
            return False, "WINDOW_NON_XHR", path
        if method not in WINDOW_METHODS:
            return False, "WINDOW_METHOD", path
        ctype = (facts.content_type or "").split(";")[0].strip().lower()
        if ctype.startswith("multipart/"):
            return False, "WINDOW_UPLOAD", path
        if self._clock() - self._window_opened_at > self._max_window_seconds:
            return False, "WINDOW_EXPIRED", path
        if self._window_count >= self._max_window_requests:
            return False, "WINDOW_CAP", path
        self._window_count += 1
        return True, "ROW_WINDOW", path

    def _exact_contracts(self) -> tuple:
        if self._phase is CanaryPhase.SEARCH:
            return self._search_contracts
        if self._mission_contract is not None:
            return (self._mission_contract,)
        return ()

    # -- evidence bookkeeping ---------------------------------------------

    def _elapsed_ms(self) -> int:
        return int((self._clock() - self._t0) * 1000)

    def _append(self, record: EvidenceRecord) -> None:
        if len(self._evidence) < MAX_EVIDENCE_RECORDS:
            self._evidence.append(record)

    def note_status(self, record: Optional[EvidenceRecord], status: object) -> None:
        if record is not None and isinstance(status, int) and not isinstance(status, bool):
            record.status = status


# --------------------------------------------------------------------- #
# Playwright adapter (structural; no playwright import at module load)
# --------------------------------------------------------------------- #

_ABORT_CODE = "blockedbyclient"


def _facts_from_request(request, main_frame) -> RequestFacts:
    try:
        frame = request.frame
        is_main = frame is main_frame
    except Exception:
        is_main = False  # service-worker or detached request -> never main frame
    content_type = None
    try:
        for key, value in (request.headers or {}).items():
            if key.lower() == "content-type":
                content_type = value
                break
    except Exception:
        content_type = None
    try:
        body = request.post_data
    except Exception:
        body = "{binary}"
    return RequestFacts(
        url=request.url, method=request.method, resource_type=request.resource_type,
        is_navigation=bool(request.is_navigation_request()), is_main_frame=is_main,
        content_type=content_type, body=body,
    )


async def install_canary_guard(context, policy: ModeNormalCanaryNetworkPolicy, main_page) -> None:
    """Installs the canary route handler, websocket denial, popup refusal and
    response-status bookkeeping on `context`. Must run BEFORE the first
    navigation. On any installation failure the context is closed."""
    records: dict = {}

    async def handler(route) -> None:
        request = route.request
        try:
            facts = _facts_from_request(request, main_page.main_frame)
            allowed = policy.decide(facts)
            records[id(request)] = policy.last_record
        except Exception:
            allowed = False
            policy.record_violation("HANDLER_ERROR")
        try:
            if allowed:
                await route.continue_()
            else:
                await route.abort(_ABORT_CODE)
        except Exception:
            try:
                await route.abort(_ABORT_CODE)
            except Exception:
                pass

    async def deny_websocket(ws_route) -> None:
        policy.record_violation("WEBSOCKET")
        try:
            await ws_route.close()
        except Exception:
            pass

    def on_response(response) -> None:
        try:
            policy.note_status(records.get(id(response.request)), response.status)
        except Exception:
            pass

    def on_page(page) -> None:
        if page is main_page:
            return
        policy.record_violation("POPUP")
        try:
            # Fire-and-forget close of an unexpected popup/tab.
            asyncio.ensure_future(page.close())
        except Exception:
            pass

    try:
        await context.route("**/*", handler)
        await context.route_web_socket("**/*", deny_websocket)
        context.on("response", on_response)
        context.on("page", on_page)
    except Exception:
        try:
            await context.close()
        except Exception:
            pass
        raise
