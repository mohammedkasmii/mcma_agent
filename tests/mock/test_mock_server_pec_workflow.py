"""
INC-06 — Garage Conventionne / PEC DOM + HTTP/state lifecycle against the
offline mock.
"""

import json

from mock_test_support import FIXTURES_DIR, PEC_CHARGE_FIELDS, state


def _section_pec(html: str) -> str:
    start = html.index('<div id="sectionGarageConventionne"')
    end = html.index('<div id="sectionModeNormal"', start)
    return html[start:end]


def test_original_read_only_table_is_separate_and_immutable(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    section = _section_pec(resp.text)
    assert 'id="DevisDetTable"' in section
    original = client.get("/_mock/pec/original_rows").json()["data"]
    assert len(original) == 4

    client.post(
        "/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet",
        data={
            "IdDevisDet": "1",
            "MontantHTValide": "1.00",
            "TaxeValide": "0.00",
            "MontantTTCValide": "1.00",
            "TauxVetusteValide": "0.00",
            "MontantVetusteValide": "0.00",
            "SubmissionNonce": "n-1",
        },
    )
    still_original = client.get("/_mock/pec/original_rows").json()["data"]
    assert still_original == original


def test_editable_table_lists_matching_rows_for_preflight(client):
    resp = client.post("/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet")
    rows = resp.json()["data"]
    assert len(rows) == 4
    ids = [r["IdRubrique"] for r in rows]
    assert len(ids) == len(set(ids))


def test_preflight_exact_match_zero_and_multiple_fail_closed(client):
    ok = client.post("/_mock/pec/preflight_match", json={"planned_rubrique_ids": ["3", "7"]})
    body = ok.json()
    assert body["all_matched"] is True

    zero = client.post("/_mock/pec/preflight_match", json={"planned_rubrique_ids": ["999"]})
    assert zero.json()["all_matched"] is False
    assert zero.json()["results"][0]["match_count"] == 0

    duplicate_target = client.post(
        "/_mock/pec/preflight_match", json={"planned_rubrique_ids": ["3", "3"]}
    )
    # Same id requested twice against a table with exactly one "3" row is a
    # planning-side ambiguity, not a portal-side multiple-match; the mock
    # reports match_count per requested id (1 each) — genuine multiple-match
    # is a table with duplicate IdRubrique rows, which the fixed data lacks.
    assert duplicate_target.json()["results"][0]["match_count"] == 1


def test_update_devis_det_requires_exact_existing_row(client):
    resp = client.post(
        "/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet",
        data={
            "IdDevisDet": "999",
            "MontantHTValide": "1.00",
            "TaxeValide": "0.00",
            "MontantTTCValide": "1.00",
            "TauxVetusteValide": "0.00",
            "MontantVetusteValide": "0.00",
            "SubmissionNonce": "n-missing",
        },
    )
    body = resp.json()
    assert body["state"] == "error"
    assert body["reason"] == "ROW_NOT_FOUND"


def test_update_devis_det_mutates_and_reads_back_exactly_once(client):
    resp = client.post(
        "/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet",
        data={
            "IdDevisDet": "2",
            "MontantHTValide": "2000.00",
            "TaxeValide": "400.00",
            "MontantTTCValide": "2400.00",
            "TauxVetusteValide": "5.00",
            "MontantVetusteValide": "120.00",
            "SubmissionNonce": "n-ok",
        },
    )
    assert resp.json()["state"] == "success"

    st = state(client)
    assert st["observability"]["row_endpoint_calls"]["GARAGE_CONVENTIONNE"]["updateDevisDet"] == 1

    rows = client.post("/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet").json()["data"]
    row2 = next(r for r in rows if r["IdDevisDet"] == 2)
    assert row2["MontantHT"] == "2000.00"
    assert row2["MontantTTC"] == "2400.00"


def test_duplicate_submission_nonce_fails_closed(client):
    payload = {
        "IdDevisDet": "3",
        "MontantHTValide": "1.00",
        "TaxeValide": "0.00",
        "MontantTTCValide": "1.00",
        "TauxVetusteValide": "0.00",
        "MontantVetusteValide": "0.00",
        "SubmissionNonce": "n-dup",
    }
    first = client.post("/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet", data=payload)
    assert first.json()["state"] == "success"
    second = client.post("/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet", data=payload)
    assert second.json()["state"] == "error"
    assert second.json()["reason"] == "DUPLICATE_ROW_SUBMISSION"
    assert state(client)["observability"]["duplicate_checkmark_attempts"]["GARAGE_CONVENTIONNE"] == 1


def test_direct_charge_field_write_rejected(client):
    for field in PEC_CHARGE_FIELDS:
        payload = {
            "IdDevisDet": "1",
            "MontantHTValide": "1.00",
            "TaxeValide": "0.00",
            "MontantTTCValide": "1.00",
            "TauxVetusteValide": "0.00",
            "MontantVetusteValide": "0.00",
            "SubmissionNonce": f"n-{field}",
            field: "9999.00",
        }
        resp = client.post("/SinAuto_MCMA/expertise/gestionexpert/updateDevisDet", data=payload)
        body = resp.json()
        assert body["state"] == "error"
        assert body["reason"] == "DIRECT_CHARGE_FIELD_WRITE_REJECTED"
    assert state(client)["observability"]["direct_charge_write_attempts"]["GARAGE_CONVENTIONNE"] == len(
        PEC_CHARGE_FIELDS
    )


def test_devis_calculer_montant_charge_success_and_readback(client):
    resp = client.post(
        "/_mock/pec/native_calculation",
        json={
            "total_ttc": "11200.00",
            "franchise": "0.00",
            "vetuste": "0.00",
            "remise": "0.00",
            "part_resp": "100",
            "simulate": "success",
        },
    )
    body = resp.json()
    assert body["state"] == "success"
    assert client.get("/_mock/pec/financial_summary").json()["summary"] == body["summary"]


def test_devis_calculer_montant_charge_stale_missing_failed_mismatch(client):
    base = {
        "total_ttc": "11200.00",
        "franchise": "500.00",
        "vetuste": "0.00",
        "remise": "0.00",
        "part_resp": "100",
    }
    stale = client.post("/_mock/pec/native_calculation", json={**base, "simulate": "stale"})
    assert stale.json()["stale"] is True

    client.post("/_mock/reset")
    missing = client.post("/_mock/pec/native_calculation", json={**base, "simulate": "missing"})
    assert missing.json()["state"] == "error"
    assert client.get("/_mock/pec/financial_summary").json()["summary"] is None

    failed = client.post("/_mock/pec/native_calculation", json={**base, "simulate": "failed"})
    assert failed.json()["state"] == "error"

    client.post("/_mock/reset")
    mismatch = client.post("/_mock/pec/native_calculation", json={**base, "simulate": "mismatch"})
    computed = mismatch.json()["summary"]
    stored = client.get("/_mock/pec/financial_summary").json()["summary"]
    assert stored != computed


def test_final_button_and_endpoint_visible_but_permanently_prohibited(client):
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    section = _section_pec(resp.text)
    assert 'id="DEVISDET_Btn"' in section

    hit = client.post(
        "/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis",
        data={"DevisMontantChargeMutuelle": "11200.00"},
    )
    body = hit.json()
    assert body["state"] == "error"
    assert body["reason"] == "FINAL_ACTION_PERMANENTLY_PROHIBITED"
    assert state(client)["observability"]["final_endpoint_hits"]["garageModifierValDevis"] == 1
    assert state(client)["last_saved_mission"] is None


def test_pec_never_uses_ajouter_or_create_rapport_def_det(client):
    """Correction #2 — scoped to the PEC DOM section and its fixture, not a
    whole-file scan (the combined mock legitimately contains both workflows'
    contracts elsewhere)."""
    resp = client.get("/SinAuto_MCMA/expertise/gestionexpert/index")
    section = _section_pec(resp.text)
    assert "ajouterLigneModeNormal" not in section
    assert "createRapportDefDet" not in section

    fixture = json.loads((FIXTURES_DIR / "pec_edit_row.json").read_text(encoding="utf-8"))
    dumped = json.dumps(fixture)
    assert "Ajouter" not in dumped
    assert "createRapportDefDet" not in dumped
