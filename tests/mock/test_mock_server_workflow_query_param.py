"""
INC-09A -- the mock-only ?workflow= query parameter. TestClient-based (no
browser needed to verify HTML content). Amendment #3: the default
(unspecified) rendering must be UNCHANGED from the accepted INC-06
behavior -- both sections present, exactly as before. Amendment #5: the
parameter must be documented as mock-only, never a live contract.
"""

import inspect

import mock_server


def _has_element(html: str, element_id: str) -> bool:
    return f'id="{element_id}"' in html


def test_default_renders_both_sections_unchanged_from_inc06(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="sectionGarageConventionne"' in html
    assert 'id="sectionModeNormal"' in html
    assert _has_element(html, "tableRapportDet")
    assert _has_element(html, "DevisDetTableVal")
    assert _has_element(html, "blocDevisValide")


def test_workflow_normal_removes_pec_section_entirely(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index", params={"workflow": "normal"})
    html = resp.text
    assert _has_element(html, "tableRapportDet")
    assert _has_element(html, "MontantReparation")
    assert not _has_element(html, "DevisDetTableVal")
    assert not _has_element(html, "blocDevisValide")
    assert 'id="sectionGarageConventionne"' not in html


def test_workflow_conventionne_removes_normal_section_entirely(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index", params={"workflow": "conventionne"})
    html = resp.text
    assert _has_element(html, "DevisDetTableVal")
    assert _has_element(html, "blocDevisValide")
    assert not _has_element(html, "tableRapportDet")
    assert not _has_element(html, "MontantReparation")
    assert 'id="sectionModeNormal"' not in html


def test_deep_link_route_renders_the_synthetic_missions_own_workflow_and_ignores_workflow_param(client):
    """INC-09B amendment #2 (blocker #2) REQUIRED change, disclosed here:
    the deep-link route no longer accepts a `?workflow=` override at all
    (unlike the bare /index route above, whose own override is unchanged
    09A test infrastructure) -- the rendered workflow is now looked up
    deterministically from which synthetic mission the id in the URL
    names. The id in this route is id_mission (532805 for the PEC
    mission), not id_sinistre (534660) -- see get_mission_deep_link's
    docstring for exactly why. A `?workflow=` query string is accepted but
    has no effect, since this route does not read it at all."""
    resp = client.get(
        "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/532805/rubrique/gestionexpert-index",
        params={"workflow": "normal"},
    )
    html = resp.text
    assert _has_element(html, "DevisDetTableVal")
    assert not _has_element(html, "tableRapportDet")


def test_deep_link_route_with_the_synthetic_normal_mission_id_renders_normal_only(client):
    resp = client.get(
        "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/612001/rubrique/gestionexpert-index"
    )
    html = resp.text
    assert _has_element(html, "tableRapportDet")
    assert not _has_element(html, "DevisDetTableVal")


def test_deep_link_route_with_unrecognized_id_returns_404_with_no_identity_or_workflow_dom(client):
    resp = client.get(
        "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/999999/rubrique/gestionexpert-index"
    )
    assert resp.status_code == 404
    html = resp.text
    assert 'id="IdMission"' not in html
    assert 'id="IdSinistre__I"' not in html
    assert 'id="MatriculeVeh"' not in html
    assert not _has_element(html, "tableRapportDet")
    assert not _has_element(html, "DevisDetTableVal")


def test_deep_link_route_with_non_integer_id_returns_404(client):
    resp = client.get(
        "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/not-a-number/rubrique/gestionexpert-index"
    )
    assert resp.status_code == 404


def test_matricule_veh_field_present_with_expected_value(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    assert 'id="MatriculeVeh"' in resp.text
    assert 'value="34602-B-7"' in resp.text


def test_render_mission_page_docstring_marks_workflow_param_mock_only():
    doc = " ".join((inspect.getdoc(mock_server._render_mission_page) or "").split())
    assert "MOCK-ONLY" in doc
    assert "never a confirmed live query parameter or contract" in doc
