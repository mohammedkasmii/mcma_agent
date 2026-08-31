"""
mcma.domain.rubriques — catalog + corrected classification rules
(BUSINESS_RULES B.1/B.2/B.4/B.7, DOMAIN_MODEL §3):

- three-origin rule: ordinary parts map ONLY by origin to 1/2/3 — the
  classifier structurally cannot see a description, so keyword inference of
  4-6/10-11/13-15 (F33) is impossible;
- glass: component identity x operation -> 19-24, both required, ambiguity or
  conflict fails closed (F13);
- labour: structured-first; explicit labour expressions only; no unrestricted
  'mo' substring (F15); generic family words alone insufficient;
- colle/kits: 25/26/27;
- out-of-catalogue rubric id fails closed (F14).
"""

from typing import Optional

from mcma.domain.enums import GlassComponent, GlassOperation, LabourFamily, Origin
from mcma.domain.normalize import normalize_text
from mcma.domain.results import Mapped, MapResult, NeedsReview, ReasonCode
from mcma.domain.values import RubriqueId

RUBRIQUE_CATALOG: dict[str, str] = {
    "1": "FOURNITURES CARROSSERIE (ORIGINES)",
    "2": "FOURNITURES CARROSSERIE (ADAPTABLES)",
    "3": "TOTAL PIECES OCCASIONS / RECUPERABLES",
    "4": "FOURNITURES MECANIQUE (ORIGINES)",
    "5": "FOURNITURES MECANIQUE (ADAPTABLES)",
    "6": "FOURNITURES MECANIQUE (RECUPERABLES)",
    "7": "MAIN D'OEUVRE CARROSSERIE",
    "8": "MAIN D'OEUVRE MECANIQUE",
    "9": "MONTANT TOTAL",
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
# Three-origin rule (B.1)
# ---------------------------------------------------------------------------

_ORIGIN_ALIASES = {
    Origin.ORIGINAL: {"original", "origine", "oem", "neuf", "neuve", "new"},
    Origin.ADAPTABLE: {"adaptable", "equivalent", "aftermarket"},
    Origin.RECOVERED: {"recuperation", "recuperable", "occasion", "used"},
}

_ORIGIN_RUBRIQUE = {
    Origin.ORIGINAL: RubriqueId("1"),
    Origin.ADAPTABLE: RubriqueId("2"),
    Origin.RECOVERED: RubriqueId("3"),
}


def classify_ordinary_part(part_type: Optional[str], is_original: Optional[bool]) -> MapResult:
    """Origin ONLY — deliberately takes no description/system hint so no
    keyword inference into 4-6/10-11/13-15 is possible. Unknown, missing, or
    contradictory origin signals fail closed."""
    normalized = normalize_text(part_type) if part_type else ""
    from_part_type = None
    for origin, aliases in _ORIGIN_ALIASES.items():
        if normalized in aliases:
            from_part_type = origin
            break

    if from_part_type is None and normalized:
        return NeedsReview(ReasonCode.UNKNOWN_PART_ORIGIN, detail=f"part_type={part_type!r}")
    if is_original is True and from_part_type in (Origin.ADAPTABLE, Origin.RECOVERED):
        return NeedsReview(
            ReasonCode.UNKNOWN_PART_ORIGIN,
            detail=f"is_original=True contradicts part_type={part_type!r}",
        )
    if is_original is False and from_part_type is Origin.ORIGINAL:
        return NeedsReview(
            ReasonCode.UNKNOWN_PART_ORIGIN,
            detail=f"is_original=False contradicts part_type={part_type!r}",
        )
    origin = from_part_type or (Origin.ORIGINAL if is_original is True else None)
    if origin is None:
        return NeedsReview(ReasonCode.UNKNOWN_PART_ORIGIN, detail="no origin signal")
    return Mapped(_ORIGIN_RUBRIQUE[origin])


# ---------------------------------------------------------------------------
# Glass (B.2) — component x operation, both required, fail closed otherwise
# ---------------------------------------------------------------------------

_COMPONENT_TOKENS = {
    GlassComponent.VITRE: ("vitre", "glace", "deflecteur"),
    GlassComponent.PARE_BRISE: ("pare brise", "parebrise"),
    GlassComponent.LUNETTE_ARRIERE: ("lunette arriere", "lunette ar"),
}

_OPERATION_TOKENS = {
    GlassOperation.REPARATION: ("reparation", "resine", "impact"),
    GlassOperation.REMPLACEMENT: ("remplacement", "pose"),
}

_GLASS_MATRIX = {
    (GlassComponent.VITRE, GlassOperation.REPARATION): RubriqueId("19"),
    (GlassComponent.VITRE, GlassOperation.REMPLACEMENT): RubriqueId("20"),
    (GlassComponent.PARE_BRISE, GlassOperation.REPARATION): RubriqueId("21"),
    (GlassComponent.PARE_BRISE, GlassOperation.REMPLACEMENT): RubriqueId("22"),
    (GlassComponent.LUNETTE_ARRIERE, GlassOperation.REPARATION): RubriqueId("23"),
    (GlassComponent.LUNETTE_ARRIERE, GlassOperation.REMPLACEMENT): RubriqueId("24"),
}


def glass_rubrique(component: GlassComponent, operation: GlassOperation) -> RubriqueId:
    return _GLASS_MATRIX[(component, operation)]


def _components_in(norm: str) -> set:
    return {
        component
        for component, tokens in _COMPONENT_TOKENS.items()
        if any(token in norm for token in tokens)
    }


def _operations_in(norm: str) -> set:
    # Word-boundary matching only: 'depose'/'repose' (removal/refit) must
    # never substring-match 'pose' (G1 review H7 — same lesson as F15).
    words = set(norm.split())
    return {
        operation
        for operation, tokens in _OPERATION_TOKENS.items()
        if any(token in words for token in tokens)
    }


def detect_glass_component(text: Optional[str]) -> Optional[GlassComponent]:
    components = _components_in(normalize_text(text))
    return next(iter(components)) if len(components) == 1 else None


def has_glass_signal(text: Optional[str]) -> bool:
    """True when ANY glass-component token is present (including ambiguous
    multi-component text, which must route to the fail-closed glass path)."""
    return bool(_components_in(normalize_text(text)))


def classify_glass_line(description: Optional[str], operation_hint: Optional[str]) -> MapResult:
    norm = f"{normalize_text(description)} {normalize_text(operation_hint)}".strip()
    words = set(norm.split())
    if any(token in words for token in ("moteur", "mecanisme", "leve")):
        return NeedsReview(
            ReasonCode.AMBIGUOUS_GLASS,
            detail="physical component excluded from automatic glass mapping"
        )
    components = _components_in(norm)
    operations = _operations_in(norm)
    if len(components) == 1 and len(operations) == 1:
        return Mapped(glass_rubrique(next(iter(components)), next(iter(operations))))
    return NeedsReview(
        ReasonCode.AMBIGUOUS_GLASS,
        detail=f"components={sorted(c.value for c in components)} "
        f"operations={sorted(o.value for o in operations)}",
    )


# ---------------------------------------------------------------------------
# Labour (B.7) — structured-first; explicit expressions only
# ---------------------------------------------------------------------------

_LABOUR_RUBRIQUE = {
    LabourFamily.TOLERIE_CARROSSERIE: RubriqueId("7"),
    LabourFamily.MECANIQUE: RubriqueId("8"),
    LabourFamily.PEINTURE: RubriqueId("12"),
    LabourFamily.ELECTRIQUE: RubriqueId("28"),
    LabourFamily.MARBRE: RubriqueId("17"),
    LabourFamily.PARALLELISME_EQUILIBRAGE: RubriqueId("18"),
}

# Self-explicit dedicated operations (marker AND family at once).
_SELF_EXPLICIT = {
    LabourFamily.MARBRE: ("marbre",),
    LabourFamily.PARALLELISME_EQUILIBRAGE: ("parallelisme", "equilibrage", "geometrie"),
}

# Body-repair verbs implying tolerie/carrosserie labour by themselves.
_BODY_VERBS = ("debosselage", "redressage")
# Generic labour operation verbs: mark labour but still need a family word.
_GENERIC_LABOUR_VERBS = ("montage", "demontage", "depose", "pose")

_FAMILY_WORDS = {
    LabourFamily.TOLERIE_CARROSSERIE: ("carrosserie", "tolerie"),
    LabourFamily.MECANIQUE: ("mecanique",),
    LabourFamily.PEINTURE: ("peinture",),
    LabourFamily.ELECTRIQUE: ("electrique", "electricite"),
}


def labour_rubrique(family: LabourFamily) -> RubriqueId:
    return _LABOUR_RUBRIQUE[family]


def _explicit_labour_signals(norm: str, *, item_type_says_labour: bool = False) -> tuple[bool, set]:
    """Returns (has_explicit_labour_marker, families named by the text).
    'mo' matches ONLY as a standalone word — never as a substring (F15).

    `item_type_says_labour` supplies the MARKER, not a family. The marker
    only ever answered "is this line labour at all", which a structured
    item_type='labor' states more reliably than a word in free text ever
    could -- so a line Wexia has already declared to be labour does not
    also have to say "main d'oeuvre" in its description before its family
    word counts. No keyword is widened: the family still has to come from
    the existing _FAMILY_WORDS / _SELF_EXPLICIT tokens, a family word
    alone still classifies nothing on a non-labour line, and two families
    still contradict."""
    words = norm.split()
    families: set = set()
    for family, tokens in _SELF_EXPLICIT.items():
        if any(token in norm for token in tokens):
            families.add(family)

    marker = bool(families) or item_type_says_labour
    if "main d oeuvre" in norm or "mo" in words:
        marker = True
    if any(verb in words for verb in _GENERIC_LABOUR_VERBS):
        marker = True
    if any(verb in words for verb in _BODY_VERBS):
        marker = True
        families.add(LabourFamily.TOLERIE_CARROSSERIE)

    if marker:
        for family, tokens in _FAMILY_WORDS.items():
            if any(token in norm for token in tokens):
                families.add(family)
    return marker, families


def _family_from_structured_val(val: str) -> Optional[LabourFamily]:
    norm = normalize_text(val)
    if not norm:
        return None
    for family, tokens in _FAMILY_WORDS.items():
        if any(token in norm for token in tokens):
            return family
    for family, tokens in _SELF_EXPLICIT.items():
        if any(token in norm for token in tokens):
            return family
    return None


def classify_labour_line(
    operation_type: Optional[str],
    labor_type_id: Optional[str],
    item_type: Optional[str],
    text: Optional[str]
) -> MapResult:
    """Structured field decides; free text may only VALIDATE, never override.
    Without a structured family, only explicit labour expressions classify;
    generic family words alone are insufficient. Ambiguity fails closed."""
    norm = normalize_text(text)
    is_structured_item = normalize_text(item_type) in ("labor", "labour")
    marker, text_families = _explicit_labour_signals(norm, item_type_says_labour=is_structured_item)

    has_structured_val = False
    structured_families = set()
    unknown_structured = False
    for val in (operation_type, labor_type_id):
        if val and str(val).strip():
            has_structured_val = True
            fam = _family_from_structured_val(val)
            if fam:
                structured_families.add(fam)
            else:
                unknown_structured = True

    if unknown_structured:
        return NeedsReview(ReasonCode.UNKNOWN_LABOUR, detail=f"unknown structured fields: {operation_type=} {labor_type_id=}")

    # A STRUCTURED FIELD, when present, is authoritative -- unchanged.
    #
    # What changed: item_type='labor' with BOTH structured family fields
    # genuinely absent used to stop here as UNKNOWN_LABOUR. Real Wexia
    # dossiers carry labour that way (item_type='labor', operation_type
    # None, labor_type_id None), so the strict text path never got to run
    # on lines it can classify deterministically. Absent is not the same
    # as unknown: an unrecognised NON-EMPTY structured value still fails
    # closed above, and nothing here widens the text rules.
    if has_structured_val:
        if len(structured_families) > 1:
            return NeedsReview(
                ReasonCode.CONTRADICTORY_LABOUR,
                detail=f"conflicting structured fields: {sorted(f.value for f in structured_families)}"
            )
        structured_family = next(iter(structured_families))
        if marker and text_families and structured_family not in text_families:
            return NeedsReview(
                ReasonCode.CONTRADICTORY_LABOUR,
                detail=f"structured={structured_family.value} text={sorted(f.value for f in text_families)}",
            )
        return Mapped(labour_rubrique(structured_family))

    if not marker:
        if is_structured_item:
            return NeedsReview(
                ReasonCode.UNKNOWN_LABOUR,
                detail="item_type=labour with no structured family and no explicit labour signal in text",
            )
        return NeedsReview(ReasonCode.UNKNOWN_LABOUR, detail=f"no explicit labour signal in {text!r}")
    if len(text_families) == 1:
        return Mapped(labour_rubrique(next(iter(text_families))))
    if len(text_families) > 1:
        return NeedsReview(
            ReasonCode.CONTRADICTORY_LABOUR,
            detail=f"families={sorted(f.value for f in text_families)}",
        )
    return NeedsReview(ReasonCode.UNKNOWN_LABOUR, detail=f"labour marker without family in {text!r}")


# ---------------------------------------------------------------------------
# Colle / kits (25/26/27) and out-of-catalogue (B.4)
# ---------------------------------------------------------------------------

def classify_colle(description: Optional[str]) -> Optional[MapResult]:
    # Word-boundary matching: 'collecteur'/'recollee' must never classify as
    # glue (G1 review H6).
    words = set(normalize_text(description).split())
    if not words or ("colle" not in words and "mastic" not in words):
        return None
    if "kit" in words:
        components = _components_in(normalize_text(description))
        if not components:
            return NeedsReview(ReasonCode.AMBIGUOUS_GLASS, detail="kit colle without component")
        if len(components) > 1:
            return NeedsReview(ReasonCode.AMBIGUOUS_GLASS, detail="kit colle with conflicting components")
        comp = next(iter(components))
        if comp is GlassComponent.VITRE:
            return Mapped(RubriqueId("27"))
        return Mapped(RubriqueId("26"))
    return Mapped(RubriqueId("25"))


_PEINTURE_MATERIAL_PHRASES = (
    "peintures et ingredients",
    "peinture et ingredients",
    "produit de peinture",
    "produits de peinture",
)


def classify_peinture_materials(description: Optional[str]) -> Optional[RubriqueId]:
    """Painting materials/products/ingredients → 16 (DOMAIN_MODEL §3). A bare
    'peinture' is NOT sufficient; physical painting-related parts stay on the
    origin path (1/2/3) and 10/11 are never produced."""
    norm = normalize_text(description)
    if not norm:
        return None
    if any(phrase in norm for phrase in _PEINTURE_MATERIAL_PHRASES):
        return RubriqueId("16")
    words = set(norm.split())
    if "ingredient" in words or "ingredients" in words:
        return RubriqueId("16")
    return None


# Rubrique 9 (MONTANT TOTAL) is an aggregate row — never a line target
# (G1 review M3).
_LINE_ASSIGNABLE_RUBRIQUES = frozenset(RUBRIQUE_CATALOG) - {"9"}


def resolve_explicit_rubrique(raw_id) -> MapResult:
    candidate = str(raw_id or "").strip()
    if candidate in _LINE_ASSIGNABLE_RUBRIQUES:
        return Mapped(RubriqueId(candidate))
    return NeedsReview(ReasonCode.UNKNOWN_RUBRIC_ID, detail=f"mcma_rubric_id={raw_id!r}")
