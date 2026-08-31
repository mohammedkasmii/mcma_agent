"""Correction batch (owner amendment, section J) -- non-table header-field
FormFieldIntent: the five confirmed fields are produced from their
CONFIRMED sources, an out-of-range PartResponsabilite fails to
NeedsReview (never guessed), plan_hash changes when intents differ, and
the three deferred/unmapped fields (MontantReparation/MontantTVA/
MontantTTC, VehRepareI, TypeReforme) are never produced at all."""

import pytest

from mcma.domain.enums import FormFieldSelector, RepairWorkflow
from mcma.mapping.wexia import parse_wexia
from mcma.planning.plan import FormFieldIntent, build_mission_normal_plan


def _base_input(**overrides) -> dict:
    raw = {
        "dossier": {
            "reference_number": "REF-1",
            "mission_type": "normal",
            "incident_description": "MODE NORMAL",
            "is_reform": False,
        },
        "vehicule": {"license_plate": "11111-A-11"},
        "chiffrages": [
            {
                "id": "CH-1",
                "status": "approved",
                "is_final": True,
                "scenario_type": "repair",
                "total_cost": 10,
                "tax_amount": 2,
                "lignes_pieces": [
                    {"item_type": "part", "item_name": "pare-choc avant", "part_type": "original", "subtotal": 10}
                ],
            }
        ],
    }
    raw["dossier"].update(overrides.pop("dossier", {}))
    raw["vehicule"].update(overrides.pop("vehicule", {}))
    raw["chiffrages"][0].update(overrides.pop("chiffrage", {}))
    if "observations_expert" in overrides:
        raw["observations_expert"] = overrides.pop("observations_expert")
    if "assureur" in overrides:
        raw["assureur"] = overrides.pop("assureur")
    return raw


def _build(raw: dict):
    return build_mission_normal_plan(parse_wexia(raw))


def test_no_form_field_intents_when_no_source_fields_present():
    plan = _build(_base_input())
    assert plan.form_field_intents == ()


def test_kilometrage_from_vehicule_preferred_over_dossier():
    plan = _build(_base_input(vehicule={"mileage_km": 40000}, dossier={"mileage_km": 99999}))
    kil = [i for i in plan.form_field_intents if i.selector is FormFieldSelector.KILOMETRAGE]
    assert len(kil) == 1
    assert kil[0].value == "40000"


def test_kilometrage_falls_back_to_dossier():
    plan = _build(_base_input(dossier={"mileage_km": 12345}))
    kil = [i for i in plan.form_field_intents if i.selector is FormFieldSelector.KILOMETRAGE]
    assert kil[0].value == "12345"


def test_market_value_dual_writes_both_selectors():
    plan = _build(_base_input(vehicule={"market_value": 55000}))
    selectors = {i.selector for i in plan.form_field_intents}
    assert FormFieldSelector.VALEUR_VENALE in selectors
    assert FormFieldSelector.VALEUR_VENALE_ESTIME in selectors
    values = {i.value for i in plan.form_field_intents if i.selector in (FormFieldSelector.VALEUR_VENALE, FormFieldSelector.VALEUR_VENALE_ESTIME)}
    assert values == {"55000"}


def test_nbre_jour_immobilisation_only_when_positive():
    plan_zero = _build(_base_input(chiffrage={"estimated_days": 0}))
    assert not any(i.selector is FormFieldSelector.NBRE_JOUR_IMMOBILISATION for i in plan_zero.form_field_intents)

    plan_positive = _build(_base_input(chiffrage={"estimated_days": 5}))
    matches = [i for i in plan_positive.form_field_intents if i.selector is FormFieldSelector.NBRE_JOUR_IMMOBILISATION]
    assert matches[0].value == "5"


def test_part_responsabilite_accepts_confirmed_values():
    for rate in (0, 50, 100):
        plan = _build(_base_input(dossier={"responsibility_rate": rate}))
        matches = [i for i in plan.form_field_intents if i.selector is FormFieldSelector.PART_RESPONSABILITE]
        assert matches[0].value == str(rate)
        assert plan.needs_review == ()


def test_part_responsabilite_falls_back_to_assureur():
    plan = _build(_base_input(assureur={"responsibility_rate": 50}))
    matches = [i for i in plan.form_field_intents if i.selector is FormFieldSelector.PART_RESPONSABILITE]
    assert matches[0].value == "50"


def test_part_responsabilite_out_of_range_becomes_needs_review_never_guessed():
    plan = _build(_base_input(dossier={"responsibility_rate": 75}))
    assert not any(i.selector is FormFieldSelector.PART_RESPONSABILITE for i in plan.form_field_intents)
    assert len(plan.needs_review) == 1
    assert plan.needs_review[0].reason.value == "INVALID_RESPONSIBILITY_RATE"
    assert plan.is_writeable is False  # NeedsReview present -> non-writeable


def test_observation_mission_from_observations_expert_texte_not_incident_description():
    """The confirmed source is observations_expert.texte, NOT
    dossier.incident_description -- proven here by setting ONLY
    incident_description and confirming no ObservationMission intent is
    produced, then setting observations_expert.texte and confirming it IS."""
    plan_without = _build(_base_input(dossier={"incident_description": "some free text mentioning normal mode"}))
    assert not any(i.selector is FormFieldSelector.OBSERVATION_MISSION for i in plan_without.form_field_intents)

    plan_with = _build(_base_input(observations_expert={"texte": "Expert observation text."}))
    matches = [i for i in plan_with.form_field_intents if i.selector is FormFieldSelector.OBSERVATION_MISSION]
    assert matches[0].value == "Expert observation text."


def test_observation_mission_falls_back_to_dossier_expert_observations():
    plan = _build(_base_input(dossier={"expert_observations": "fallback text"}))
    matches = [i for i in plan.form_field_intents if i.selector is FormFieldSelector.OBSERVATION_MISSION]
    assert matches[0].value == "fallback text"


def test_deferred_and_unmapped_fields_are_never_produced():
    """MontantReparation/MontantTVA/MontantTTC (portal-computed risk),
    VehRepareI and TypeReforme (no confirmed JSON source) have NO
    FormFieldSelector member at all -- structurally impossible to
    produce, not merely untested."""
    implemented = {s.value for s in FormFieldSelector}
    assert "MontantReparation" not in implemented
    assert "MontantTVA" not in implemented
    assert "MontantTTC" not in implemented
    assert "VehRepareI" not in implemented
    assert "TypeReforme" not in implemented


def test_form_field_intents_change_the_plan_hash():
    plan_a = _build(_base_input())
    plan_b = _build(_base_input(vehicule={"mileage_km": 12345}))
    assert plan_a.provenance.plan_hash != plan_b.provenance.plan_hash


def test_form_field_intents_are_deterministic_across_repeated_builds():
    raw = _base_input(vehicule={"mileage_km": 12345, "market_value": 60000}, dossier={"responsibility_rate": 50})
    plan_1 = _build(raw)
    plan_2 = _build(raw)
    assert plan_1.form_field_intents == plan_2.form_field_intents
    assert plan_1.provenance.plan_hash == plan_2.provenance.plan_hash


def test_form_field_intent_rejects_a_non_enum_selector():
    with pytest.raises(TypeError):
        FormFieldIntent(selector="Kilometrage", value="1", applicable_workflows=(RepairWorkflow.MODE_NORMAL,))


def test_form_field_intent_rejects_empty_value():
    with pytest.raises(ValueError):
        FormFieldIntent(selector=FormFieldSelector.KILOMETRAGE, value="", applicable_workflows=(RepairWorkflow.MODE_NORMAL,))


def test_form_field_intent_rejects_no_applicable_workflows():
    with pytest.raises(ValueError):
        FormFieldIntent(selector=FormFieldSelector.KILOMETRAGE, value="1", applicable_workflows=())
