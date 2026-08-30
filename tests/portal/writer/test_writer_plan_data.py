"""
INC-09B -- PortalRowIntent/WriterPlanData binding, _workflow_key, and the
strict id_mission/allowed_host validators. Pure unit tests, no I/O.
"""

import pytest

from mcma.domain.enums import RepairWorkflow
from mcma.domain.values import RubriqueId
from mcma.portal.writer import (
    PortalRowIntent,
    WriterPlanData,
    _mission_route_for,
    _require_loopback_host,
    _require_valid_mission_id,
    _workflow_key,
)
from writer_test_support import money, row_intent


def test_portal_row_intent_requires_rubrique_id_type():
    with pytest.raises(TypeError):
        PortalRowIntent(rubrique_id="3", ht=money("10.00"), tva=money("2.00"), vetuste=money("0.00"))


def test_portal_row_intent_requires_money_types():
    with pytest.raises(TypeError):
        PortalRowIntent(rubrique_id=RubriqueId("3"), ht="10.00", tva=money("2.00"), vetuste=money("0.00"))


def test_writer_plan_data_rejects_duplicate_rubrique_ids():
    with pytest.raises(ValueError):
        WriterPlanData(
            repair_workflow=RepairWorkflow.MODE_NORMAL,
            row_intents=(row_intent("3", "10.00", "2.00"), row_intent("3", "20.00", "4.00")),
        )


def test_writer_plan_data_intent_for_returns_none_when_unplanned():
    plan = WriterPlanData(repair_workflow=RepairWorkflow.MODE_NORMAL, row_intents=(row_intent("3", "10.00", "2.00"),))
    assert plan.intent_for(RubriqueId("99")) is None
    assert plan.intent_for(RubriqueId("3")) is not None


def test_workflow_key_matches_established_string_convention():
    assert _workflow_key(RepairWorkflow.MODE_NORMAL) == "MODE_NORMAL"
    assert _workflow_key(RepairWorkflow.GARAGE_CONVENTIONNE) == "GARAGE_CONVENTIONNE"


# --------------------------------------------------------------------- #
# id_mission validation
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [True, False, 1.5, "5", "", None, 0, -1])
def test_require_valid_mission_id_rejects(bad):
    with pytest.raises(ValueError):
        _require_valid_mission_id(bad)


def test_require_valid_mission_id_accepts_positive_int():
    assert _require_valid_mission_id(532805) == 532805


def test_mission_route_uses_one_fixed_template_and_canonicalizes():
    from mcma.portal.canonical import canonicalize_request

    route = _mission_route_for(532805)
    assert route == "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/532805/rubrique/gestionexpert-index"
    canonical = canonicalize_request(
        raw_url=f"http://127.0.0.1:8080{route}", raw_method="GET", raw_content_type=None, raw_body=None
    )
    assert canonical is not None
    assert canonical.path == route


# --------------------------------------------------------------------- #
# allowed_host validation
# --------------------------------------------------------------------- #


def test_require_loopback_host_accepts_ipv4_loopback():
    _require_loopback_host("127.0.0.1:8080")  # no raise


def test_require_loopback_host_accepts_bracketed_ipv6_loopback():
    _require_loopback_host("[::1]:8080")  # no raise


@pytest.mark.parametrize(
    "bad_host",
    [
        "localhost:8080",
        "example.com:8080",
        "user@127.0.0.1:8080",
        "127.0.0.1:8080/path",
        "127.0.0.1:8080/",
        "127.0.0.1:8080?x=1",
        "127.0.0.1:8080#frag",
        "127.0.0.1:99999",
        "127.0.0.1:notaport",
        "8.8.8.8:8080",
        "[::2]:8080",
    ],
)
def test_require_loopback_host_rejects(bad_host):
    with pytest.raises(ValueError):
        _require_loopback_host(bad_host)
