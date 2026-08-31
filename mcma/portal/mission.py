"""
mcma.portal.mission -- exactly-one mission search, mission-open navigation,
identity scraping, and workflow detection (INC-09A, SAFETY_MODEL.md §4/§4a,
ADR-0003, PORTAL_CONTRACT.md §4).

Deliberately duplicates a small amount of mechanics already present in
mcma.portal.capabilities (the fetch-based search call, the mission deep-link
navigation) rather than importing from it or refactoring it: capabilities.py
is an already-accepted, CI-green file from INC-08, and this project's
established convention (INC-06/07/08) is bounded duplication over coupling
to accepted files. ReadCapability.search()/.open() deliberately do NOT
enforce exactly-one or verify identity (that enforcement is exactly what
this module adds); the two are structurally different consumers, not the
same operation reused with a flag.

-- Workflow detection and the #VehRepareI conflict --
PORTAL_CONTRACT.md §4 lists Mode Normal markers as
`#VehRepareI, #MontantReparation, #tableRapportDet`. PORTAL_CONTRACT.md §5
("Header form fields") separately lists `#VehRepareI` among the SHARED
header fields present on every mission regardless of mode. The two sections
disagree about what `#VehRepareI` is. Reading the actual recovered
mock/DOM evidence: `#VehRepareI` sits in the mission's shared "Options"
fieldset, rendered once per page, OUTSIDE both the Mode Normal and Garage
Conventionne sections -- it is present on a PEC page too. A detector using
"any Normal marker present => MODE_NORMAL" would therefore return
MODE_NORMAL on every page, PEC included, and the workflow-mismatch gate
would pass vacuously (the exact defect a reviewer caught before this module
was implemented).

`#VehRepareI` is therefore EXCLUDED from detection. Only markers verified
exclusive to one workflow's own DOM section are used:
  Mode Normal:         #tableRapportDet, #MontantReparation
  Garage Conventionne: #DevisDetTableVal, #blocDevisValide
Both markers of a set must be present for that workflow to count as
detected (stronger than "any one"); if both workflows' marker sets are
present, or neither is, detection fails closed with WorkflowIndeterminate
-- ambiguity is never resolved by picking one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from mcma.domain.enums import RepairWorkflow
from mcma.portal.capabilities import SearchIdentifiers
from mcma.portal.identity import observe_identity  # noqa: F401 -- re-exported, see below

# --------------------------------------------------------------------- #
# Exactly-one mission search (F3/F4: no first-row/sole-candidate fallback)
# --------------------------------------------------------------------- #

_SEARCH_ROUTE = "/SinAuto_MCMA/expertise/FrontExpert/listeMissions"
_MISSION_DEEP_LINK_TEMPLATE = (
    "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id_sinistre}/rubrique/gestionexpert-index"
)
_FETCH_JSON_JS = """([url, payload]) => fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams(payload).toString()
}).then(r => r.json())"""


@dataclass(frozen=True)
class MissionCandidate:
    """A raw search result row, scoped to this module's own exactly-one
    search flow. Deliberately a separate type from
    mcma.portal.capabilities.Candidate (whose owner-token protects a
    different trust boundary -- a public ReadCapability handing results
    back to an arbitrary caller); here the result never leaves this
    module's own construction flow, so that protection does not apply."""

    id_mission: object
    matricule: Optional[str]
    reference_mission: Optional[str]
    societaire: Optional[str]


class MissionSelectionError(Exception):
    """Zero or more than one candidate matched. Never resolved by picking
    the first or the sole remaining row (F3/F4)."""

    def __init__(self, count: int):
        super().__init__(f"expected exactly one mission candidate, found {count}")
        self.count = count


async def search_exactly_one(page, allowed_host: str, identifiers: SearchIdentifiers) -> MissionCandidate:
    if not isinstance(identifiers, SearchIdentifiers):
        raise TypeError("search_exactly_one() requires a SearchIdentifiers instance")
    payload = {"Matricule": identifiers.matricule, "ReferenceCie": identifiers.reference_cie}
    url = f"http://{allowed_host}{_SEARCH_ROUTE}"
    result = await page.evaluate(_FETCH_JSON_JS, [url, payload])
    rows = result.get("data", []) if isinstance(result, dict) else []
    candidates = [
        MissionCandidate(
            id_mission=row.get("IdMission"),
            matricule=row.get("Matricule"),
            reference_mission=row.get("ReferenceMission"),
            societaire=row.get("Societaire"),
        )
        for row in rows
        if isinstance(row, dict) and "IdMission" in row
    ]
    if len(candidates) != 1:
        raise MissionSelectionError(len(candidates))
    return candidates[0]


async def open_candidate(page, allowed_host: str, candidate: MissionCandidate) -> None:
    """Navigates to the given candidate's mission page. The id is
    percent-escaped before being placed in the one fixed path template --
    never a caller-supplied URL, never string-built from untrusted data
    beyond one escaped scalar."""
    id_segment = quote(str(candidate.id_mission), safe="")
    path = _MISSION_DEEP_LINK_TEMPLATE.format(id_sinistre=id_segment)
    await page.goto(f"http://{allowed_host}{path}")


# --------------------------------------------------------------------- #
# Workflow detection (ambiguity always fails closed -- see module docstring
# for why #VehRepareI is excluded)
# --------------------------------------------------------------------- #

_NORMAL_MARKERS = ("#tableRapportDet", "#MontantReparation")
_PEC_MARKERS = ("#DevisDetTableVal", "#blocDevisValide")

_DETECT_WORKFLOW_JS = """(markers) => {
    const allPresent = (selectors) => selectors.every((sel) => document.querySelector(sel) !== null);
    return { normal: allPresent(markers.normal), pec: allPresent(markers.pec) };
}"""


class WorkflowDetectionError(Exception):
    """Base for workflow-detection failures."""


class WorkflowIndeterminate(WorkflowDetectionError):
    """Both workflows' exclusive markers were present, or neither was.
    Ambiguity is never resolved by guessing; it always fails closed."""


class WorkflowMismatch(WorkflowDetectionError):
    """The detected (unambiguous) workflow disagrees with the planned one."""

    def __init__(self, planned: RepairWorkflow, observed: RepairWorkflow):
        super().__init__(f"planned {planned!r} but observed {observed!r}")
        self.planned = planned
        self.observed = observed


async def detect_observed_workflow(page) -> RepairWorkflow:
    result = await page.evaluate(
        _DETECT_WORKFLOW_JS, {"normal": list(_NORMAL_MARKERS), "pec": list(_PEC_MARKERS)}
    )
    raw = result if isinstance(result, dict) else {}
    normal_present = bool(raw.get("normal"))
    pec_present = bool(raw.get("pec"))
    if normal_present and pec_present:
        raise WorkflowIndeterminate("both workflows' exclusive markers are present")
    if not normal_present and not pec_present:
        raise WorkflowIndeterminate("neither workflow's exclusive markers are present")
    return RepairWorkflow.MODE_NORMAL if normal_present else RepairWorkflow.GARAGE_CONVENTIONNE


def require_workflow_agreement(planned: RepairWorkflow, observed: RepairWorkflow) -> None:
    if planned != observed:
        raise WorkflowMismatch(planned, observed)
