"""
mapper.py — WexiaToDossierMapper
=================================
Translates a full Wexia dossier JSON (format: wexia.dossier.full, schema_version 2.0)
into the flat MCMA-ready payload consumed by process_workflow() in main.py.

Usage (standalone test):
    python mapper.py path/to/dossier.json
"""

import os
import uuid
import json
import httpx
from typing import Optional


# ---------------------------------------------------------------------------
# Configurable mappings — edit these to match your MCMA rubrique catalog
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Real MCMA IdRubrique values (confirmed from live HTML — formGED form)
# ---------------------------------------------------------------------------
# Maps Wexia operation_type (from lignes_mo) -> MCMA IdRubrique
LABOR_RUBRIQUE_MAP: dict = {
    "tolerie":       "7",    # MAIN D'OEUVRE CARROSSERIE
    "carrosserie":   "7",    # MAIN D'OEUVRE CARROSSERIE (alias)
    "mecanique":     "8",    # MAIN D'OEUVRE MECANIQUE
    "peinture":      "12",   # MAIN D'OEUVRE PEINTURE
    "electricite":   "28",   # MAIN D'OEUVRE ELECTRIQUE
    "ingredients":   "16",   # PEINTURES ET INGREDIENTS
    "marbre":        "17",   # PASSAGE AU MARBRE
}

# Full MCMA IdRubrique catalog:
#  1=FOURNITURES CARROSSERIE (ORIGINES)      2=CARROSSERIE (ADAPTABLES)   3=CARROSSERIE (RECUPERABLES)
#  4=FOURNITURES MECANIQUE (ORIGINES)        5=MECANIQUE (ADAPTABLES)     6=MECANIQUE (RECUPERABLES)
#  7=MO CARROSSERIE  8=MO MECANIQUE  9=MONTANT TOTAL  10=PEINTURE (ORIGINES)
# 11=PEINTURE (ADAPTABLES)  12=MO PEINTURE  13=ELECTRIQUE (D'ORIGINE)  14=ELECTRIQUE (ADAPTABLES)
# 15=ELECTRIQUE (RECUPERABLES)  16=PEINTURES ET INGREDIENTS  17=PASSAGE AU MARBRE
# 18=PARALLELISME ET EQUILIBRAGE  19=REP VITRE  20=REMPL VITRE  21=REP PARE-BRISE
# 22=REMPL PARE-BRISE  23=REP LUNETTE ARRIERE  24=REMPL LUNETTE ARRIERE
# 25=COLLE  26=KIT COLLE PB ET LA  27=KIT COLLE VITRE  28=MO ELECTRIQUE

# Maps Wexia part_type (from lignes_pieces) -> MCMA rubrique ID for spare parts
PIECE_TYPE_RUBRIQUE_MAP: dict = {
    "origine":       "1",    # FOURNITURES CARROSSERIE (ORIGINES)
    "adaptable":     "2",    # CARROSSERIE (ADAPTABLES)
    "recuperation":  "3",    # CARROSSERIE (RECUPERABLES)
}
DEFAULT_PIECE_RUBRIQUE_ID = "1"   # fallback if part_type not recognized

# ---------------------------------------------------------------------------
# Real MCMA IdNatureDocument values (confirmed from live HTML — GED dropdown)
# ---------------------------------------------------------------------------
DOCUMENT_NATURE_MAP: dict = {
    # Expertise reports
    "rapport_preliminaire":        "40",   # RAPPORT D'EXPERTISE PRELIMINAIRE DE REFORME
    "rapport_final":               "41",   # RAPPORT D'EXPERTISE DEFINITIF DE REFORME
    "rapport_expertise":           "39",   # RAPPORT D'EXPERTISE DE REPARATION
    "rapport_appreciation":        "60",   # RAPPORT D'APPRECIATION
    "rapport_valeur_venale":       "61",   # RAPPORT D'ESTIMATION DE LA VALEUR VENALE
    # Photos
    "photo_damage":                "62",   # PHOTOS DE L'ACCIDENT
    "photo_avant_reparation":      "63",   # PHOTOS AVANT LA REPARATION  ← most common
    "photo_apres_reparation":      "64",   # PHOTOS APRES REPARATION
    # Devis / factures
    "devis":                       "56",   # DEVIS DE REPARATION GARAGE
    "devis_valide":                "57",   # DEVIS DE REPARATION VALIDE PAR L'EXPERT
    "devis_client":                "37",   # DEVIS DE REPARATION CLIENT
    "facture":                     "23",   # FACTURE DE REPARATION GARAGE
    "facture_client":              "24",   # FACTURE DE REPARATION CLIENT
    # Vehicle docs
    "carte_grise":                 "6",    # LA CARTE GRISE
    "carte_verte":                 "11",   # LA CARTE VERTE
    "constat":                     "22",   # CONSTAT AMIABLE
    "attestation_assurance":       "7",    # ATTESTATION D'ASSURANCE
    "permis":                      "10",   # PERMIS DE CONDUIRE
    "visite_technique":            "12",   # VISITE TECHNIQUE
    # Other
    "autre":                       "74",   # AUTRE
}

# TVA rate applied to line items that have no explicit tax field
DEFAULT_TVA_RATE = 0.20


# ---------------------------------------------------------------------------
# Mapper class
# ---------------------------------------------------------------------------

class WexiaToDossierMapper:
    """
    Maps a Wexia full-dossier JSON dict to the flat MCMA process_workflow payload.

    Example
    -------
    mapper  = WexiaToDossierMapper()
    payload = mapper.map(wexia_json)
    # payload is ready to pass straight into process_workflow()
    """

    def __init__(self, download_dir: str = "temp"):
        self.download_dir = download_dir
        os.makedirs(download_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def map(self, wexia: dict) -> dict:
        """
        Returns the MCMA-ready flat payload.
        Documents in the result carry a 'url' key.
        Call download_documents() to resolve them to local 'path' keys.
        """
        dossier   = wexia.get("dossier",  {}) or {}
        vehicule  = wexia.get("vehicule", {}) or {}
        assureur  = wexia.get("assureur", {}) or {}
        obs       = wexia.get("observations_expert", {}) or {}
        missions  = wexia.get("missions", []) or []
        chiffrage = self._get_active_chiffrage(wexia)

        # Detect Garage Conventionné (Prise en Charge) Mode vs Mode Normal
        is_garage_conventionne = False
        mission_type_str = str(dossier.get("mission_type", "")).lower()
        incident_desc = str(dossier.get("incident_description", "")).lower()
        repair_mode_str = str(dossier.get("repair_mode", "")).lower()

        if "normal" in mission_type_str or "normal" in incident_desc:
            is_garage_conventionne = False
        elif mission_type_str in ["conventionne", "garage_conventionne", "pec"] or "pec" in incident_desc or "convention" in incident_desc or "convention" in repair_mode_str:
            is_garage_conventionne = True
        elif missions and any(m.get("mission_type") in ["pec", "conventionne", "garage_conventionne"] for m in missions):
            is_garage_conventionne = True


        # Extract financial values for Devis Validation payload (Garage Conventionné)
        devis_validation = {}
        if chiffrage:
            notes_raw = chiffrage.get("notes", "")
            franchise, vetuste, remise = 0.0, 0.0, 0.0
            if isinstance(notes_raw, str) and notes_raw.startswith("{"):
                try:
                    notes = json.loads(notes_raw)
                    franchise = float(notes.get("franchise", 0) or 0)
                    vetuste = float(notes.get("vetuste", 0) or 0)
                    remise = float(notes.get("remise", 0) or 0)
                except Exception:
                    pass
            
            charge_soc = franchise + vetuste
            total_cost = float(chiffrage.get("total_cost") or chiffrage.get("final_cost") or 0)
            charge_mut = max(0.0, total_cost - charge_soc - remise)

            devis_validation = {
                "MontantTVA": str(chiffrage.get("tax_amount", 0)),
                "MontantVetuste": str(vetuste),
                "MontantFranchise": str(franchise),
                "MontantRemise": str(remise),
                "MontantChargeSocietaire": str(charge_soc),
                "MontantChargeMutuelle": str(charge_mut),
            }

        return {
            # --- Search keys (used to locate the dossier in MCMA) ---
            "dossier_reference": (
                assureur.get("reference_dossier")
                or dossier.get("reference_number")
                or wexia.get("dossier_reference", "")
            ),
            "matricule": (
                vehicule.get("license_plate")
                or dossier.get("license_plate")
                or (vehicule.get("carte_grise_extractions", [{}])[0].get("immatriculation") if vehicule.get("carte_grise_extractions") else None)
                or (assureur.get("attestation_extractions", [{}])[0].get("immatriculation") if assureur.get("attestation_extractions") else None)
                or wexia.get("matricule")
                or wexia.get("immatriculation", "")
            ),

            # --- Mode and Devis Validation ---
            "mode_reparation": "conventionne" if is_garage_conventionne else "normal",
            "devis_validation": devis_validation,

            # --- Main form text fields ---
            "text_fields": self._build_text_fields(dossier, vehicule, chiffrage, obs, wexia),

            # --- Dropdown / select fields ---
            "select_fields": self._build_select_fields(dossier),

            # --- Checkbox states ---
            "checkboxes": self._build_checkboxes(dossier),

            # --- Line items (rubriques) ---
            "rubriques": self._build_rubriques(chiffrage),

            # --- Documents (urls — resolved to paths after download) ---
            "documents": self._build_documents(wexia),
        }


    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _get_active_chiffrage(self, wexia: dict) -> dict:
        """
        Returns the best chiffrage for MCMA filling.
        Priority: approved chiffrage with the most line items (lignes_pieces + lignes_mo).
        Falls back to is_final, then first approved, then first overall.
        """
        chiffrages = wexia.get("chiffrages") or []
        if not chiffrages:
            return {}

        def _score(c):
            items = len(c.get("lignes_pieces", [])) + len(c.get("lignes_mo", []))
            is_approved = 1 if c.get("status") == "approved" else 0
            is_final = 1 if c.get("is_final") else 0
            cost = float(c.get("total_cost", 0) or 0)
            # Primary: most line items, then approved, then highest cost, then is_final
            return (items, is_approved, cost, is_final)

        return max(chiffrages, key=_score)

    def _build_text_fields(
        self,
        dossier: dict,
        vehicule: dict,
        chiffrage: dict,
        obs: dict,
        wexia: dict,
    ) -> dict:
        fields: dict = {}

        # Kilometrage
        km = vehicule.get("mileage_km") or dossier.get("mileage_km")
        if km is not None:
            fields["Kilometrage"] = str(int(km))

        # Valeur venale (market value)
        vv = vehicule.get("market_value") or dossier.get("market_value")
        if vv is not None:
            fields["ValeurVenale"] = str(int(vv))
            fields["ValeurVenaleEstime"] = str(int(vv))  # Fill both variants

        # Financial amounts from the active chiffrage
        if chiffrage:
            ht   = chiffrage.get("total_cost")
            tva  = chiffrage.get("tax_amount")
            ttc  = chiffrage.get("final_cost") or chiffrage.get("indemnification_amount")
            days = chiffrage.get("estimated_days")
            sv   = chiffrage.get("salvage_value") or vehicule.get("salvage_value") or dossier.get("salvage_value")

            if ht   is not None: fields["MontantReparation"]      = str(int(ht))
            if tva  is not None: fields["MontantTVA"]             = str(int(tva))
            if ttc  is not None: fields["MontantTTC"]             = str(int(ttc))
            if days is not None: fields["NbreJourImmobilisation"]  = str(int(days))
            if sv   is not None:
                fields["MontantEpave"]  = str(int(sv))
                fields["ValeurEpave"]   = str(int(sv))

            # Parse chiffrage notes for vetuste, franchise, remise
            notes_raw = chiffrage.get("notes", "")
            if notes_raw:
                try:
                    notes = json.loads(notes_raw)
                    vetuste   = notes.get("vetuste", 0)
                    franchise = notes.get("franchise", 0)
                    remise    = notes.get("remise", 0)
                    if vetuste:   fields["MontantVetusteTotal"]  = str(int(vetuste))
                    if franchise: fields["MontantFranchise"]     = str(int(franchise))
                    if remise:    fields["MontantRemise"]        = str(int(remise))
                except (json.JSONDecodeError, TypeError):
                    pass

        # Date devis (from first devis extracted_data)
        devis_list = wexia.get("devis") or []
        if devis_list:
            date_devis = (devis_list[0].get("extracted_data") or {}).get("date_devis")
            if date_devis:
                fields["DateDevis"] = str(date_devis)

        # Reference Dossier (e.g. MCM14-08-26.WEX002)
        ref_num = dossier.get("reference_number") or dossier.get("claim_number") or dossier.get("num_dossier")
        if ref_num:
            fields["ReferenceDossier"] = str(ref_num)

        # Expert observations (free text)
        obs_text = obs.get("texte") or dossier.get("expert_observations", "")
        if obs_text:
            fields["ObservationMission"] = obs_text

        # Expertise city
        city = dossier.get("expertise_city", "")
        if city:
            fields["LieuExpertise"] = city

        return fields

    def _build_select_fields(self, dossier: dict) -> dict:
        fields: dict = {}

        # Taux de responsabilite (e.g. "100", "50")
        rate = dossier.get("responsibility_rate")
        if rate is not None:
            fields["PartResponsabilite"] = str(int(rate))

        # Type reforme (e.g. "E" = Economique, "T" = Technique)
        reform_type = dossier.get("reform_type")
        if reform_type:
            fields["TypeReforme"] = str(reform_type)

        return fields

    def _build_checkboxes(self, dossier: dict) -> dict:
        boxes: dict = {}

        # In MCMA, "Véhicule Réparable" (#VehRepareI) reveals the "Rapport de la réparation" and rubriques table.
        # For all normal repair claims (non-reform), this MUST be True.
        is_reform = bool(dossier.get("is_reform"))
        boxes["VehRepareI"] = not is_reform

        # Reform flag (real MCMA id = VehReformeI)
        if is_reform:
            boxes["VehReformeI"] = True

        # TVA récupérable (sociétés can recover TVA)
        insured_type = dossier.get("insured_type", "")
        if insured_type in ("societe", "société", "company", "entreprise"):
            boxes["TvaRecupI"] = True

        return boxes

    def _build_rubriques(self, chiffrage: dict) -> list:
        """
        Builds aggregated MCMA rubrique line items grouped by category:
          1. Total Pièces Occasions / Récupérables (IdRubrique=3) or Origines (IdRubrique=1)
          2. M.O Tôlerie / Carrosserie (IdRubrique=7)
          3. M.O Peinture (IdRubrique=12)
          4. Peintures et Ingrédients (IdRubrique=16)
          5. M.O Mécanique (IdRubrique=8) / Electrique (IdRubrique=28)
        """
        if not chiffrage:
            return []

        # Dictionary to aggregate amounts by IdRubrique: { rubrique_id: { "amount_ht": float, "label": str } }
        aggregated = {}

        # Rubrique human labels
        RUBRIQUE_LABELS = {
            "1": "FOURNITURES CARROSSERIE (ORIGINES)",
            "2": "FOURNITURES CARROSSERIE (ADAPTABLES)",
            "3": "TOTAL PIECES OCCASIONS / RECUPERABLES",
            "4": "FOURNITURES MECANIQUE (ORIGINES)",
            "5": "FOURNITURES MECANIQUE (ADAPTABLES)",
            "6": "FOURNITURES MECANIQUE (RECUPERABLES)",
            "7": "M.O TOLERIE / CARROSSERIE",
            "8": "M.O MECANIQUE",
            "12": "M.O PEINTURE",
            "16": "PEINTURES ET INGREDIENTS",
            "17": "PASSAGE AU MARBRE",
            "28": "M.O ELECTRIQUE",
        }

        def _add_to_rubrique(rub_id: str, amount: float, default_label: str = ""):
            if amount <= 0:
                return
            if rub_id not in aggregated:
                aggregated[rub_id] = {
                    "IdRubrique": rub_id,
                    "amount_ht": 0.0,
                    "_label": RUBRIQUE_LABELS.get(rub_id, default_label or f"Rubrique #{rub_id}")
                }
            aggregated[rub_id]["amount_ht"] += amount

        # Process lignes_pieces (contains parts and/or labor lines)
        for line in chiffrage.get("lignes_pieces") or []:
            amount_ht = float(line.get("subtotal") or line.get("unit_price") or 0)
            if amount_ht <= 0:
                continue

            item_type = (line.get("item_type") or "part").lower()
            item_name_lower = (line.get("item_name") or "").lower()

            if item_type == "labor":
                op_type = (line.get("notes") or "").lower().strip()
                if "peinture" in item_name_lower and ("ingr" in item_name_lower or "ingrédient" in item_name_lower):
                    rub_id = "16"
                elif op_type in LABOR_RUBRIQUE_MAP:
                    rub_id = LABOR_RUBRIQUE_MAP[op_type]
                elif "peinture" in item_name_lower:
                    rub_id = "12"
                elif "tolerie" in item_name_lower or "tôlerie" in item_name_lower or "carrosserie" in item_name_lower:
                    rub_id = "7"
                elif "mecanique" in item_name_lower or "mécanique" in item_name_lower:
                    rub_id = "8"
                else:
                    rub_id = LABOR_RUBRIQUE_MAP.get(op_type, "7")

                _add_to_rubrique(rub_id, amount_ht, line.get("item_name", ""))
            else:
                # Spare part
                part_type = (line.get("part_type") or "").lower().strip()
                rub_id = PIECE_TYPE_RUBRIQUE_MAP.get(part_type, DEFAULT_PIECE_RUBRIQUE_ID)
                _add_to_rubrique(rub_id, amount_ht, "TOTAL PIECES OCCASIONS / RECUPERABLES")

        # Process legacy lignes_mo if present
        for mo in chiffrage.get("lignes_mo") or []:
            amount_ht = float(mo.get("subtotal") or 0)
            if amount_ht <= 0:
                continue
            op_type = (mo.get("operation_type") or "").lower().strip()
            rub_id = LABOR_RUBRIQUE_MAP.get(op_type, "7")
            _add_to_rubrique(rub_id, amount_ht, mo.get("operation_type", ""))

        # Format into final MCMA list with rounded HT and Taxe
        rubriques = []
        for rub_id, item in aggregated.items():
            tot_ht = item["amount_ht"]
            tva = round(tot_ht * DEFAULT_TVA_RATE)
            rubriques.append({
                "IdRubrique": rub_id,
                "MontantHT": str(int(round(tot_ht))),
                "Taxe": str(tva),
                "_label": item["_label"]
            })

        return rubriques

    def _build_documents(self, wexia: dict) -> list:
        """
        Collects all uploadable document URLs from the Wexia JSON.
        Returns dicts with keys: url, id_nature, label.
        Call download_documents() to download them to local temp files.
        """
        docs = []

        def _add(url: Optional[str], nature_key: str, label: str):
            if not url or url.strip().endswith("..."):
                return   # skip missing or truncated placeholder URLs
            docs.append({
                "url":       url,
                "id_nature": DOCUMENT_NATURE_MAP.get(nature_key, "63"),
                "label":     label,
            })

        # Validated devis (quote PDFs)
        for devis in wexia.get("devis") or []:
            if devis.get("status") in ("validated", "approved", None):
                url = (devis.get("file") or {}).get("url")
                _add(url, "devis", f"Devis — {devis.get('repairer_name', '')}")

        # Generated expert reports
        for rpt in wexia.get("rapports_generes") or []:
            rpt_type   = rpt.get("report_type", "")
            nature_key = "rapport_final" if "final" in rpt_type else "rapport_preliminaire"
            url        = (rpt.get("file") or {}).get("url")
            _add(url, nature_key, rpt_type)

        # Carte grise and other scanned docs
        for doc in (wexia.get("documents") or {}).get("cartes_grises_et_autres") or []:
            doc_type = doc.get("document_type", "")
            if doc_type in DOCUMENT_NATURE_MAP:
                url = (doc.get("file") or {}).get("url")
                _add(url, doc_type, doc_type)

        # Invoices (factures)
        for fac in wexia.get("factures") or []:
            url = (fac.get("file") or {}).get("url")
            _add(url, "facture", f"Facture — {fac.get('repairer_name', '')}")

        return docs

    # ------------------------------------------------------------------
    # Document downloader
    # ------------------------------------------------------------------

    async def download_documents(self, documents: list) -> list:
        """
        Downloads each document from its signed URL to a local temp file.
        Returns a new list with 'path' key set — ready for process_workflow().
        Documents whose URL fails are skipped with a warning.
        """
        downloaded = []
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            for doc in documents:
                url = doc.get("url", "")
                if not url:
                    continue
                try:
                    print(f"[Doc] Downloading: {doc.get('label', url)}")
                    resp = await client.get(url)
                    resp.raise_for_status()

                    local_path = os.path.join(self.download_dir, f"{uuid.uuid4()}.pdf")
                    with open(local_path, "wb") as fh:
                        fh.write(resp.content)

                    size_kb = os.path.getsize(local_path) / 1024
                    print(f"[Doc]   Saved -> {local_path} ({size_kb:.1f} KB)")

                    downloaded.append({
                        "path":      local_path,
                        "id_nature": doc["id_nature"],
                        "label":     doc.get("label", ""),
                    })
                except Exception as exc:
                    print(f"[Doc] WARNING — failed to download '{doc.get('label')}': {exc}")

        return downloaded


# ---------------------------------------------------------------------------
# CLI test runner: python mapper.py path/to/dossier.json
# ---------------------------------------------------------------------------

def _pretty_print_payload(payload: dict):
    print("\n" + "=" * 62)
    print("  MCMA PAYLOAD SUMMARY")
    print("=" * 62)
    print(f"  Dossier reference : {payload['dossier_reference']}")
    print(f"  Matricule         : {payload['matricule']}")
    print(f"\n  Text fields ({len(payload['text_fields'])})")
    for k, v in payload["text_fields"].items():
        display_v = v[:80] + "..." if len(str(v)) > 80 else v
        print(f"      {k:<30} = {display_v}")
    print(f"\n  Select fields ({len(payload['select_fields'])})")
    for k, v in payload["select_fields"].items():
        print(f"      {k:<30} = {v}")
    print(f"\n  Checkboxes ({len(payload['checkboxes'])})")
    for k, v in payload["checkboxes"].items():
        print(f"      {k:<30} = {v}")
    print(f"\n  Rubriques ({len(payload['rubriques'])})")
    for r in payload["rubriques"]:
        print(f"      [Id={r['IdRubrique']}] HT={r['MontantHT']}  TVA={r['Taxe']}  ({r.get('_label','')})")
    print(f"\n  Documents ({len(payload['documents'])})")
    for d in payload["documents"]:
        print(f"      [nature={d['id_nature']}] {d['label']}")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python mapper.py <path_to_wexia_dossier.json>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        raw_text = fh.read().strip()
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_text = "\n".join(lines)
        wexia_data = json.loads(raw_text)

    mapper  = WexiaToDossierMapper()
    payload = mapper.map(wexia_data)
    _pretty_print_payload(payload)
