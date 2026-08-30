"""
INC-06 — Mode Normal DOM + HTTP/state lifecycle against the offline mock.
"""

import json
import re

from mock_test_support import FIXTURES_DIR, NORMAL_CHARGE_FIELDS, state


def _section_normal(html: str) -> str:
    start = html.index('<div id="sectionModeNormal"')
    end = html.index("</form>", start)
    return html[start:end]


def test_veh_repare_section_and_empty_table_render(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    section = _section_normal(resp.text)
    assert 'id="VehRepareI"' in resp.text
    assert 'id="tbodyModeNormal"' in section
    assert 'ajouterLigneModeNormal' in section


def test_ajouter_lifecycle_creates_exactly_one_row_and_checkmark_calls_create_once(client):
    resp = client.post(
        "/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
        data={
            "IdRubrique": "7",
            "MontantHT": "1000.00",
            "Taxe": "200.00",
            "MontantTTC": "1200.00",
            "TauxVetuste": "0.00",
            "MontantVetuste": "0.00",
            "TempRowId": "tmp-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "success"

    st = state(client)
    assert st["observability"]["row_endpoint_calls"]["MODE_NORMAL"]["createRapportDefDet"] == 1
    assert len(st["rows"]["normal"]) == 1
    assert st["rows"]["normal"][0]["IdRubrique"] == "7"

    read_back = client.post("/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet")
    rows = read_back.json()["data"]
    assert len(rows) == 1
    assert rows[0]["MontantHT"] == "1000.00"


def test_duplicate_temp_row_id_fails_closed(client):
    payload = {
        "IdRubrique": "7",
        "MontantHT": "1000.00",
        "Taxe": "200.00",
        "MontantTTC": "1200.00",
        "TauxVetuste": "0.00",
        "MontantVetuste": "0.00",
        "TempRowId": "tmp-dup",
    }
    first = client.post("/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet", data=payload)
    assert first.json()["state"] == "success"

    second = client.post("/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet", data=payload)
    assert second.json()["state"] == "error"
    assert second.json()["reason"] == "DUPLICATE_ROW_SUBMISSION"

    st = state(client)
    assert len(st["rows"]["normal"]) == 1
    assert st["observability"]["duplicate_checkmark_attempts"]["MODE_NORMAL"] == 1


def test_direct_charge_field_write_rejected(client):
    for field in NORMAL_CHARGE_FIELDS:
        payload = {
            "IdRubrique": "7",
            "MontantHT": "1000.00",
            "Taxe": "200.00",
            "MontantTTC": "1200.00",
            "TauxVetuste": "0.00",
            "MontantVetuste": "0.00",
            "TempRowId": f"tmp-{field}",
            field: "9999.00",
        }
        resp = client.post(
            "/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet", data=payload
        )
        body = resp.json()
        assert body["state"] == "error"
        assert body["reason"] == "DIRECT_CHARGE_FIELD_WRITE_REJECTED"

    st = state(client)
    assert st["observability"]["direct_charge_write_attempts"]["MODE_NORMAL"] == len(
        NORMAL_CHARGE_FIELDS
    )
    assert st["rows"]["normal"] == []


def test_charge_fields_present_in_dom_but_unwired(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    section = _section_normal(resp.text)
    assert 'id="MontantChargeMutuelle"' in section
    assert 'id="MontantChargeSocietaire"' in section
    # No confirmed onclick/onchange wiring — only the mock-only calculation
    # hook may ever set these values, and only via its own response handler.
    for field_id in ("MontantChargeMutuelle", "MontantChargeSocietaire"):
        match = re.search(rf'id="{field_id}"[^>]*', section)
        assert match is not None
        assert "onchange" not in match.group(0)


def test_native_calculation_fixture_is_mock_only_and_unconfirmed():
    fixture = json.loads(
        (FIXTURES_DIR / "normal_native_recalc_mock_only.json").read_text(encoding="utf-8")
    )
    assert fixture["mock_only"] is True
    assert fixture["g5_live_contract_status"] == "UNCONFIRMED"
    assert fixture["eligible_for_live_allowlist"] is False
    assert fixture["live_selector"] is None
    assert fixture["live_endpoint"] is None
    assert fixture["mock_route"] is True


def test_native_calculation_success_stale_missing_failed_mismatch(client):
    base = {"total_ttc": "1200.00", "franchise": "100.00", "vetuste": "50.00", "remise": "0.00", "part_resp": "100"}

    ok = client.post("/_mock/normal/native_calculation", json={**base, "simulate": "success"})
    assert ok.json()["state"] == "success"
    summary_ok = ok.json()["summary"]
    read_back = client.get("/_mock/normal/financial_summary").json()
    assert read_back["summary"] == summary_ok

    stale = client.post("/_mock/normal/native_calculation", json={**base, "simulate": "stale"})
    assert stale.json()["state"] == "success"
    assert stale.json()["stale"] is True
    assert client.get("/_mock/normal/financial_summary").json()["summary"]["stale"] is True

    client.post("/_mock/reset")
    missing = client.post("/_mock/normal/native_calculation", json={**base, "simulate": "missing"})
    assert missing.json()["state"] == "error"
    assert client.get("/_mock/normal/financial_summary").json()["summary"] is None

    failed = client.post("/_mock/normal/native_calculation", json={**base, "simulate": "failed"})
    assert failed.json()["state"] == "error"
    assert failed.json()["reason"] == "NATIVE_CALCULATION_FAILED"

    client.post("/_mock/reset")
    mismatch = client.post("/_mock/normal/native_calculation", json={**base, "simulate": "mismatch"})
    computed = mismatch.json()["summary"]
    stored = client.get("/_mock/normal/financial_summary").json()["summary"]
    assert stored != computed


def test_native_calculation_never_settable_by_direct_charge_field(client):
    resp = client.post(
        "/_mock/normal/native_calculation",
        json={
            "total_ttc": "1200.00",
            "franchise": "0",
            "vetuste": "0",
            "remise": "0",
            "part_resp": "100",
            "simulate": "success",
            "MontantChargeMutuelle": "999999.00",
        },
    )
    assert resp.json()["state"] == "error"
    assert resp.json()["reason"] == "DIRECT_CHARGE_FIELD_WRITE_REJECTED"


def test_mode_normal_never_uses_pec_selectors_or_native_function(client):
    """Correction #2 — scoped to the Mode Normal DOM section and its fixture,
    not a whole-file scan (the combined mock legitimately contains both
    workflows' contracts elsewhere)."""
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    section = _section_normal(resp.text)
    assert "DevisCalculerMontantCharge" not in section
    assert "#Devis" not in section
    assert 'id="Devis' not in section

    fixture = json.loads(
        (FIXTURES_DIR / "normal_add_row.json").read_text(encoding="utf-8")
    )
    dumped = json.dumps(fixture)
    assert "Devis" not in dumped
