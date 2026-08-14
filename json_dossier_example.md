```json
{
  "meta": {
    "format": "wexia.dossier.full",
    "schema_version": "2.0",
    "generated_at": "2026-08-14T15:43:00.000Z",
    "generated_by": {
      "id": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
      "email": "fatima.zahrae@cabinet-expert.ma"
    },
    "signed_url_expires_in_seconds": 2592000,
    "source_project_url": "https://xyzabc.supabase.co",
    "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
    "restitution_notes": "Ce fichier contient l'intégralité du dossier + liens (signés 30j) vers photos, PDF, pièces jointes.",
    "archive_path": "7e2c9f4a-5678-4def-b001-112233445566/dossier-2026-08-14T15-43-00-000Z.json",
    "archive_signed_url": "https://xyzabc.supabase.co/storage/v1/object/sign/claim-archives/7e2c9f4a/dossier-2026-08-14T15-43-00-000Z.json?token=eyJhbGci..."
  },

  "dossier": {
    "id": "7e2c9f4a-5678-4def-b001-112233445566",
    "claim_number": "CLM-26-000847",
    "reference_number": "RMA14-08-26.WEX047",
    "user_id": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
    "status": "reviewed",
    "kpi_status": "quote_validated",
    "mission_type": "normal",
    "guarantee_type": "dta",
    "vehicle_make": "RENAULT",
    "vehicle_model": "DUSTER",
    "vehicle_year": 2019,
    "vehicle_category": "C2",
    "vehicle_usage": "Personnel",
    "license_plate": "12345-A-7",
    "first_registration_date": "2019-03-15",
    "motorisation": "Thermique",
    "fuel_type": "Diesel",
    "fiscal_power": 7,
    "mileage_km": 87500,
    "valeur_neuf": 210000,
    "market_value": 148000,
    "market_value_calculation": {
      "method": "depreciation",
      "valeur_neuf": 210000,
      "age_years": 7.4,
      "taux_depreciation_annuel": 0.09,
      "coefficient": 0.706,
      "result": 148260
    },
    "salvage_value": null,
    "salvage_value_calculated": null,
    "salvage_calculation": null,
    "is_reform": false,
    "reform_type": null,
    "repair_status": "en_cours",
    "insured_name": "ALAOUI",
    "insured_first_name": "Mohamed",
    "insured_phone": "+212661234567",
    "insured_email": "m.alaoui@gmail.com",
    "insured_type": "physique",
    "cin_assure": "BK123456",
    "policy_number": "DTA-RMA-2024-098765",
    "insurer": "RMA",
    "responsibility_rate": 100,
    "responsibility_rate_enabled": true,
    "incident_date": "2026-08-10T00:00:00.000Z",
    "incident_description": "Collision frontale avec un autre véhicule au carrefour de l'avenue Mohammed V et rue Hassan II à Casablanca.",
    "expertise_city": "Casablanca",
    "expert_observations": "Dommages constatés sur la partie avant du véhicule. Aile avant droite enfoncée avec pli de tôle. Pare-chocs avant fissuré sur toute la longueur. Phare avant droit brisé. Capot bosselé avec déformation modérée. Grille calandre arrachée.",
    "vehicle_condition_score": 72,
    "vehicle_condition_notes": "État général acceptable pour l'âge du véhicule.",
    "tire_wear_front_left": 35,
    "tire_wear_front_right": 38,
    "tire_wear_rear_left": 20,
    "tire_wear_rear_right": 22,
    "epaviste_nom": null,
    "epaviste_prenom": null,
    "epaviste_adresse": null,
    "epaviste_telephone": null,
    "epaviste_ville": null,
    "photo_requirements_waived": false,
    "source": "web",
    "tracking_token": "tkn_a1b2c3d4e5f6789012345678",
    "tracking_url": "https://impact-vision-ai.lovable.app/suivi/CLM-26-000847?t=tkn_a1b2c3d4e5f6789012345678",
    "archived_at": null,
    "archived_by": null,
    "archive_zip_url": null,
    "deleted_at": null,
    "deleted_by": null,
    "created_at": "2026-08-14T08:15:22.000Z",
    "updated_at": "2026-08-14T15:40:11.000Z"
  },

  "vehicule": {
    "make": "RENAULT",
    "model": "DUSTER",
    "year": 2019,
    "license_plate": "12345-A-7",
    "category": "C2",
    "first_registration_date": "2019-03-15",
    "mileage_km": 87500,
    "market_value": 148000,
    "market_value_calculation": {
      "method": "depreciation",
      "valeur_neuf": 210000,
      "age_years": 7.4,
      "coefficient": 0.706
    },
    "salvage_value": null,
    "salvage_value_calculated": null,
    "salvage_calculation": null,
    "condition_score": 72,
    "condition_notes": "État général acceptable pour l'âge du véhicule.",
    "tire_wear": {
      "front_left": 35,
      "front_right": 38,
      "rear_left": 20,
      "rear_right": 22
    },
    "carte_grise_extractions": [
      {
        "id": "cge-0001-aaaa",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "document_id": "doc-0001-carte-grise",
        "marque": "RENAULT",
        "modele": "DUSTER 1.5 DCI",
        "genre": "VP",
        "type_vehicule": "SUV",
        "immatriculation": "12345-A-7",
        "energie": "Diesel",
        "puissance_fiscale": 7,
        "places_assises": 5,
        "ptac": 1870,
        "numero_serie": "VF1HJABA5K0123456",
        "date_premiere_mise_en_circulation": "2019-03-15",
        "proprietaire_nom": "ALAOUI",
        "proprietaire_prenom": "Mohamed",
        "proprietaire_adresse": "123 Rue Allal Ben Abdellah, Casablanca",
        "date_dernier_controle": "2025-03-10",
        "resultat_controle": "FAVORABLE",
        "assureur": "RMA",
        "numero_police": "DTA-RMA-2024-098765",
        "date_effet_assurance": "2025-01-01",
        "date_fin_assurance": "2025-12-31",
        "date_accident": null,
        "lieu_accident": null,
        "circonstances": null,
        "manually_edited": false,
        "created_at": "2026-08-14T08:20:11.000Z",
        "updated_at": "2026-08-14T08:20:11.000Z"
      }
    ]
  },

  "assure": {
    "type": "physique",
    "nom": "ALAOUI",
    "prenom": "Mohamed",
    "cin": "BK123456",
    "telephone": "+212661234567",
    "email": "m.alaoui@gmail.com"
  },

  "assureur": {
    "nom": "RMA",
    "reference_dossier": "RMA14-08-26.WEX047",
    "responsibility_rate": 100,
    "responsibility_rate_enabled": true,
    "format_reference": {
      "id": "fmt-rma-001",
      "insurer_name": "RMA",
      "prefix": "RMA",
      "format_pattern": "{PREFIX}{DD}-{MM}-{YY}.WEX{NNN}",
      "example": "RMA14-08-26.WEX047"
    },
    "attestation_extractions": [
      {
        "id": "att-0001-aaaa",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "assureur": "RMA",
        "numero_police": "DTA-RMA-2024-098765",
        "assure_nom": "ALAOUI",
        "assure_prenom": "Mohamed",
        "assure_adresse": "123 Rue Allal Ben Abdellah, Casablanca",
        "immatriculation": "12345-A-7",
        "type_garantie": "DTA - Dommages Tous Accidents",
        "date_effet": "2025-01-01",
        "date_fin": "2025-12-31",
        "manually_edited": false,
        "created_at": "2026-08-14T08:22:00.000Z"
      }
    ]
  },

  "accident": {
    "description": "Collision frontale avec un autre véhicule au carrefour de l'avenue Mohammed V et rue Hassan II à Casablanca.",
    "date": "2026-08-10T00:00:00.000Z",
    "constat_extractions": [
      {
        "id": "acc-0001-aaaa",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "date_accident": "2026-08-10",
        "heure_accident": "14:35",
        "lieu_accident": "Carrefour Av. Mohammed V / Rue Hassan II, Casablanca",
        "circonstances": "Le véhicule A n'a pas respecté le feu rouge.",
        "degats": "Dommages importants à l'avant du véhicule A. Dommages légers sur le côté gauche du véhicule B.",
        "vehicule_a_immatriculation": "12345-A-7",
        "vehicule_a_conducteur": "ALAOUI Mohamed",
        "vehicule_a_assureur": "RMA",
        "vehicule_a_numero_police": "DTA-RMA-2024-098765",
        "vehicule_b_immatriculation": "67890-B-2",
        "vehicule_b_conducteur": "BENNANI Youssef",
        "vehicule_b_assureur": "WAFA",
        "vehicule_b_numero_police": "RC-WAFA-2025-054321",
        "croquis_url": "7e2c9f4a-5678-4def-b001-112233445566/croquis_constat.jpg",
        "manually_edited": false,
        "created_at": "2026-08-14T08:25:00.000Z"
      }
    ]
  },

  "epaviste": null,

  "missions": [
    {
      "id": "mission-0001-aaaa",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "assigned_to": "exp-uuid-0001-expert-karim",
      "assigned_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
      "status": "completed",
      "assigned_at": "2026-08-14T09:00:00.000Z",
      "notes": "Expertise avant travaux. Véhicule disponible chez garage AutoTech, Casablanca. Contact: 0522-123456."
    }
  ],

  "observations_expert": {
    "texte": "Dommages constatés sur la partie avant du véhicule. Aile avant droite enfoncée avec pli de tôle. Pare-chocs avant fissuré. Phare avant droit brisé. Capot bosselé. Grille calandre arrachée.",
    "analyses_dommages": [
      {
        "id": "da-0001-aaaa",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "image_url": "7e2c9f4a-5678-4def-b001-112233445566/photo_damage_1723622100000_abc123.jpg",
        "damage_description": "Impact frontal avec dommages importants sur l'aile AV droite (pli structurel), pare-chocs AV (fissure traversante), phare AV droit (destruction totale), capot (bosse modérée), et calandre (brisée).",
        "damage_severity": "level_3",
        "estimated_cost": 18500,
        "damaged_parts": {
          "parts": ["aile_avant_droite", "pare_chocs_avant", "phare_avant_droit", "capot", "calandre"],
          "annotations": [
            {"part": "aile_avant_droite", "x": 0.72, "y": 0.38, "color": "#ef4444"},
            {"part": "pare_chocs_avant",  "x": 0.50, "y": 0.85, "color": "#ef4444"},
            {"part": "phare_avant_droit", "x": 0.78, "y": 0.70, "color": "#f97316"},
            {"part": "capot",             "x": 0.50, "y": 0.40, "color": "#eab308"},
            {"part": "calandre",          "x": 0.50, "y": 0.75, "color": "#f97316"}
          ]
        },
        "ai_analysis": {
          "damage_description": "Impact frontal avec dommages importants sur la face avant.",
          "damage_severity": "level_3",
          "estimated_cost": 18500,
          "damage_types": [
            {
              "type": "deformation_structurelle",
              "location": "Aile avant droite",
              "severity": "grave",
              "confidence": 0.94,
              "repair_action": "remplacement",
              "repair_reason": "Pli de tôle structurel — réparation impossible, coût > 60% pièce neuve",
              "estimated_cost": 4200
            },
            {
              "type": "piece_cassee",
              "location": "Pare-chocs avant",
              "severity": "grave",
              "confidence": 0.97,
              "repair_action": "remplacement",
              "repair_reason": "Fissure traversante sur toute la longueur",
              "estimated_cost": 3500
            },
            {
              "type": "piece_cassee",
              "location": "Phare avant droit",
              "severity": "grave",
              "confidence": 0.99,
              "repair_action": "remplacement",
              "repair_reason": "Optique complètement détruite",
              "estimated_cost": 3800
            },
            {
              "type": "bosse",
              "location": "Capot",
              "severity": "moyen",
              "confidence": 0.88,
              "repair_action": "reparation",
              "repair_reason": "Bosse < 10cm sans pli structurel — débosselage possible",
              "estimated_cost": 1800
            },
            {
              "type": "piece_cassee",
              "location": "Calandre",
              "severity": "moyen",
              "confidence": 0.92,
              "repair_action": "remplacement",
              "repair_reason": "Plastique brisé non réparable",
              "estimated_cost": 1200
            }
          ],
          "safety_impact": true,
          "repair_urgency": "urgent",
          "reform_recommendation": {
            "is_reform": false,
            "reform_type": null,
            "reason": "Coût 18 500 DH < 80% valeur vénale — réparation économiquement viable"
          },
          "processing_time_ms": 4231,
          "ai_mode": "cloud"
        },
        "analyzed_at": "2026-08-14T08:35:12.000Z",
        "created_at": "2026-08-14T08:15:22.000Z"
      }
    ],
    "sketch_pieces_endommagees": [
      {"id": "sketch-0001", "claim_id": "7e2c9f4a-5678-4def-b001-112233445566", "part_name": "aile_avant_droite", "x": 0.72, "y": 0.38, "color": "#ef4444"}
    ],
    "rapport_extractions": [
      {
        "id": "re-0001-aaaa",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "report_type": "expertise_preliminaire",
        "numero_dossier": "RMA14-08-26.WEX047",
        "date_rapport": "2026-08-14",
        "date_sinistre": "2026-08-10",
        "marque_modele": "RENAULT DUSTER 1.5 DCI",
        "immatriculation": "12345-A-7",
        "annee": 2019,
        "vin": "VF1HJABA5K0123456",
        "kilometrage": 87500,
        "nature_sinistre": "Collision frontale",
        "lieu_sinistre": "Casablanca",
        "expert_name": "Karim BENSOUDA",
        "constatations": "Impact frontal avec dommages sur aile AV droite, pare-chocs AV, phare AV droit, capot et calandre.",
        "observations": "Véhicule non roulant. Risque de fuite radiateur à vérifier.",
        "circonstances_detaillees": "Non-respect du feu rouge à l'intersection.",
        "pieces_a_reparer": [{"piece": "Capot", "operation": "Débosselage + peinture", "heures_mo": 4.5}],
        "pieces_a_remplacer": [
          {"piece": "Aile avant droite", "reference": "631012353R"},
          {"piece": "Pare-chocs avant",  "reference": "620220007R"},
          {"piece": "Phare avant droit", "reference": "260103477R"},
          {"piece": "Calandre",          "reference": "623100001R"}
        ],
        "pieces_carrosserie": [{"piece": "Aile AV droite", "type": "remplacement"}],
        "pieces_mecaniques": [],
        "pieces_electriques": [{"piece": "Phare AV droit", "type": "remplacement"}],
        "dommages_avant": {"elements": ["aile_av_droite", "pare_chocs_avant", "phare_av_droit", "capot", "calandre"]},
        "dommages_arriere": null,
        "dommages_lateral_droit": {"elements": ["aile_av_droite"]},
        "dommages_lateral_gauche": null,
        "main_oeuvre": {"tolerie": 8, "mecanique": 0, "peinture": 6},
        "estimation_preliminaire": 18500,
        "estimation_total": 18500,
        "montant_total_pieces": 12700,
        "montant_total_mo": 4200,
        "montant_total_ht": 16900,
        "montant_total_ttc": 20280,
        "valeur_venale": 148000,
        "vetuste": 0,
        "conclusions": "Réparation économiquement viable. Dommages compatibles avec les circonstances déclarées.",
        "recommandations": "Vérifier l'état du radiateur avant mise en réparation.",
        "manually_edited": false,
        "created_at": "2026-08-14T14:00:00.000Z"
      }
    ]
  },

  "documents": {
    "cartes_grises_et_autres": [
      {
        "id": "doc-0001-carte-grise",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "document_type": "carte_grise",
        "document_side": "recto",
        "file_url": "7e2c9f4a-5678-4def-b001-112233445566/carte_grise_recto.jpg",
        "uploaded_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
        "uploaded_at": "2026-08-14T08:18:00.000Z",
        "file": {
          "bucket": "damage-photos",
          "path": "7e2c9f4a-5678-4def-b001-112233445566/carte_grise_recto.jpg",
          "url": "https://xyzabc.supabase.co/storage/v1/object/public/damage-photos/7e2c9f4a/carte_grise_recto.jpg",
          "public": true
        }
      },
      {
        "id": "doc-0004-photo-damage",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "document_type": "photo_damage",
        "document_side": "avant",
        "file_url": "7e2c9f4a-5678-4def-b001-112233445566/photo_damage_1723622100000_abc123.jpg",
        "uploaded_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
        "uploaded_at": "2026-08-14T08:15:30.000Z",
        "file": {
          "bucket": "damage-photos",
          "path": "7e2c9f4a-5678-4def-b001-112233445566/photo_damage_1723622100000_abc123.jpg",
          "url": "https://xyzabc.supabase.co/storage/v1/object/public/damage-photos/7e2c9f4a/photo_damage_1723622100000_abc123.jpg",
          "public": true
        }
      }
    ],
    "photos": [
      {
        "id": "ph-0001",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "photo_url": "7e2c9f4a-5678-4def-b001-112233445566/photo_damage_1723622100000_abc123.jpg",
        "analysis_data": {"width": 1920, "height": 1080, "size_kb": 847},
        "created_at": "2026-08-14T08:15:30.000Z",
        "file": {
          "bucket": "damage-photos",
          "url": "https://xyzabc.supabase.co/storage/v1/object/public/damage-photos/7e2c9f4a/photo_damage_1723622100000_abc123.jpg",
          "public": true
        }
      }
    ]
  },

  "devis": [
    {
      "id": "quote-0001-aaaa",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "repairer_name": "AutoTech Casablanca",
      "total_amount": 21500,
      "status": "validated",
      "file_url": "7e2c9f4a-5678-4def-b001-112233445566/devis_autotech_20260814.pdf",
      "created_at": "2026-08-14T10:00:00.000Z",
      "file": {
        "bucket": "damage-photos",
        "path": "7e2c9f4a-5678-4def-b001-112233445566/devis_autotech_20260814.pdf",
        "url": "https://xyzabc.supabase.co/storage/v1/object/sign/damage-photos/7e2c9f4a/devis_autotech_20260814.pdf?token=eyJhbGci...",
        "public": false
      }
    }
  ],

  "factures": [],

  "chiffrages": [
    {
      "id": "est-0001-aaaa",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "version_number": 1,
      "version_label": "Chiffrage initial — Devis AutoTech",
      "document_type": "devis",
      "scenario_type": "standard",
      "source_type": "quote",
      "source_quote_id": "quote-0001-aaaa",
      "source_invoice_id": null,
      "status": "approved",
      "workflow_status": "validated_secretary",
      "total_parts_cost": 12700,
      "total_labor_cost": 4200,
      "total_cost": 16900,
      "tax_amount": 3380,
      "final_cost": 20280,
      "indemnification_amount": 20280,
      "market_value": 148000,
      "salvage_value": null,
      "is_reform": false,
      "reform_type": null,
      "estimated_days": 7,
      "notes": "Conforme au devis garage. Radiateur non inclus — à vérifier lors de la mise en réparation.",
      "is_final": true,
      "parent_estimate_id": null,
      "selected_repairer_id": null,
      "created_by": "chiffreur-uuid-0001",
      "created_at": "2026-08-14T11:00:00.000Z",
      "approved_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
      "approved_at": "2026-08-14T13:30:00.000Z",
      "sent_to_chiffreur_at": "2026-08-14T10:30:00.000Z",
      "sent_to_chiffreur_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
      "sent_to_secretary_at": "2026-08-14T12:45:00.000Z",
      "sent_to_secretary_by": "chiffreur-uuid-0001",
      "submitted_at": "2026-08-14T12:45:00.000Z",
      "requested_changes": null,
      "archive_cycle": 1,
      "updated_at": "2026-08-14T13:30:00.000Z",
      "lignes_pieces": [
        {
          "id": "li-0001",
          "estimate_id": "est-0001-aaaa",
          "item_name": "Aile avant droite",
          "item_type": "piece",
          "part_type": "Neuf",
          "part_id": "part-uuid-aile-av-d",
          "quantity": 1,
          "unit_price": 4200,
          "original_price": 4200,
          "depreciation_rate": 0,
          "depreciation_amount": 0,
          "labor_hours": 3.0,
          "repair_action": "remplacement",
          "subtotal": 4200,
          "notes": "Référence OEM 631012353R"
        },
        {
          "id": "li-0002",
          "estimate_id": "est-0001-aaaa",
          "item_name": "Pare-chocs avant complet",
          "item_type": "piece",
          "part_type": "Neuf",
          "quantity": 1,
          "unit_price": 3500,
          "original_price": 3500,
          "depreciation_rate": 0,
          "depreciation_amount": 0,
          "labor_hours": 1.5,
          "repair_action": "remplacement",
          "subtotal": 3500,
          "notes": "Inclut support et absorbeur — réf 620220007R"
        },
        {
          "id": "li-0003",
          "estimate_id": "est-0001-aaaa",
          "item_name": "Phare avant droit LED",
          "item_type": "piece",
          "part_type": "Neuf",
          "quantity": 1,
          "unit_price": 3800,
          "original_price": 3800,
          "depreciation_rate": 0,
          "depreciation_amount": 0,
          "labor_hours": 0.75,
          "repair_action": "remplacement",
          "subtotal": 3800,
          "notes": "Réf 260103477R"
        },
        {
          "id": "li-0004",
          "estimate_id": "est-0001-aaaa",
          "item_name": "Calandre avant",
          "item_type": "piece",
          "part_type": "Neuf",
          "quantity": 1,
          "unit_price": 1200,
          "original_price": 1200,
          "depreciation_rate": 0,
          "depreciation_amount": 0,
          "labor_hours": 0.5,
          "repair_action": "remplacement",
          "subtotal": 1200,
          "notes": "Réf 623100001R"
        }
      ],
      "lignes_mo": [
        {
          "id": "mo-0001",
          "estimate_id": "est-0001-aaaa",
          "operation_type": "tolerie",
          "hours": 8.0,
          "hourly_rate": 200,
          "subtotal": 1600,
          "labor_type_id": "lt-tolerie"
        },
        {
          "id": "mo-0002",
          "estimate_id": "est-0001-aaaa",
          "operation_type": "mecanique",
          "hours": 2.0,
          "hourly_rate": 200,
          "subtotal": 400,
          "labor_type_id": "lt-mecanique"
        },
        {
          "id": "mo-0003",
          "estimate_id": "est-0001-aaaa",
          "operation_type": "peinture",
          "hours": 11.0,
          "hourly_rate": 200,
          "subtotal": 2200,
          "labor_type_id": "lt-peinture"
        }
      ]
    }
  ],

  "rapports_generes": [
    {
      "id": "rpt-0001-aaaa",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "report_type": "rapport_preliminaire",
      "file_url": "7e2c9f4a-5678-4def-b001-112233445566/rapport_preliminaire_20260814.pdf",
      "created_at": "2026-08-14T14:10:00.000Z",
      "created_by": "exp-uuid-0001-expert-karim",
      "file": {
        "bucket": "damage-photos",
        "url": "https://xyzabc.supabase.co/storage/v1/object/sign/damage-photos/7e2c9f4a/rapport_preliminaire_20260814.pdf?token=eyJhbGci...",
        "public": false
      }
    }
  ],

  "signatures": [
    {
      "id": "sig-0001-aaaa",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "signer_type": "expert",
      "signer_name": "Karim BENSOUDA",
      "signed_by": "exp-uuid-0001-expert-karim",
      "signed_at": "2026-08-14T14:05:00.000Z",
      "signature_url": "7e2c9f4a-5678-4def-b001-112233445566/signature_expert_karim.png",
      "created_at": "2026-08-14T14:05:00.000Z",
      "file": {
        "bucket": "damage-photos",
        "url": "https://xyzabc.supabase.co/storage/v1/object/public/damage-photos/7e2c9f4a/signature_expert_karim.png",
        "public": true
      }
    }
  ],

  "suivi_evenements": [
    {
      "id": "evt-0001",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "kpi_status": "pending_quote",
      "step_label": "Dossier ouvert",
      "message_fr": "Dossier créé par Fatima Zahrae. En attente de réception du devis.",
      "created_at": "2026-08-14T08:15:22.000Z",
      "created_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011"
    },
    {
      "id": "evt-0002",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "kpi_status": "devis_recu",
      "step_label": "Devis reçu",
      "message_fr": "Devis reçu et enregistré par Fatima Zahrae. En cours d'analyse.",
      "created_at": "2026-08-14T10:05:00.000Z",
      "created_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011"
    },
    {
      "id": "evt-0003",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "kpi_status": "chiffrage_en_cours",
      "step_label": "Chiffrage en cours",
      "message_fr": "Fatima Zahrae a transmis le devis au chiffreur pour vérification.",
      "created_at": "2026-08-14T10:30:00.000Z",
      "created_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011"
    },
    {
      "id": "evt-0004",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "kpi_status": "quote_validated",
      "step_label": "Devis validé",
      "message_fr": "Fatima Zahrae a validé le montant du devis de réparation.",
      "created_at": "2026-08-14T13:30:00.000Z",
      "created_by": "a3f8c2d1-1234-4abc-9000-aabbccdd0011"
    }
  ],

  "notifications": [
    {
      "id": "notif-0001",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "user_id": "a3f8c2d1-1234-4abc-9000-aabbccdd0011",
      "notification_type": "whatsapp_tracking",
      "title": "✅ WhatsApp — RMA14-08-26.WEX047",
      "message": "Envoyer à Mohamed ALAOUI : « Dossier sinistre ouvert »",
      "read": true,
      "metadata": {
        "whatsapp_url": "https://wa.me/212661234567?text=%E2%9C%85%20*Dossier%20sinistre%20ouvert*%0A%0ABonjour%20Mohamed%20ALAOUI...",
        "whatsapp_phone": "212661234567",
        "step": "Dossier sinistre ouvert",
        "insured_name": "Mohamed ALAOUI",
        "insurer": "RMA"
      },
      "created_at": "2026-08-14T08:15:25.000Z"
    },
    {
      "id": "notif-0002",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "user_id": "exp-uuid-0001-expert-karim",
      "notification_type": "mission_assignment",
      "title": "🔔 Nouvelle mission — RMA14-08-26.WEX047",
      "message": "Vous avez été assigné à la mission RENAULT DUSTER / ALAOUI Mohamed",
      "read": true,
      "metadata": {
        "mission_id": "mission-0001-aaaa",
        "vehicle": "RENAULT DUSTER",
        "insured": "ALAOUI Mohamed"
      },
      "created_at": "2026-08-14T09:00:05.000Z"
    }
  ],

  "messagerie": {
    "messages": [
      {
        "id": "msg-0001",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "mailbox_account_id": "mailbox-cabinet-001",
        "subject": "Devis réparation RENAULT DUSTER 12345-A-7",
        "sender_email": "devis@autotech-casa.ma",
        "sender_name": "AutoTech Casablanca",
        "body_text": "Veuillez trouver ci-joint notre devis. Total HT: 16 900 DH / TTC: 20 280 DH.",
        "direction": "inbound",
        "gmail_message_id": "msg_gmail_abc123",
        "gmail_thread_id": "thread_gmail_xyz789",
        "received_at": "2026-08-14T09:55:00.000Z",
        "attachments": [
          {
            "id": "att-email-0001",
            "message_id": "msg-0001",
            "filename": "devis_autotech_20260814.pdf",
            "size_bytes": 248000,
            "file": {
              "bucket": "mail-attachments",
              "url": "https://xyzabc.supabase.co/storage/v1/object/sign/mail-attachments/msg-0001/devis.pdf?token=eyJhbGci...",
              "public": false
            }
          }
        ]
      }
    ],
    "triage_log": [
      {
        "id": "triage-0001",
        "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
        "subject": "Devis réparation RENAULT DUSTER 12345-A-7",
        "sender_email": "devis@autotech-casa.ma",
        "action_taken": "linked_claim",
        "confidence_score": 0.93,
        "matched_claim_number": "RMA14-08-26.WEX047",
        "created_at": "2026-08-14T09:55:10.000Z"
      }
    ]
  },

  "automations_email": [
    {
      "id": "auto-0001",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "email_type": "devis_repairer",
      "subject": "Devis réparation RENAULT DUSTER 12345-A-7",
      "sender_email": "devis@autotech-casa.ma",
      "sender_name": "AutoTech Casablanca",
      "status": "processed",
      "action_taken": "linked_to_claim",
      "gmail_message_id": "msg_gmail_abc123",
      "gmail_thread_id": "thread_gmail_xyz789",
      "attachments": {"count": 1, "filenames": ["devis_autotech_20260814.pdf"]},
      "raw_data": {"snippet": "Veuillez trouver ci-joint notre devis..."},
      "security_flags": {"spam_score": 0.01, "verified_sender": true},
      "error_message": null,
      "received_at": "2026-08-14T09:55:00.000Z",
      "processed_at": "2026-08-14T09:55:10.000Z",
      "created_at": "2026-08-14T09:55:00.000Z"
    }
  ],

  "apprentissage_expert": [
    {
      "id": "learn-0001",
      "claim_id": "7e2c9f4a-5678-4def-b001-112233445566",
      "expert_id": "exp-uuid-0001-expert-karim",
      "part_name": "Aile avant droite",
      "part_type": "Neuf",
      "original_price": 4200,
      "depreciation_rate": 0,
      "labor_hours": 3.0,
      "labor_rate": 200,
      "vehicle_age": 7,
      "vehicle_category": "C2",
      "created_at": "2026-08-14T13:00:00.000Z"
    }
  ],

  "config_bureau": {
    "id": "bureau-config-001",
    "nom_bureau": "Cabinet d'Expertise Automobile Al Amal",
    "adresse": "45 Boulevard Zerktouni",
    "ville": "Casablanca",
    "code_postal": "20100",
    "pays": "Maroc",
    "telephone": "05 22 36 89 00",
    "mobile": "06 61 00 11 22",
    "fax": "05 22 36 89 01",
    "email": "contact@cabinet-expert-amal.ma",
    "site_web": "www.cabinet-expert-amal.ma",
    "rc": "RC-CASA-123456",
    "ice": "002345678000001",
    "patente": "PAT-56789",
    "cnss": "CNSS-987654",
    "identifiant_fiscal": "IF-112233",
    "logo_url": "bureau-assets/logo_cabinet.png",
    "signature_url": "bureau-assets/signature_directeur.png",
    "tampon_url": "bureau-assets/tampon_officiel.png",
    "cachet_signature_url": "bureau-assets/cachet_avec_signature.png",
    "couleur_primaire": "#0ea5e9",
    "slogan": "L'expertise au service de la vérité",
    "ssl_cert_url": null,
    "created_at": "2025-01-01T00:00:00.000Z",
    "updated_at": "2026-06-01T10:00:00.000Z"
  },

  "archives_precedentes": [],

  "totaux": {
    "photos": 1,
    "documents": 2,
    "devis": 1,
    "factures": 0,
    "chiffrages": 1,
    "rapports": 1,
    "signatures": 1,
    "messages_email": 1,
    "evenements_suivi": 4,
    "missions": 1
  }
}
```
