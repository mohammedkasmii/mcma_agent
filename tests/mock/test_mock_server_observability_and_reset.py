"""
INC-06 — observable mock state per workflow, and deterministic reset.
"""

from conftest import state


def test_reset_restores_deterministic_initial_state(client):
    baseline = state(client)

    client.post(
        "/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
        data={
            "IdRubrique": "7",
            "MontantHT": "1.00",
            "Taxe": "0.00",
            "MontantTTC": "1.00",
            "TauxVetuste": "0.00",
            "MontantVetuste": "0.00",
            "TempRowId": "tmp-reset",
        },
    )
    client.post(
        "/_mock/field_event",
        json={"workflow": "MODE_NORMAL", "row_id": "tmp-reset", "field": "MontantHT", "event_type": "input"},
    )
    mutated = state(client)
    assert mutated != baseline

    client.post("/_mock/reset")
    restored = state(client)
    assert restored == baseline


def test_field_event_history_recorded_per_workflow(client):
    client.post(
        "/_mock/field_event",
        json={"workflow": "MODE_NORMAL", "row_id": "r1", "field": "MontantHT", "event_type": "input"},
    )
    client.post(
        "/_mock/field_event",
        json={"workflow": "GARAGE_CONVENTIONNE", "row_id": "2", "field": "TaxeValide", "event_type": "blur"},
    )
    st = state(client)
    normal_events = st["observability"]["field_event_history"]["MODE_NORMAL"]
    pec_events = st["observability"]["field_event_history"]["GARAGE_CONVENTIONNE"]
    assert len(normal_events) == 1 and normal_events[0]["field"] == "MontantHT"
    assert len(pec_events) == 1 and pec_events[0]["event_type"] == "blur"


def test_redraw_version_increments_only_on_successful_row_mutation(client):
    before = state(client)["observability"]["redraw_version"]["MODE_NORMAL"]
    client.post(
        "/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
        data={
            "IdRubrique": "7",
            "MontantHT": "1.00",
            "Taxe": "0.00",
            "MontantTTC": "1.00",
            "TauxVetuste": "0.00",
            "MontantVetuste": "0.00",
            "TempRowId": "tmp-redraw",
        },
    )
    after = state(client)["observability"]["redraw_version"]["MODE_NORMAL"]
    assert after == before + 1

    # A rejected duplicate must not bump the redraw version again.
    client.post(
        "/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet",
        data={
            "IdRubrique": "7",
            "MontantHT": "1.00",
            "Taxe": "0.00",
            "MontantTTC": "1.00",
            "TauxVetuste": "0.00",
            "MontantVetuste": "0.00",
            "TempRowId": "tmp-redraw",
        },
    )
    assert state(client)["observability"]["redraw_version"]["MODE_NORMAL"] == after
