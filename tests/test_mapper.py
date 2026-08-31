import os
import sys
import pytest
from decimal import Decimal

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mapper import WexiaToDossierMapper


FALLBACK_SE00009_DATA = {
    "dossier": {
        "claim_number": "se00009",
        "vehicle_make": "DACIA",
        "vehicle_model": "SANDERO",
        "vehicle_year": 2026,
        "license_plate": "36165-B-50",
        "incident_date": "2024-08-02T00:00:00+00:00",
        "incident_description": "MODE NORMAL",
        "market_value": 150000,
        "mission_type": "normal",
        "salvage_value": 18000,
        "first_registration_date": "2026-05-18",
        "insured_type": "location_voiture",
        "reference_number": "MCM24-08-26.WEX9066",
        "responsibility_rate": 100,
        "is_reform": False,
    },
    "vehicule": {
        "make": "DACIA",
        "model": "SANDERO",
        "year": 2026,
        "license_plate": "36165-B-50",
        "first_registration_date": "2026-05-18",
        "market_value": 150000,
        "salvage_value": 18000,
    },
    "assureur": {
        "nom": "MCMA",
        "reference_dossier": "MCM24-08-26.WEX9066",
        "responsibility_rate": 100,
    },
    "devis": [
        {
            "extracted_data": {
                "immatriculation": "36165-U-50",
                "date_devis": "2024-08-04",
                "total_ttc": 12900,
                "total_ht": 10750,
                "tva_amount": 2150
            }
        }
    ],
    "chiffrages": [
        {
            "id": "b82bcfb7-eb1a-47b8-83fc-7b4b144d9203",
            "status": "approved",
            "scenario_type": "repair",
            "is_final": False,
            "total_cost": 10749.99,
            "tax_amount": 2150.00,
            "final_cost": 12899.99,
            "lignes_pieces": [
                {"item_name": "2 Portes (AR) (D)", "item_type": "part", "part_type": "original", "repair_action": "remplacement", "subtotal": 4583.33, "unit_price": 2291.67},
                {"item_name": "Retroviseur", "item_type": "part", "part_type": "original", "repair_action": "remplacement", "subtotal": 666.67, "unit_price": 666.67},
                {"item_name": "Pare-brise", "item_type": "part", "part_type": "original", "repair_action": "remplacement", "subtotal": 1583.33, "unit_price": 1583.33},
                {"item_name": "Colle Pare-brise", "item_type": "part", "part_type": "original", "repair_action": "remplacement", "subtotal": 375.00, "unit_price": 187.50},
                {"item_name": "Vitre porte", "item_type": "part", "part_type": "original", "repair_action": "remplacement", "subtotal": 833.33, "unit_price": 833.33},
                {"item_name": "MONTAGE", "item_type": "labor", "notes": "carrosserie", "subtotal": 208.33, "unit_price": 208.33},
                {"item_name": "Carrosserie de face", "item_type": "labor", "notes": "carrosserie", "subtotal": 2500.00, "unit_price": 2500.00},
            ]
        }
    ]
}


@pytest.fixture
def mapper():
    return WexiaToDossierMapper()


@pytest.fixture
def se00009_data():
    """Pilot-integration correction: this fixture used to try loading a
    REAL file from input_dossier/ first, falling back to synthetic data
    only if that file was absent -- meaning a machine that happened to
    have input_dossier/ populated ran this automated test against real
    claimant data, silently and non-reproducibly. It now always returns
    the committed synthetic fixture; input_dossier/ is never referenced
    by any automated test (see test_no_automated_test_references_input_
    dossier)."""
    return FALLBACK_SE00009_DATA


def test_1_se00009_exact_rubriques_and_totals(mapper, se00009_data):
    """Test 1: dossier-se00009 produces exact rubriques (Fournitures Carrosserie Origines, Colle, M.O Carrosserie)."""
    res = mapper.map(se00009_data)
    assert res["matricule"] == "36165-B-50"
    assert res["search_matricule"] == "36165"
    assert res["mode_reparation"] == "normal"
    assert res["selected_chiffrage_id"] == "b82bcfb7-eb1a-47b8-83fc-7b4b144d9203"

    rubriques = res["rubriques"]
    assert len(rubriques) == 3

    # Check each rubrique specifically
    rub_map = {r["IdRubrique"]: r for r in rubriques}

    # 1. Fournitures Carrosserie Origines (2 Portes + Retroviseur + Pare-brise + Vitre porte)
    assert "1" in rub_map
    assert rub_map["1"]["MontantHT"] == "7666.66"
    assert rub_map["1"]["Taxe"] == "1533.33"
    assert rub_map["1"]["MontantTTC"] == "9199.99"

    # 2. Colle
    assert "25" in rub_map
    assert rub_map["25"]["MontantHT"] == "375.00"
    assert rub_map["25"]["Taxe"] == "75.00"
    assert rub_map["25"]["MontantTTC"] == "450.00"

    # 3. Main d'oeuvre Carrosserie (MONTAGE + Carrosserie de face)
    assert "7" in rub_map
    assert rub_map["7"]["MontantHT"] == "2708.33"
    assert rub_map["7"]["Taxe"] == "541.67"
    assert rub_map["7"]["MontantTTC"] == "3250.00"

    # Overall totals
    total_ht = sum(Decimal(r["MontantHT"]) for r in rubriques)
    total_tva = sum(Decimal(r["Taxe"]) for r in rubriques)
    total_ttc = sum(Decimal(r["MontantTTC"]) for r in rubriques)

    assert total_ht == Decimal("10749.99")
    assert total_tva == Decimal("2150.00")
    assert total_ttc == Decimal("12899.99")


def test_2_normal_mode_not_conventionne_with_repairer(mapper):
    """Test 2: Explicit normal mode is not changed to conventionne because a repairer exists."""
    doc = {
        "dossier": {
            "license_plate": "12345-A-1",
            "mission_type": "normal",
            "incident_description": "MODE NORMAL"
        },
        "devis": [
            {
                "repairer_id": "rep-999",
                "repairer_name": "GARAGE BARCELONA",
                "extracted_data": {"immatriculation": "12345-A-1"}
            }
        ],
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 1000,
                "tax_amount": 200,
                "final_cost": 1200,
                "lignes_pieces": [
                    {"item_name": "Porte avant", "part_type": "original", "unit_price": 1000}
                ]
            }
        ]
    }
    res = mapper.map(doc)
    assert res["mode_reparation"] == "normal"


def test_3_approved_chiffrage_beats_submitted(mapper):
    """Test 3: Approved detailed chiffrage beats submitted chiffrage even if submitted is larger."""
    doc = {
        "dossier": {"license_plate": "12345-A-1", "mission_type": "normal"},
        "chiffrages": [
            {
                "id": "submitted_chif",
                "status": "submitted",
                "total_cost": 50000,
                "tax_amount": 10000,
                "final_cost": 60000,
                "lignes_pieces": [
                    {"item_name": "Porte avant", "part_type": "original", "unit_price": 50000}
                ]
            },
            {
                "id": "approved_chif",
                "status": "approved",
                "total_cost": 1000,
                "tax_amount": 200,
                "final_cost": 1200,
                "lignes_pieces": [
                    {"item_name": "Porte avant", "part_type": "original", "unit_price": 1000}
                ]
            }
        ]
    }
    res = mapper.map(doc)
    assert res["selected_chiffrage_id"] == "approved_chif"
    assert res["text_fields"]["MontantReparation"] == "1200.00"


def test_4_part_origin_aliases(mapper):
    """Test 4: original, origine, neuf, adaptable and recuperation aliases."""
    doc = {
        "dossier": {"license_plate": "12345-A-1", "mission_type": "normal"},
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 500,
                "tax_amount": 100,
                "final_cost": 600,
                "lignes_pieces": [
                    {"item_name": "Porte A", "part_type": "neuf", "unit_price": 100},
                    {"item_name": "Porte B", "part_type": "origine", "unit_price": 100},
                    {"item_name": "Porte C", "part_type": "oem", "unit_price": 100},
                    {"item_name": "Porte D", "part_type": "adaptable", "unit_price": 100},
                    {"item_name": "Porte E", "part_type": "recuperation", "unit_price": 100},
                ]
            }
        ]
    }
    res = mapper.map(doc)
    rub_map = {r["IdRubrique"]: r for r in res["rubriques"]}
    # Origine (A, B, C) -> Rubrique 1: 300
    assert rub_map["1"]["MontantHT"] == "300.00"
    # Adaptable (D) -> Rubrique 2: 100
    assert rub_map["2"]["MontantHT"] == "100.00"
    # Recuperation (E) -> Rubrique 3: 100
    assert rub_map["3"]["MontantHT"] == "100.00"


def test_5_colle_and_labour_mappings(mapper):
    """Test 5: Colle, kit colle and distinct labour families (carrosserie, peinture, mecanique, electrique)."""
    doc = {
        "dossier": {"license_plate": "12345-A-1", "mission_type": "normal"},
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 700,
                "tax_amount": 140,
                "final_cost": 840,
                "lignes_pieces": [
                    {"item_name": "Colle Pare-brise", "part_type": "original", "unit_price": 100},
                    {"item_name": "Kit colle pare-brise", "part_type": "original", "unit_price": 100},
                    {"item_name": "Kit colle vitre", "part_type": "original", "unit_price": 100},
                    {"item_name": "Tôlerie porte", "item_type": "labor", "notes": "carrosserie", "unit_price": 100},
                    {"item_name": "Peinture complète", "item_type": "labor", "notes": "peinture", "unit_price": 100},
                    {"item_name": "Réparation moteur", "item_type": "labor", "notes": "mecanique", "unit_price": 100},
                    {"item_name": "Câblage phare", "item_type": "labor", "notes": "electrique", "unit_price": 100},
                ]
            }
        ]
    }
    res = mapper.map(doc)
    rub_ids = {r["IdRubrique"] for r in res["rubriques"]}
    assert "25" in rub_ids  # COLLE
    assert "26" in rub_ids  # KIT COLLE PARE-BRISE ET LUNETTE ARRIERE
    assert "27" in rub_ids  # KIT COLLE VITRE
    assert "7" in rub_ids   # MAIN D'OEUVRE CARROSSERIE
    assert "12" in rub_ids  # MAIN D'OEUVRE PEINTURE
    assert "8" in rub_ids   # MAIN D'OEUVRE MECANIQUE
    assert "28" in rub_ids  # MAIN D'OEUVRE ELECTRIQUE



def test_6_decimal_precision_and_tax_remainder_allocation(mapper):
    """Test 6: Decimal precision and exact tax remainder allocation."""
    doc = {
        "dossier": {"license_plate": "12345-A-1", "mission_type": "normal"},
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": "333.33",
                "tax_amount": "66.67",
                "final_cost": "400.00",
                "lignes_pieces": [
                    {"item_name": "Porte avant", "part_type": "original", "unit_price": "166.66"},
                    {"item_name": "Porte arriere", "part_type": "adaptable", "unit_price": "166.67"},
                ]
            }
        ]
    }
    res = mapper.map(doc)
    total_tax = sum(Decimal(r["Taxe"]) for r in res["rubriques"])
    assert total_tax == Decimal("66.67")


def test_7_unknown_part_type_fails_closed(mapper):
    """Test 7: Unknown part_type fails closed with ValueError."""
    doc = {
        "dossier": {"license_plate": "12345-A-1", "mission_type": "normal"},
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 100,
                "tax_amount": 20,
                "final_cost": 120,
                "lignes_pieces": [
                    {"item_name": "Porte avant", "part_type": "unknown_invalid_type", "unit_price": 100}
                ]
            }
        ]
    }
    with pytest.raises(ValueError, match="Unknown or missing part_type"):
        mapper.map(doc)



def test_8_unknown_labour_fails_closed(mapper):
    """Test 8: Unknown labour fails closed with ValueError."""
    doc = {
        "dossier": {"license_plate": "12345-A-1", "mission_type": "normal"},
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 100,
                "tax_amount": 20,
                "final_cost": 120,
                "lignes_pieces": [
                    {"item_name": "Alien Telepathic Labor", "item_type": "labor", "unit_price": 100}
                ]
            }
        ]
    }
    with pytest.raises(ValueError, match="Unknown labour type"):
        mapper.map(doc)


def test_9_conflicting_registrations_warning_and_review(mapper):
    """Test 9: Conflicting registrations produce a warning and needs_review state."""
    doc = {
        "dossier": {"license_plate": "36165-B-50", "mission_type": "normal"},
        "devis": [
            {"extracted_data": {"immatriculation": "36165-U-50"}}
        ],
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 100,
                "tax_amount": 20,
                "final_cost": 120,
                "lignes_pieces": [{"item_name": "Porte", "part_type": "original", "unit_price": 100}]
            }
        ]
    }
    res = mapper.map(doc)
    assert res["matricule"] == "36165-B-50"
    assert res["mapping_status"] == "needs_review"
    assert any("conflicts with authoritative" in w for w in res["warnings"])


def test_10_dates_formatted_dd_mm_yyyy(mapper):
    """Test 10: Dates are formatted as DD/MM/YYYY."""
    doc = {
        "dossier": {
            "license_plate": "12345-A-1",
            "first_registration_date": "2024-05-18",
            "incident_date": "2024-08-02",
            "mission_type": "normal"
        },
        "devis": [
            {"extracted_data": {"date_devis": "2024-08-04", "immatriculation": "12345-A-1"}}
        ],
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 100,
                "tax_amount": 20,
                "final_cost": 120,
                "lignes_pieces": [{"item_name": "Porte", "part_type": "original", "unit_price": 100}]
            }
        ]
    }
    res = mapper.map(doc)
    assert res["text_fields"]["DateMECVeh"] == "18/05/2024"
    assert res["text_fields"]["DateDevis"] == "04/08/2024"


def test_11_missing_optional_fields_skipped(mapper):
    """Test 11: Missing optional fields are skipped without crashing."""
    doc = {
        "dossier": {"license_plate": "12345-A-1"},
        "chiffrages": [
            {
                "id": "c1",
                "status": "approved",
                "total_cost": 100,
                "tax_amount": 20,
                "final_cost": 120,
                "lignes_pieces": [{"item_name": "Porte", "part_type": "original", "unit_price": 100}]
            }
        ]
    }
    res = mapper.map(doc)
    assert "Kilometrage" not in res["text_fields"]
    assert "DateMECVeh" not in res["text_fields"]
    assert "ObservationMission" not in res["text_fields"]


def test_12_ged_documents_remain_disabled(mapper, se00009_data):
    """Test 12: GED/document downloading remains disabled."""
    res = mapper.map(se00009_data)
    assert res["documents"] == []
