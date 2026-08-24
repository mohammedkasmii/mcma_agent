import os
import sys
import json
import unittest
from decimal import Decimal

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mapper import WexiaToDossierMapper


class TestWexiaToDossierMapper(unittest.TestCase):

    def setUp(self):
        self.mapper = WexiaToDossierMapper()
        path = os.path.join(os.path.dirname(__file__), "..", "input_dossier", "dossier-se00009.json")
        with open(path, "r", encoding="utf-8") as f:
            self.se00009_data = json.load(f)

    def test_1_se00009_exact_rubriques_and_totals(self):
        """Test 1: dossier-se00009 produces exactly five rubriques with expected IDs and amounts."""
        res = self.mapper.map(self.se00009_data)
        self.assertEqual(res["matricule"], "36165-B-50")
        self.assertEqual(res["search_matricule"], "36165")
        self.assertEqual(res["mode_reparation"], "normal")
        self.assertEqual(res["selected_chiffrage_id"], "b82bcfb7-eb1a-47b8-83fc-7b4b144d9203")

        rubriques = res["rubriques"]
        self.assertEqual(len(rubriques), 5)

        # Check each rubrique specifically
        rub_map = {r["IdRubrique"]: r for r in rubriques}

        self.assertIn("1", rub_map)
        self.assertEqual(rub_map["1"]["MontantHT"], "5250.00")
        self.assertEqual(rub_map["1"]["Taxe"], "1050.00")
        self.assertEqual(rub_map["1"]["MontantTTC"], "6300.00")

        self.assertIn("22", rub_map)
        self.assertEqual(rub_map["22"]["MontantHT"], "1583.33")
        self.assertEqual(rub_map["22"]["Taxe"], "316.67")
        self.assertEqual(rub_map["22"]["MontantTTC"], "1900.00")

        self.assertIn("25", rub_map)
        self.assertEqual(rub_map["25"]["MontantHT"], "375.00")
        self.assertEqual(rub_map["25"]["Taxe"], "75.00")
        self.assertEqual(rub_map["25"]["MontantTTC"], "450.00")

        self.assertIn("20", rub_map)
        self.assertEqual(rub_map["20"]["MontantHT"], "833.33")
        self.assertEqual(rub_map["20"]["Taxe"], "166.67")
        self.assertEqual(rub_map["20"]["MontantTTC"], "1000.00")

        self.assertIn("7", rub_map)
        self.assertEqual(rub_map["7"]["MontantHT"], "2708.33")
        self.assertEqual(rub_map["7"]["Taxe"], "541.66")
        self.assertEqual(rub_map["7"]["MontantTTC"], "3249.99")

        # Overall totals
        total_ht = sum(Decimal(r["MontantHT"]) for r in rubriques)
        total_tva = sum(Decimal(r["Taxe"]) for r in rubriques)
        total_ttc = sum(Decimal(r["MontantTTC"]) for r in rubriques)

        self.assertEqual(total_ht, Decimal("10749.99"))
        self.assertEqual(total_tva, Decimal("2150.00"))
        self.assertEqual(total_ttc, Decimal("12899.99"))

    def test_2_normal_mode_not_conventionne_with_repairer(self):
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
        res = self.mapper.map(doc)
        self.assertEqual(res["mode_reparation"], "normal")

    def test_3_approved_chiffrage_beats_submitted(self):
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
        res = self.mapper.map(doc)
        self.assertEqual(res["selected_chiffrage_id"], "approved_chif")
        self.assertEqual(res["text_fields"]["MontantReparation"], "1200.00")

    def test_4_part_origin_aliases(self):
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
        res = self.mapper.map(doc)
        rub_map = {r["IdRubrique"]: r for r in res["rubriques"]}
        # Origine (A, B, C) -> Rubrique 1: 300
        self.assertEqual(rub_map["1"]["MontantHT"], "300.00")
        # Adaptable (D) -> Rubrique 2: 100
        self.assertEqual(rub_map["2"]["MontantHT"], "100.00")
        # Recuperation (E) -> Rubrique 3: 100
        self.assertEqual(rub_map["3"]["MontantHT"], "100.00")

    def test_5_glass_and_adhesive_mappings(self):
        """Test 5: Pare-brise, vitre, colle, kit colle and lunette mappings."""
        doc = {
            "dossier": {"license_plate": "12345-A-1", "mission_type": "normal"},
            "chiffrages": [
                {
                    "id": "c1",
                    "status": "approved",
                    "total_cost": 800,
                    "tax_amount": 160,
                    "final_cost": 960,
                    "lignes_pieces": [
                        {"item_name": "Pare-brise", "repair_action": "remplacement", "unit_price": 100},
                        {"item_name": "Pare brise", "repair_action": "reparation", "unit_price": 100},
                        {"item_name": "Vitre porte", "repair_action": "remplacement", "unit_price": 100},
                        {"item_name": "Vitre", "repair_action": "reparation", "unit_price": 100},
                        {"item_name": "Lunette arriere", "repair_action": "remplacement", "unit_price": 100},
                        {"item_name": "Colle Pare-brise", "repair_action": "remplacement", "unit_price": 100},
                        {"item_name": "Kit colle pare-brise", "repair_action": "remplacement", "unit_price": 100},
                        {"item_name": "Kit colle vitre", "repair_action": "remplacement", "unit_price": 100},
                    ]
                }
            ]
        }
        res = self.mapper.map(doc)
        rub_ids = {r["IdRubrique"] for r in res["rubriques"]}
        self.assertIn("22", rub_ids)  # REMPLACEMENT PARE-BRISE
        self.assertIn("21", rub_ids)  # REPARATION PARE-BRISE
        self.assertIn("20", rub_ids)  # REMPLACEMENT VITRE
        self.assertIn("19", rub_ids)  # REPARATION VITRE
        self.assertIn("24", rub_ids)  # REMPLACEMENT LUNETTE ARRIERE
        self.assertIn("25", rub_ids)  # COLLE
        self.assertIn("26", rub_ids)  # KIT COLLE PARE-BRISE ET LUNETTE ARRIERE
        self.assertIn("27", rub_ids)  # KIT COLLE VITRE

    def test_6_decimal_precision_and_tax_remainder_allocation(self):
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
        res = self.mapper.map(doc)
        total_tax = sum(Decimal(r["Taxe"]) for r in res["rubriques"])
        self.assertEqual(total_tax, Decimal("66.67"))

    def test_7_unknown_part_family_fails_closed(self):
        """Test 7: Unknown part family fails closed with ValueError."""
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
                        {"item_name": "XYZ Unknown Widget 999", "part_type": "original", "unit_price": 100}
                    ]
                }
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            self.mapper.map(doc)
        self.assertIn("Cannot determine part system family", str(ctx.exception))

    def test_8_unknown_labour_fails_closed(self):
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
        with self.assertRaises(ValueError) as ctx:
            self.mapper.map(doc)
        self.assertIn("Unknown labour type", str(ctx.exception))

    def test_9_conflicting_registrations_warning_and_review(self):
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
        res = self.mapper.map(doc)
        self.assertEqual(res["matricule"], "36165-B-50")
        self.assertEqual(res["mapping_status"], "needs_review")
        self.assertTrue(any("conflicts with authoritative" in w for w in res["warnings"]))

    def test_10_dates_formatted_dd_mm_yyyy(self):
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
        res = self.mapper.map(doc)
        self.assertEqual(res["text_fields"]["DateMECVeh"], "18/05/2024")
        self.assertEqual(res["text_fields"]["DateDevis"], "04/08/2024")

    def test_11_missing_optional_fields_skipped(self):
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
        res = self.mapper.map(doc)
        self.assertNotIn("Kilometrage", res["text_fields"])
        self.assertNotIn("DateMECVeh", res["text_fields"])
        self.assertNotIn("ObservationMission", res["text_fields"])

    def test_12_ged_documents_remain_disabled(self):
        """Test 12: GED/document downloading remains disabled."""
        res = self.mapper.map(self.se00009_data)
        self.assertEqual(res["documents"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
