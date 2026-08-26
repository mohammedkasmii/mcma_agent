"""
core/constants.py — Domain Constants & Rubrique Catalog
========================================================
Canonical definitions of MCMA rubriques, synonym matrices, and origin mappings.
"""

from decimal import Decimal
from typing import Dict, Tuple, Set, List

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

# ---------------------------------------------------------------------------
# Part origin aliases
# ---------------------------------------------------------------------------
PART_ORIGIN_ORIGINAL: Set[str] = {"original", "origine", "oem", "neuf", "neuve", "new"}
PART_ORIGIN_ADAPTABLE: Set[str] = {"adaptable", "equivalent", "aftermarket"}
PART_ORIGIN_RECOVERED: Set[str] = {"recuperation", "recuperable", "occasion", "used"}

# ---------------------------------------------------------------------------
# System families to MCMA rubrique ID mapping
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Table 2 Matching Synonyms & Aliases (Garage Conventionné)
# ---------------------------------------------------------------------------
RUBRIQUE_MATCH_ALIASES: Dict[str, List[str]] = {
    "1": [
        "fournitures carrosserie origines",
        "fournitures carrosserie origine",
        "pieces carrosserie origines",
        "pieces carrosserie origine",
        "fournitures carrosserie oem",
        "pieces origines",
    ],
    "2": [
        "fournitures carrosserie adaptables",
        "fournitures carrosserie adaptable",
        "pieces carrosserie adaptables",
        "pieces carrosserie adaptable",
        "pieces adaptables",
    ],
    "3": [
        "total pieces occasions recuperables",
        "total pieces occasions",
        "pieces occasions recuperables",
        "fournitures carrosserie recuperables",
        "fournitures carrosserie occasions",
        "pieces recuperables",
        "pieces occasions",
    ],
    "4": [
        "fournitures mecanique origines",
        "fournitures mecanique origine",
        "pieces mecanique origines",
    ],
    "5": [
        "fournitures mecanique adaptables",
        "fournitures mecanique adaptable",
        "pieces mecanique adaptables",
    ],
    "6": [
        "fournitures mecanique recuperables",
        "fournitures mecanique occasions",
        "pieces mecanique recuperables",
    ],
    "7": [
        "main d oeuvre carrosserie",
        "mo carrosserie",
        "main d oeuvre tole",
        "mo tole",
        "main doeuvre carrosserie",
    ],
    "8": [
        "main d oeuvre mecanique",
        "mo mecanique",
        "main doeuvre mecanique",
    ],
    "10": [
        "peinture origines",
        "peinture origine",
        "peintures et ingredients",
        "peintures et ingredients",
    ],
    "11": [
        "peinture adaptables",
        "peinture adaptable",
        "peintures et ingredients",
        "peintures et ingredients",
    ],
    "12": [
        "main d oeuvre peinture",
        "mo peinture",
        "main doeuvre peinture",
    ],
    "13": [
        "electrique d origine",
        "electrique origines",
        "fournitures electrique origines",
    ],
    "14": [
        "electrique adaptables",
        "electrique adaptable",
    ],
    "15": [
        "electrique recuperables",
        "electrique occasions",
    ],
    "16": [
        "peintures et ingredients",
        "peintures et ingredients",
        "peinture et ingredients",
        "peintures ingredients",
        "ingredients peinture",
        "produits de peinture",
        "produit de peinture",
        "fournitures et produit de peinture",
        "diverses fournitures et produit de peinture",
        "peinture adaptables",
        "peinture origines",
    ],
    "17": ["passage au marbre", "marbre"],
    "18": ["parallelisme et equilibrage", "geometrie"],
    "19": ["reparation vitre"],
    "20": ["remplacement vitre"],
    "21": ["reparation pare brise"],
    "22": ["remplacement pare brise"],
    "23": ["reparation lunette arriere"],
    "24": ["remplacement lunette arriere"],
    "25": ["colle", "colle pare brise", "mastic colle"],
    "26": ["kit colle pare brise et lunette arriere", "kit colle"],
    "27": ["kit colle vitre"],
    "28": [
        "main d oeuvre electrique",
        "mo electrique",
        "main doeuvre electrique",
    ],
}

# Financial defaults
DEFAULT_TVA_RATE: Decimal = Decimal("0.20")
CENT: Decimal = Decimal("0.01")
