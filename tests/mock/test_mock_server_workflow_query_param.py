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


def test_deep_link_route_also_accepts_the_workflow_parameter(client):
    resp = client.get(
        "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/534660/rubrique/gestionexpert-index",
        params={"workflow": "normal"},
    )
    html = resp.text
    assert _has_element(html, "tableRapportDet")
    assert not _has_element(html, "DevisDetTableVal")


def test_matricule_veh_field_present_with_expected_value(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    assert 'id="MatriculeVeh"' in resp.text
    assert 'value="34602-B-7"' in resp.text


def test_render_mission_page_docstring_marks_workflow_param_mock_only():
    doc = " ".join((inspect.getdoc(mock_server._render_mission_page) or "").split())
    assert "MOCK-ONLY" in doc
    assert "never a confirmed live query parameter or contract" in doc
