"""
mapper.py — WexiaToDossierMapper
=================================
Translates a full Wexia dossier JSON (format: wexia.dossier.full, schema_version 2.0)
into the deterministic, validated MCMA payload contract.

Usage:
    from mapper import WexiaToDossierMapper
    mapper = WexiaToDossierMapper()
    payload = mapper.map(wexia_data)
"""

import os
import re
import json
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, List, Tuple


# ---------------------------------------------------------------------------
# Complete MCMA Rubrique Catalog
# ---------------------------------------------------------------------------
RUBRIQUE_CATALOG: Dict[str, str] = {
    "1":  "FOURNITURES CARROSSERIE (ORIGINES)",
    "2":  "FOURNITURES CARROSSERIE (ADAPTABLES)",
    "3":  "TOTAL PIECES OCCASIONS / RECUPERABLES",
    "4":  "FOURNITURES MECANIQUE (ORIGINES)",
    "5":  "FOURNITURES MECANIQUE (ADAPTABLES)",
    "6":  "FOURNITURES MECANIQUE (RECUPERABLES)",
    "7":  "MAIN D'OEUVRE CARROSSERIE",
    "8":  "MAIN D'OEUVRE MECANIQUE",
    "9":  "MONTANT TOTAL",
    "10": "PEINTURE (ORIGINES)",
    "11": "PEINTURE (ADAPTABLES)",
    "12": "MAIN D'OEUVRE PEINTURE",
    "13": "ELECTRIQUE (D'ORIGINE)",
    "14": "ELECTRIQUE (ADAPTABLES)",
    "15": "ELECTRIQUE (RECUPERABLES)",
    "16": "PEINTURES ET INGREDIENTS",
    "17": "PASSAGE AU MARBRE",
    "18": "PARALLELISME ET EQUILIBRAGE",
    "19": "REPARATION VITRE",
    "20": "REMPLACEMENT VITRE",
    "21": "REPARATION PARE-BRISE",
    "22": "REMPLACEMENT PARE-BRISE",
    "23": "REPARATION LUNETTE ARRIERE",
    "24": "REMPLACEMENT LUNETTE ARRIERE",
    "25": "COLLE",
    "26": "KIT COLLE PARE-BRISE ET LUNETTE ARRIERE",
    "27": "KIT COLLE VITRE",
    "28": "MAIN D'OEUVRE ELECTRIQUE",
}

# Part origin aliases
PART_ORIGIN_ORIGINAL = {"original", "origine", "oem", "neuf", "neuve", "new"}
PART_ORIGIN_ADAPTABLE = {"adaptable", "equivalent", "aftermarket"}
PART_ORIGIN_RECOVERED = {"recuperation", "recuperable", "occasion", "used"}

# System families to MCMA rubrique ID mapping: (system, origin_type) -> rubrique_id
SYSTEM_RUBRIQUE_MATRIX: Dict[Tuple[str, str], str] = {
    ("carrosserie", "original"):    "1",
    ("carrosserie", "adaptable"):   "2",
    ("carrosserie", "recovered"):   "3",
    ("mecanique",   "original"):    "4",
    ("mecanique",   "adaptable"):   "5",
    ("mecanique",   "recovered"):   "6",
    ("peinture",    "original"):    "10",
    ("peinture",    "adaptable"):   "11",
    ("peinture",    "recovered"):   "16",
    ("electrique",  "original"):    "13",
    ("electrique",  "adaptable"):   "14",
    ("electrique",  "recovered"):   "15",
}

DEFAULT_TVA_RATE = Decimal("0.20")
CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------
def normalize_text(text: Optional[str]) -> str:
    """Normalizes text by removing accents, punctuation, and extra whitespace."""
    if not text:
        return ""
    # Normalize unicode characters (remove accents)
    nfkd = unicodedata.normalize('NFKD', str(text))
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Convert to lowercase and strip special chars
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", ascii_text).lower()
    return " ".join(cleaned.split())

def normalize_registration(reg: Optional[str]) -> str:
    """Normalizes vehicle registration for strict equality checks."""
    if not reg:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(reg))
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return re.sub(r"[^a-zA-Z0-9]", "", ascii_text).upper()

def extract_search_matricule_num(reg: Optional[str]) -> str:
    """Extracts first numeric group from registration (e.g. '36165-B-50' -> '36165')."""
    if not reg:
        return ""
    m = re.search(r"\d+", str(reg))
    return m.group(0) if m else ""

def to_decimal(val: Any) -> Decimal:
    """Safely converts input value to Decimal."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0.00")

def quantize_money(val: Decimal) -> Decimal:
    """Rounds to 2 decimal places using standard ROUND_HALF_UP."""
    return val.quantize(CENT, rounding=ROUND_HALF_UP)

def format_money(val: Any) -> str:
    """Formats Decimal value to 2 decimal string (e.g. '10749.99')."""
    dec = to_decimal(val)
    return f"{quantize_money(dec):.2f}"

def format_date_dmy(date_str: Optional[str]) -> Optional[str]:
    """Formats ISO date string (YYYY-MM-DD) into MCMA format DD/MM/YYYY."""
    if not date_str or not isinstance(date_str, str):
        return None
    cleaned = date_str.split("T")[0].strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", cleaned)
    if m:
        year, month, day = m.groups()
        return f"{int(day):02d}/{int(month):02d}/{year}"
    # If already in DD/MM/YYYY or DD-MM-YYYY
    m2 = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})", cleaned)
    if m2:
        day, month, year = m2.groups()
        return f"{int(day):02d}/{int(month):02d}/{year}"
    return None

def extract_year(date_str: Optional[str]) -> Optional[int]:
    """Extracts 4-digit year from date string."""
    if not date_str:
        return None
    m = re.search(r"\b(20\d{2}|19\d{2})\b", str(date_str))
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# WexiaToDossierMapper Class
# ---------------------------------------------------------------------------
class WexiaToDossierMapper:
    """
    Deterministic, zero-LLM mapper translating Wexia full dossier JSON to MCMA payload contract.
    """

    def __init__(self, download_dir: str = "temp"):
        # GED is disabled; download_dir kept for signature compatibility
        self.download_dir = download_dir

    def map(self, wexia: dict, explicit_chiffrage_id: Optional[str] = None) -> dict:
        """
        Maps Wexia dossier JSON to the standard MCMA contract.
        """
        warnings: List[str] = []
        mapping_status: str = "ready"

        dossier   = wexia.get("dossier", {}) or {}
        vehicule  = wexia.get("vehicule", {}) or {}
        assureur  = wexia.get("assureur", {}) or {}
        obs       = wexia.get("observations_expert", {}) or {}
        missions  = wexia.get("missions", []) or []
        devis_list = wexia.get("devis", []) or []

        # -------------------------------------------------------------------
        # 1. Authoritative Registration Mapping
        # -------------------------------------------------------------------
        authoritative_plate = (
            vehicule.get("license_plate")
            or dossier.get("license_plate")
            or (assureur.get("attestation_extractions", [{}])[0].get("immatriculation") if assureur.get("attestation_extractions") else None)
            or (vehicule.get("carte_grise_extractions", [{}])[0].get("immatriculation") if vehicule.get("carte_grise_extractions") else None)
            or wexia.get("matricule")
            or wexia.get("immatriculation", "")
        )
        matricule = str(authoritative_plate).strip()
        search_matricule = extract_search_matricule_num(matricule)

        # Check for conflicts against registrations extracted from devis
        norm_auth = normalize_registration(matricule)
        for devis in devis_list:
            ext_data = devis.get("extracted_data") or {}
            devis_plate = ext_data.get("immatriculation") or devis.get("immatriculation")
            if devis_plate:
                norm_devis = normalize_registration(devis_plate)
                if norm_devis and norm_devis != norm_auth:
                    warnings.append(
                        f"Devis registration {devis_plate} conflicts with authoritative registration {matricule}."
                    )
                    mapping_status = "needs_review"

        # Reference Dossier
        dossier_reference = (
            assureur.get("reference_dossier")
            or dossier.get("reference_number")
            or dossier.get("claim_number")
            or wexia.get("dossier_reference", "")
        )

        # -------------------------------------------------------------------
        # 2. Mission Mode Detection
        # -------------------------------------------------------------------
        if dossier.get("is_reform") is True:
            raise ValueError("Reform dossiers are disabled for automation (is_reform=True).")

        mode_reparation = self._detect_mission_mode(dossier, missions)

        # -------------------------------------------------------------------
        # 3. Chiffrage Selection
        # -------------------------------------------------------------------
        selected_chiffrage = self._select_chiffrage(wexia, explicit_chiffrage_id)
        selected_chiffrage_id = selected_chiffrage.get("id", "")

        # -------------------------------------------------------------------
        # 4. Rubriques Aggregation & Financial Precision
        # -------------------------------------------------------------------
        rubriques = self._build_rubriques(selected_chiffrage)

        # Check for 1-cent devis discrepancy warning
        if devis_list:
            ext_ttc = (devis_list[0].get("extracted_data") or {}).get("total_ttc") or devis_list[0].get("total_ttc")
            if ext_ttc is not None and selected_chiffrage:
                chif_ttc = to_decimal(selected_chiffrage.get("final_cost") or selected_chiffrage.get("total_cost"))
                dev_ttc = to_decimal(ext_ttc)
                diff = abs(dev_ttc - chif_ttc)
                if CENT <= diff <= Decimal("0.05"):
                    warnings.append(
                        f"Devis extracted TTC {format_money(dev_ttc)} differs from approved chiffrage TTC {format_money(chif_ttc)} by {diff}."
                    )

        # -------------------------------------------------------------------
        # 5. Main-Form Text Fields & Date Validation
        # -------------------------------------------------------------------
        text_fields, date_warnings, date_review = self._build_text_fields(
            dossier, vehicule, selected_chiffrage, obs, wexia
        )
        warnings.extend(date_warnings)
        if date_review:
            mapping_status = "needs_review"

        # Check estimated days
        days = selected_chiffrage.get("estimated_days") if selected_chiffrage else dossier.get("estimated_days")
        if days is None or int(days or 0) == 0:
            warnings.append("estimated_days is zero and needs confirmation.")

        # -------------------------------------------------------------------
        # 6. Select Fields and Checkboxes
        # -------------------------------------------------------------------
        select_fields = self._build_select_fields(dossier, assureur)
        checkboxes, cb_warnings, cb_review = self._build_checkboxes(dossier)
        warnings.extend(cb_warnings)
        if cb_review:
            mapping_status = "needs_review"

        return {
            "dossier_reference": str(dossier_reference),
            "matricule": matricule,
            "search_matricule": search_matricule,
            "mode_reparation": mode_reparation,
            "selected_chiffrage_id": selected_chiffrage_id,
            "text_fields": text_fields,
            "select_fields": select_fields,
            "checkboxes": checkboxes,
            "rubriques": rubriques,
            "documents": [],  # GED remains disabled
            "warnings": warnings,
            "mapping_status": mapping_status,
        }

    # -----------------------------------------------------------------------
    # Internal: Mode Detection
    # -----------------------------------------------------------------------
    def _detect_mission_mode(self, dossier: dict, missions: list) -> str:
        m_type = str(dossier.get("mission_type") or "").strip().lower()
        r_mode = str(dossier.get("repair_mode") or "").strip().lower()
        inc_desc = str(dossier.get("incident_description") or "").strip().lower()

        is_explicit_normal = any("normal" in s for s in (m_type, r_mode, inc_desc))
        is_explicit_conv = any(
            any(k in s for k in ("conventionne", "garage_conventionne", "garage conventionne", "pec"))
            for s in (m_type, r_mode, inc_desc)
        )

        if is_explicit_normal and is_explicit_conv:
            raise ValueError(f"Ambiguity error: dossier has conflicting explicit mode fields ({m_type}, {r_mode}, {inc_desc}).")

        if is_explicit_normal:
            return "normal"
        if is_explicit_conv:
            return "conventionne"

        # Fallback to missions list
        if missions:
            for m in missions:
                mt = str(m.get("mission_type") or "").lower()
                if "normal" in mt:
                    return "normal"
                if any(k in mt for k in ("conventionne", "pec", "garage_conventionne")):
                    return "conventionne"

        return "normal"

    # -----------------------------------------------------------------------
    # Internal: Chiffrage Selection
    # -----------------------------------------------------------------------
    def _select_chiffrage(self, wexia: dict, explicit_id: Optional[str] = None) -> dict:
        chiffrages = wexia.get("chiffrages") or []
        if not chiffrages:
            return {}

        # 1. Explicit ID
        if explicit_id:
            for c in chiffrages:
                if str(c.get("id")) == str(explicit_id):
                    return c
            raise ValueError(f"Explicit chiffrage ID '{explicit_id}' not found in dossier chiffrages.")

        # Filter out fee notes and non-repair chiffrages
        repair_chifs = []
        for c in chiffrages:
            scenario = str(c.get("scenario_type") or "").lower()
            if "honoraire" in scenario or "fee" in scenario:
                continue
            has_lines = bool(c.get("lignes_pieces") or c.get("lignes_mo"))
            if not has_lines:
                continue
            repair_chifs.append(c)

        if not repair_chifs:
            return {}

        # Priority 2: Approved detailed repair chiffrage
        approved = [c for c in repair_chifs if str(c.get("status")).lower() == "approved"]
        if approved:
            # If multiple approved, prefer is_final == True
            final_approved = [c for c in approved if c.get("is_final")]
            candidates = final_approved if final_approved else approved
            
            # Check for multiple equally valid with different totals
            distinct_totals = {to_decimal(c.get("total_cost") or c.get("final_cost")) for c in candidates}
            if len(distinct_totals) > 1:
                raise ValueError("Multiple approved chiffrages with different totals found. Explicit selection required.")
            return candidates[0]

        # Priority 4: Other detailed repair chiffrages (only when no approved chiffrage exists)
        return repair_chifs[0]

    # -----------------------------------------------------------------------
    # Internal: Text Fields & Date Validation
    # -----------------------------------------------------------------------
    def _build_text_fields(
        self, dossier: dict, vehicule: dict, chiffrage: dict, obs: dict, wexia: dict
    ) -> Tuple[Dict[str, str], List[str], bool]:
        fields: Dict[str, str] = {}
        warnings: List[str] = []
        needs_review = False

        # ReferenceDossier
        ref_num = dossier.get("reference_number") or dossier.get("claim_number")
        if ref_num:
            fields["ReferenceDossier"] = str(ref_num)

        # DateMECVeh (DD/MM/YYYY)
        first_reg = vehicule.get("first_registration_date") or dossier.get("first_registration_date")
        if first_reg:
            d_mec = format_date_dmy(first_reg)
            if d_mec:
                fields["DateMECVeh"] = d_mec

        # Kilometrage (only when non-null)
        km = vehicule.get("mileage_km") if vehicule.get("mileage_km") is not None else dossier.get("mileage_km")
        if km is not None:
            fields["Kilometrage"] = str(int(km))

        # NbreJourImmobilisation (only when > 0)
        days = chiffrage.get("estimated_days") if chiffrage else dossier.get("estimated_days")
        if days is not None and int(days or 0) > 0:
            fields["NbreJourImmobilisation"] = str(int(days))

        # ValeurVenale & ValeurVenaleEstime
        vv = vehicule.get("market_value") if vehicule.get("market_value") is not None else dossier.get("market_value")
        if vv is not None:
            fields["ValeurVenale"] = str(int(vv))
            fields["ValeurVenaleEstime"] = str(int(vv))

        # MontantEpave
        sv = (
            (chiffrage.get("salvage_value") if chiffrage else None)
            or vehicule.get("salvage_value")
            or dossier.get("salvage_value")
        )
        if sv is not None:
            fields["MontantEpave"] = str(int(sv))

        # MontantReparation (TTC) & MontantTVA
        if chiffrage:
            ttc = chiffrage.get("final_cost") or chiffrage.get("indemnification_amount") or chiffrage.get("total_cost")
            tva = chiffrage.get("tax_amount")
            if ttc is not None:
                fields["MontantReparation"] = format_money(ttc)
            if tva is not None:
                fields["MontantTVA"] = format_money(tva)

        # DateDevis & Chronological Date Conflict Check
        devis_list = wexia.get("devis") or []
        date_devis_raw = None
        if devis_list:
            date_devis_raw = (devis_list[0].get("extracted_data") or {}).get("date_devis") or devis_list[0].get("date_devis")

        devis_year = extract_year(date_devis_raw)
        incident_year = extract_year(dossier.get("incident_date"))
        first_reg_year = extract_year(first_reg)
        ins_start_year = extract_year(dossier.get("insurance_start_date"))

        has_date_conflict = False
        if devis_year and (first_reg_year or ins_start_year):
            cmp_year = first_reg_year or ins_start_year
            if devis_year < (cmp_year - 1) or (incident_year and incident_year < (cmp_year - 1)):
                has_date_conflict = True
                warnings.append(
                    f"Quote/incident dates in {devis_year or incident_year} conflict with first-registration and insurance dates in {cmp_year}."
                )
                needs_review = True

        if date_devis_raw and not has_date_conflict:
            d_devis = format_date_dmy(date_devis_raw)
            if d_devis:
                fields["DateDevis"] = d_devis

        # ObservationMission
        obs_text = obs.get("texte") or dossier.get("expert_observations")
        if obs_text:
            fields["ObservationMission"] = str(obs_text)

        return fields, warnings, needs_review

    # -----------------------------------------------------------------------
    # Internal: Select Fields and Checkboxes
    # -----------------------------------------------------------------------
    def _build_select_fields(self, dossier: dict, assureur: dict) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        rate = dossier.get("responsibility_rate") if dossier.get("responsibility_rate") is not None else assureur.get("responsibility_rate")
        if rate is not None:
            rate_str = str(int(rate))
            if rate_str not in ("0", "50", "100"):
                raise ValueError(f"Invalid PartResponsabilite: '{rate_str}'. Supported values are 0, 50, 100.")
            fields["PartResponsabilite"] = rate_str
        return fields

    def _build_checkboxes(self, dossier: dict) -> Tuple[Dict[str, bool], List[str], bool]:
        boxes: Dict[str, bool] = {
            "VehRepareI": True,
            "VehReformeI": False,
        }
        warnings: List[str] = []
        needs_review = False

        insured_type = str(dossier.get("insured_type") or "").strip().lower()
        if insured_type in ("societe", "société", "company", "entreprise"):
            boxes["TvaRecupI"] = True
        elif insured_type:
            # Unclear recoverable TVA types like location_voiture must not be guessed
            warnings.append(f"Recoverable TVA cannot be inferred safely from insured_type={insured_type}.")
            needs_review = True

        return boxes, warnings, needs_review

    # -----------------------------------------------------------------------
    # Internal: Rubrique Classification and Aggregation
    # -----------------------------------------------------------------------
    def _classify_colle_or_adhesive(self, item_name: str) -> Optional[str]:
        """Checks if item is colle / mastic / kit colle."""
        name_norm = normalize_text(item_name)
        if "colle" in name_norm or "mastic" in name_norm:
            if "kit" in name_norm:
                if "vitre" in name_norm:
                    return "27"  # KIT COLLE VITRE
                return "26"      # KIT COLLE PARE-BRISE ET LUNETTE ARRIERE
            return "25"          # COLLE
        return None

    def _determine_labour_rubrique(self, item_name: str, notes: str, pointer: str) -> str:
        """Determines labour rubrique ID (7, 8, 12, 17, 18, 28)."""
        combined = normalize_text(f"{item_name} {notes}")

        if any(k in combined for k in ("marbre", "passage au marbre")):
            return "17"
        if any(k in combined for k in ("parallelisme", "equilibrage", "geometrie")):
            return "18"
        if any(k in combined for k in ("peinture", "vernis")):
            return "12"
        if any(k in combined for k in ("mecanique", "moteur", "vidange")):
            return "8"
        if any(k in combined for k in ("electrique", "electricite")):
            return "28"
        if any(k in combined for k in ("carrosserie", "tolerie", "montage", "demontage", "debosselage", "redressage", "main d oeuvre", "main d'oeuvre", "mo", "reparation", "pose")):
            return "7"


        raise ValueError(
            f"Unknown labour type for line '{item_name}' (notes: '{notes}') at pointer '{pointer}'. Mapping failed closed."
        )


    def _determine_part_rubrique(self, item_name: str, part_type_raw: str, is_original: bool, system_hint: str, pointer: str) -> str:
        """
        Maps parts into Fournitures Carrosserie (1: Origines, 2: Adaptables, 3: Récupérables)
        or specialized mechanical/electrical families if explicitly indicated.
        """
        colle_rub = self._classify_colle_or_adhesive(item_name)
        if colle_rub:
            return colle_rub

        pt_clean = str(part_type_raw or "").strip().lower()
        if pt_clean in PART_ORIGIN_ORIGINAL or is_original is True:
            origin = "original"
        elif pt_clean in PART_ORIGIN_ADAPTABLE:
            origin = "adaptable"
        elif pt_clean in PART_ORIGIN_RECOVERED:
            origin = "recovered"
        else:
            raise ValueError(
                f"Unknown or missing part_type '{part_type_raw}' for piece '{item_name}' at pointer '{pointer}'. Failed closed."
            )

        hint_norm = normalize_text(system_hint)
        name_norm = normalize_text(item_name)

        if "mecanique" in hint_norm or any(t in name_norm for t in ("moteur", "filtre", "radiateur", "amortisseur", "frein")):
            family = "mecanique"
        elif "electrique" in hint_norm or any(t in name_norm for t in ("batterie", "alternateur", "demarreur", "cablage")):
            family = "electrique"
        elif "peinture" in hint_norm or any(t in name_norm for t in ("peinture", "vernis", "ingredient")):
            family = "peinture"
        else:
            family = "carrosserie"

        rub_id = SYSTEM_RUBRIQUE_MATRIX.get((family, origin), "1" if origin == "original" else ("2" if origin == "adaptable" else "3"))
        return rub_id

    def _build_rubriques(self, chiffrage: dict) -> List[dict]:
        """
        Builds and aggregates line items into exact MCMA rubriques with Decimal precision
        and exact remainder allocation.
        """
        if not chiffrage:
            return []

        # Data structure: { rubrique_id: { "ht": Decimal, "vetuste": Decimal, "sources": [...] } }
        groups: Dict[str, Dict[str, Any]] = {}

        # 1. Process lignes_pieces (parts and integrated labor lines)
        for idx, line in enumerate(chiffrage.get("lignes_pieces") or []):
            pointer = f"/chiffrages/0/lignes_pieces/{idx}"
            unit_price = to_decimal(line.get("subtotal") or line.get("unit_price") or 0)
            if unit_price <= 0:
                continue

            item_type = str(line.get("item_type") or "part").strip().lower()
            item_name = str(line.get("item_name") or "").strip()
            notes = str(line.get("notes") or "").strip()
            vetuste_amt = to_decimal(line.get("depreciation_amount") or 0)

            # Check for explicit rubric ID override
            explicit_rub = str(line.get("mcma_rubric_id") or "").strip()
            if explicit_rub and explicit_rub in RUBRIQUE_CATALOG:
                rub_id = explicit_rub
            elif item_type == "labor":
                rub_id = self._determine_labour_rubrique(item_name, notes, pointer)
            else:
                # Part line
                rub_id = self._determine_part_rubrique(
                    item_name=item_name,
                    part_type_raw=line.get("part_type"),
                    is_original=line.get("is_original"),
                    system_hint=line.get("system") or line.get("category") or "",
                    pointer=pointer
                )

            if rub_id not in groups:
                groups[rub_id] = {
                    "IdRubrique": rub_id,
                    "LibRubrique": RUBRIQUE_CATALOG.get(rub_id, f"Rubrique #{rub_id}"),
                    "ht": Decimal("0.00"),
                    "vetuste": Decimal("0.00"),
                    "source_pointers": [],
                }
            groups[rub_id]["ht"] += unit_price
            groups[rub_id]["vetuste"] += vetuste_amt
            groups[rub_id]["source_pointers"].append(pointer)

        # 2. Process legacy lignes_mo if present
        for idx, mo in enumerate(chiffrage.get("lignes_mo") or []):
            pointer = f"/chiffrages/0/lignes_mo/{idx}"
            subtotal = to_decimal(mo.get("subtotal") or 0)
            if subtotal <= 0:
                continue
            op_type = str(mo.get("operation_type") or "").strip()
            rub_id = self._determine_labour_rubrique(op_type, mo.get("notes", ""), pointer)

            if rub_id not in groups:
                groups[rub_id] = {
                    "IdRubrique": rub_id,
                    "LibRubrique": RUBRIQUE_CATALOG.get(rub_id, f"Rubrique #{rub_id}"),
                    "ht": Decimal("0.00"),
                    "vetuste": Decimal("0.00"),
                    "source_pointers": [],
                }
            groups[rub_id]["ht"] += subtotal
            groups[rub_id]["source_pointers"].append(pointer)


        if not groups:
            return []

        # Target Totals from Chiffrage
        target_ht = quantize_money(to_decimal(chiffrage.get("total_cost")))
        target_tva = quantize_money(to_decimal(chiffrage.get("tax_amount")))
        target_ttc = quantize_money(to_decimal(chiffrage.get("final_cost")))

        rubriques_list = []
        running_ht = Decimal("0.00")
        running_tva = Decimal("0.00")

        group_items = list(groups.values())
        for idx, item in enumerate(group_items):
            is_last = (idx == len(group_items) - 1)
            ht_val = quantize_money(item["ht"])
            running_ht += ht_val

            # TVA Calculation
            if is_last and target_tva > 0:
                # Allocate tax remainder to the final rubrique to ensure exact sum(rubrique TVA) == chiffrage.tax_amount
                tva_val = target_tva - running_tva
            else:
                tva_val = quantize_money(ht_val * DEFAULT_TVA_RATE)
                running_tva += tva_val

            ttc_val = ht_val + tva_val
            vet_val = quantize_money(item["vetuste"])
            taux_vet = quantize_money((vet_val / ht_val * 100)) if ht_val > 0 else Decimal("0.00")

            rubriques_list.append({
                "IdRubrique": item["IdRubrique"],
                "LibRubrique": item["LibRubrique"],
                "MontantHT": format_money(ht_val),
                "Taxe": format_money(tva_val),
                "MontantTTC": format_money(ttc_val),
                "TauxVetuste": format_money(taux_vet),
                "MontantVetuste": format_money(vet_val),
                "source_pointers": item["source_pointers"],
            })

        # Validate totals against chiffrage targets
        total_calc_ht = sum(to_decimal(r["MontantHT"]) for r in rubriques_list)
        total_calc_tva = sum(to_decimal(r["Taxe"]) for r in rubriques_list)
        total_calc_ttc = sum(to_decimal(r["MontantTTC"]) for r in rubriques_list)

        if abs(total_calc_ht - target_ht) > CENT:
            raise ValueError(f"Calculated HT sum {total_calc_ht} differs from chiffrage total_cost {target_ht} by > 0.01.")
        if target_tva > 0 and abs(total_calc_tva - target_tva) > CENT:
            raise ValueError(f"Calculated TVA sum {total_calc_tva} differs from chiffrage tax_amount {target_tva} by > 0.01.")
        if target_ttc > 0 and abs(total_calc_ttc - target_ttc) > CENT:
            raise ValueError(f"Calculated TTC sum {total_calc_ttc} differs from chiffrage final_cost {target_ttc} by > 0.01.")

        return rubriques_list
