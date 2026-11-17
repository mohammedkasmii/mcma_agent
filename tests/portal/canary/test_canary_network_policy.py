"""The supervised Mode Normal canary's network policy, decision by decision.

Pure: no browser. Requests are described as RequestFacts exactly as the
Playwright adapter would extract them."""

import pytest

from mcma.portal.canary_network import (
    ROW_WINDOW_MAX_REQUESTS,
    CanaryPhase,
    CanaryPolicyError,
    ModeNormalCanaryNetworkPolicy,
    RequestFacts,
    body_field_names,
    normalize_evidence_path,
)
from mcma.portal.contracts import RouteContract
from mcma.portal.sinauto_contracts import DEFAULT_SINAUTO_HOST, identity_read_contracts

HOST = DEFAULT_SINAUTO_HOST
BASE = f"https://{HOST}"
SEARCH_PAGE = "/SinAuto_MCMA/expertise/frontexpert"
SEARCH_POST = "/SinAuto_MCMA/expertise/FrontExpert/listeMissions"
MISSION = "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/4242/rubrique/gestionexpert-index"
SAVE = "/SinAuto_MCMA/expertise/gestionExpert/saveRubriqueRow"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _policy(clock=None):
    return ModeNormalCanaryNetworkPolicy(identity_read_contracts(HOST), clock=clock or Clock())


def _mission_contract():
    return RouteContract(
        host=HOST, route=MISSION, method="GET", query_fields=frozenset(), content_type=None,
        body_fields=frozenset(), capability="read", operation_type="mission_open", workflow=None,
    )


def _doc(path, *, main=True):
    return RequestFacts(url=BASE + path, method="GET", resource_type="document", is_navigation=True, is_main_frame=main)


def _static(path, rtype="script", host=HOST):
    return RequestFacts(url=f"https://{host}{path}", method="GET", resource_type=rtype,
                        is_navigation=False, is_main_frame=True)


def _xhr(path, method="POST", body: str | None = "IdRubrique=3&MontantHT=5000.00",
         ctype: str | None = "application/x-www-form-urlencoded",
         main=True, rtype="xhr"):
    return RequestFacts(url=BASE + path, method=method, resource_type=rtype, is_navigation=False,
                        is_main_frame=main, content_type=ctype, body=body)


def _search_post():
    return _xhr(SEARCH_POST, body="Matricule=11111-A-1&ReferenceCie=", rtype="fetch")


def _in_mission():
    policy = _policy()
    policy.authorize_exact_mission_route(_mission_contract(), expected_route=MISSION)
    return policy


# --------------------------------------------------------------------- #
# Construction and host pinning
# --------------------------------------------------------------------- #


def test_policy_is_pinned_to_the_production_host():
    with pytest.raises(CanaryPolicyError):
        ModeNormalCanaryNetworkPolicy(identity_read_contracts("127.0.0.1:8080"), host="127.0.0.1:8080")


def test_policy_refuses_non_read_contracts():
    write = RouteContract(
        host=HOST, route=SAVE, method="POST", query_fields=frozenset(), content_type=None,
        body_fields=frozenset(), capability="row_write", operation_type="x", workflow="MODE_NORMAL",
    )
    with pytest.raises(CanaryPolicyError):
        ModeNormalCanaryNetworkPolicy((write,))


@pytest.mark.parametrize("url", [
    f"http://{HOST}{SEARCH_PAGE}",                 # not https
    f"https://evil.example{SEARCH_PAGE}",           # other host
    f"https://{HOST}.evil.example{SEARCH_PAGE}",    # suffix trick
    f"https://user:pw@{HOST}{SEARCH_PAGE}",         # userinfo
    f"https://{HOST}:8443{SEARCH_PAGE}",            # other port
])
def test_only_the_exact_pinned_https_origin_is_ever_allowed(url):
    policy = _policy()
    assert policy.decide(RequestFacts(url=url, method="GET", resource_type="document",
                                      is_navigation=True, is_main_frame=True)) is False
    assert policy.has_violation


# --------------------------------------------------------------------- #
# SEARCH and MISSION phases
# --------------------------------------------------------------------- #


def test_search_phase_allows_exact_search_contracts_and_static_only():
    policy = _policy()
    assert policy.decide(_doc(SEARCH_PAGE))
    assert policy.decide(_search_post())
    for rtype in ("script", "stylesheet", "image", "font"):
        assert policy.decide(_static(f"/SinAuto_MCMA/assets/app.{rtype}", rtype))
    assert not policy.has_violation


def test_mission_route_authorized_once_then_only_that_document():
    policy = _in_mission()
    assert policy.phase is CanaryPhase.MISSION
    assert policy.decide(_doc(MISSION))
    with pytest.raises(CanaryPolicyError):
        policy.authorize_exact_mission_route(_mission_contract(), expected_route=MISSION)
    # The search POST is no longer reachable once the mission is open.
    assert not policy.decide(_search_post())


def test_mission_contract_must_be_an_exact_read_of_the_pinned_host():
    policy = _policy()
    bad = RouteContract(
        host="other.host", route=MISSION, method="GET", query_fields=frozenset(), content_type=None,
        body_fields=frozenset(), capability="read", operation_type="mission_open", workflow=None,
    )
    with pytest.raises(CanaryPolicyError):
        policy.authorize_exact_mission_route(bad, expected_route=MISSION)


@pytest.mark.parametrize("facts,reason", [
    (_xhr("/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet"), "XHR_OUTSIDE_WINDOW"),
    (_xhr(SAVE, method="GET", body=None, ctype=None, rtype="fetch"), "XHR_OUTSIDE_WINDOW"),
    (_doc("/SinAuto_MCMA/other/page"), "UNEXPECTED_NAVIGATION"),
    (_static("/x.js", host="cdn.example"), "CROSS_ORIGIN"),
    (RequestFacts(url=BASE + "/frame.js", method="GET", resource_type="script",
                  is_navigation=False, is_main_frame=False), "SUB_FRAME"),
    (RequestFacts(url=BASE + "/x", method="GET", resource_type="other", is_navigation=False, is_main_frame=True),
     "UNEXPECTED_REQUEST"),
])
def test_mission_phase_denies_everything_unreviewed_and_records_a_violation(facts, reason):
    policy = _in_mission()
    assert policy.decide(facts) is False
    assert policy.violations == (reason,)
    assert policy.evidence()[-1]["reason"] == reason


# --------------------------------------------------------------------- #
# ROW_WINDOW
# --------------------------------------------------------------------- #


def test_row_window_allows_bounded_same_host_xhr_and_closes():
    policy = _in_mission()
    policy.open_row_window(0)
    assert policy.decide(_xhr(SAVE))
    assert policy.decide(_xhr("/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet",
                              method="GET", body=None, ctype=None, rtype="fetch"))
    policy.close_row_window()
    assert policy.phase is CanaryPhase.MISSION
    assert policy.decide(_xhr(SAVE)) is False
    assert policy.violations == ("XHR_OUTSIDE_WINDOW",)


def test_row_window_enforces_its_request_cap():
    policy = _in_mission()
    policy.open_row_window(0)
    for _ in range(ROW_WINDOW_MAX_REQUESTS):
        assert policy.decide(_xhr(SAVE))
    assert policy.decide(_xhr(SAVE)) is False
    assert policy.violations == ("WINDOW_CAP",)


def test_row_window_expires():
    clock = Clock()
    policy = ModeNormalCanaryNetworkPolicy(identity_read_contracts(HOST), clock=clock, max_window_seconds=5)
    policy.authorize_exact_mission_route(_mission_contract(), expected_route=MISSION)
    policy.open_row_window(0)
    clock.now += 6
    assert policy.decide(_xhr(SAVE)) is False
    assert policy.violations == ("WINDOW_EXPIRED",)


@pytest.mark.parametrize("facts,reason", [
    (_xhr(SAVE, method="PUT"), "WINDOW_METHOD"),
    (_xhr(SAVE, method="DELETE"), "WINDOW_METHOD"),
    (_xhr(SAVE, method="PATCH"), "WINDOW_METHOD"),
    (_xhr(SAVE, ctype="multipart/form-data; boundary=x", body="--x"), "WINDOW_UPLOAD"),
    (_doc("/SinAuto_MCMA/expertise/somewhere"), "UNEXPECTED_NAVIGATION"),
    (_xhr(SAVE, main=False), "SUB_FRAME"),
    (_xhr("/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission"), "FINAL_ENDPOINT"),
    (_xhr("/SinAuto_MCMA/expertise/gestionExpert/validerDevis"), "FINAL_ENDPOINT"),
    (_xhr("/SinAuto_MCMA/expertise/gestionExpert/cloturerMission"), "FINAL_ENDPOINT"),
    (_xhr("/SinAuto_MCMA/expertise/ged/ajouterDocument"), "FINAL_ENDPOINT"),
    (_xhr("/SinAuto_MCMA/expertise/gestionExpert/updateMontantChargeMutuelle"), "CHARGE_SPLIT"),
    (_xhr("/SinAuto_MCMA/expertise/gestionExpert/setChargeSocietaire"), "CHARGE_SPLIT"),
])
def test_row_window_still_denies_every_forbidden_shape(facts, reason):
    policy = _in_mission()
    policy.open_row_window(0)
    assert policy.decide(facts) is False
    assert policy.violations == (reason,)


def test_no_window_may_open_after_a_violation_or_outside_mission():
    policy = _policy()
    with pytest.raises(CanaryPolicyError):
        policy.open_row_window(0)  # still SEARCH
    policy = _in_mission()
    policy.decide(_xhr(SAVE))  # violation
    with pytest.raises(CanaryPolicyError):
        policy.open_row_window(0)


# --------------------------------------------------------------------- #
# REVIEW / ABORTED
# --------------------------------------------------------------------- #


def test_review_allows_static_only_and_abort_denies_everything():
    policy = _in_mission()
    policy.enter_review()
    assert policy.decide(_static("/a.css", "stylesheet"))
    assert policy.decide(_xhr(SAVE)) is False
    assert not policy.has_violation  # after READY a denial no longer changes the outcome
    policy.abort()
    assert policy.decide(_static("/a.css", "stylesheet")) is False
    assert policy.decide(_doc(MISSION)) is False


def test_review_requires_a_clean_mission_phase():
    policy = _in_mission()
    policy.decide(_xhr(SAVE))
    with pytest.raises(CanaryPolicyError):
        policy.enter_review()


# --------------------------------------------------------------------- #
# Safe evidence
# --------------------------------------------------------------------- #


def test_evidence_never_contains_values_or_identifiers():
    policy = _policy()
    policy.decide(_search_post())
    policy.authorize_exact_mission_route(_mission_contract(), expected_route=MISSION)
    policy.decide(_doc(MISSION))
    policy.open_row_window(0)
    policy.decide(_xhr(SAVE + "?id=4242", body="IdRubrique=3&MontantHT=5000.00&Taxe=0&Plate=11111-A-1"))
    text = repr(policy.evidence())
    for secret in ("11111", "4242", "5000", "Plate=", "A-1"):
        assert secret not in text
    last = policy.evidence()[-1]
    assert last["body_field_names"] == ["IdRubrique", "MontantHT", "Plate", "Taxe"]
    assert last["body_fields_hash"] and len(last["body_fields_hash"]) == 16
    assert last["path"] == "/SinAuto_MCMA/expertise/gestionExpert/saveRubriqueRow"
    mission_record = [r for r in policy.evidence() if r["resource_type"] == "document"][0]
    assert "{v}" in mission_record["path"]


def test_path_normalization_and_field_names():
    assert normalize_evidence_path("/a/getSinistre/idSinistre/123/x-y") == "/a/getSinistre/idSinistre/{v}/x-y"
    assert normalize_evidence_path("/a/getSinistre/idSinistre/opaqueMissionRef/x-y") == (
        "/a/getSinistre/idSinistre/{v}/x-y"
    )
    assert normalize_evidence_path("/missions/ALPHA-REFERENCE/details") == "/missions/{v}/details"
    assert normalize_evidence_path("/A1B2/ok") == "/{v}/ok"
    assert body_field_names("application/json", '{"a": 1, "b c": 2}') == ("a", "{unsafe}")
    assert body_field_names("application/json", "not json") == ("{unparsed}",)
