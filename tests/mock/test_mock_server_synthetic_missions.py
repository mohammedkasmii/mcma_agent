"""
INC-09B amendment #2 (blocker #2) -- proves, for EACH synthetic mission,
the full chain: search-by-Matricule -> URL identifier (id_mission) ->
rendered identity (IdMission/IdSinistre__I/MatriculeVeh) -> observed
workflow agreement. TestClient-based (no real browser needed -- identity/
workflow markers are plain substring checks on the returned HTML, the
same technique tests/mock/*'s other accepted tests already use).
"""


def _has_element(html: str, element_id: str) -> bool:
    return f'id="{element_id}"' in html


def _search(client, matricule):
    resp = client.post(
        "/SinAuto_MCMA/expertise/FrontExpert/listeMissions", data={"Matricule": matricule}
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    return rows[0]


def _deep_link(candidate):
    return (
        "/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/"
        f"{candidate['IdMission']}/rubrique/gestionexpert-index"
    )


def test_pec_synthetic_mission_full_chain(client):
    candidate = _search(client, "34602-B-7")
    assert candidate["IdMission"] == 532805

    resp = client.get(_deep_link(candidate))
    assert resp.status_code == 200
    html = resp.text
    assert 'id="IdMission" value="532805"' in html
    assert 'id="IdSinistre__I" value="534660"' in html
    assert 'id="MatriculeVeh" value="34602-B-7"' in html
    assert _has_element(html, "DevisDetTableVal")
    assert _has_element(html, "blocDevisValide")
    assert not _has_element(html, "tableRapportDet")
    assert not _has_element(html, "MontantReparation")


def test_normal_synthetic_mission_full_chain(client):
    candidate = _search(client, "77001-C-3")
    assert candidate["IdMission"] == 612001

    resp = client.get(_deep_link(candidate))
    assert resp.status_code == 200
    html = resp.text
    assert 'id="IdMission" value="612001"' in html
    assert 'id="IdSinistre__I" value="699001"' in html
    assert 'id="MatriculeVeh" value="77001-C-3"' in html
    assert _has_element(html, "tableRapportDet")
    assert _has_element(html, "MontantReparation")
    assert not _has_element(html, "DevisDetTableVal")
    assert not _has_element(html, "blocDevisValide")


def test_pec_mission_never_carries_normal_missions_identity_and_vice_versa(client):
    """Direct regression for the exact defect blocker #2 named: a
    synthetic mission's page must never render the OTHER mission's
    hardcoded identity."""
    pec_html = client.get(_deep_link({"IdMission": 532805})).text
    normal_html = client.get(_deep_link({"IdMission": 612001})).text
    assert "612001" not in pec_html
    assert "77001-C-3" not in pec_html
    assert "532805" not in normal_html
    assert "34602-B-7" not in normal_html


def test_blank_matricule_search_returns_both_synthetic_missions(client):
    resp = client.post("/SinAuto_MCMA/expertise/FrontExpert/listeMissions", data={"Matricule": ""})
    ids = {row["IdMission"] for row in resp.json()["data"]}
    assert ids == {532805, 612001}


def test_non_matching_matricule_returns_zero_rows(client):
    resp = client.post(
        "/SinAuto_MCMA/expertise/FrontExpert/listeMissions", data={"Matricule": "00000-A-00"}
    )
    assert resp.json()["data"] == []
