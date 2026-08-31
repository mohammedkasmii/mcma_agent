"""
mcma.planning.plan — deterministic, capability-neutral plan types and the
mission-normal plan builder (ADR-0002, DOMAIN_MODEL §6).

ProposedPlan is PURE IMMUTABLE DATA: no `mode`, no `read_only`, no live
capability, no charge-mutuelle field anywhere. Any NeedsReview makes the plan
non-writeable. Same input (regardless of line order) yields identical steps,
input_hash, and plan_hash.

This module imports only mcma.domain / mcma.core (never mcma.mapping — the
typed input is consumed structurally; `execution` wires the two at INC-12).
"""

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence, Tuple

from mcma.core.money import Money
from mcma.domain.normalize import normalize_text
from mcma.domain.results import Mapped, NeedsReview, ReasonCode, tva_allocation_result
from mcma.domain.rubriques import (
    MODE_NORMAL_ALLOWED_RUBRIQUES,
    classify_colle,
    classify_glass_line,
    classify_labour_line,
    classify_ordinary_part,
    classify_peinture_materials,
    has_glass_signal,
    resolve_explicit_rubrique,
)
from mcma.domain.enums import FormFieldSelector, RepairWorkflow
from mcma.domain.values import FormFieldIntent, IdSinistre, InsurerReference, RegistrationPlate, RubriqueId

# ---------------------------------------------------------------------------
# Non-table header fields (correction batch, section J) -- evidence matrix
# ---------------------------------------------------------------------------
# docs/recovery/PORTAL_CONTRACT.md §5 lists TEN recovered selectors. Of
# those, only the five below have BOTH a confirmed, unambiguous single-
# valued JSON source AND no evidence of being portal-computed --
# implemented here as FormFieldIntent. The remaining five are deliberately
# NOT implemented (never guessed):
#   - MontantReparation / MontantTVA / MontantTTC: recovered baseline
#     mapper/wexia_mapper.py writes these, but browser/form_filler.py
#     calls trigger_mcma_calculations() immediately after filling text
#     fields, strongly suggesting the portal recalculates these itself --
#     UNCONFIRMED whether writing them is safe or even meaningful; do not
#     write them if native calculation owns them.
#   - VehRepareI: PORTAL_CONTRACT.md §4 confirms it as a SHARED
#     mission-option/header field (never a workflow detector), but no
#     recovered evidence maps ANY Wexia JSON field to it -- the baseline
#     mapper hardcodes it to a constant (True) with no JSON source at
#     all, which is a business-rule assumption, not an evidenced mapping,
#     and no such rule is confirmed here.
#   - TypeReforme: no recovered evidence maps dossier.is_reform (or
#     anything else) to this selector; reform dossiers are already
#     excluded upstream (_build_plan_core raises PlanBuildError before
#     any plan exists), and the baseline mapper never writes it either.
# Each implemented field's confirmed source (recovered baseline
# mapper/wexia_mapper.py line references in parentheses):
#   Kilometrage            <- vehicule.mileage_km, else dossier.mileage_km (:383)
#   ValeurVenale/Estime    <- vehicule.market_value, else dossier.market_value (:393; dual-write :392-396)
#   NbreJourImmobilisation <- chiffrage.estimated_days, only when > 0 (:388-390)
#   PartResponsabilite     <- dossier.responsibility_rate, else assureur.responsibility_rate;
#                             constrained to {0, 50, 100} -- NeedsReview otherwise, never guessed (:454-459)
#   ObservationMission     <- observations_expert.texte, else dossier.expert_observations (:442-445)
# All five are shared header fields present on every mission regardless
# of workflow (PORTAL_CONTRACT.md §4-5) -- FormFieldIntent.applicable_
# workflows lists both for all five today.

_VALID_RESPONSIBILITY_RATES = frozenset({"0", "50", "100"})

BUILDER_VERSION = "inc05-3"

_CENT = Decimal("0.01")


class PlanBuildError(ValueError):
    """Fail-closed: the input cannot yield a plan at all (reform dossier,
    conflicting explicit modes, missing identity, total mismatch)."""


@dataclass(frozen=True)
class ExpectedIdentity:
    """Correction #4: registration is MANDATORY; at least one of insurer
    reference / idSinistre is also required. A plate alone is insufficient."""

    registration: RegistrationPlate
    insurer_reference: Optional[InsurerReference] = None
    id_sinistre: Optional[IdSinistre] = None

    def __post_init__(self):
        if not isinstance(self.registration, RegistrationPlate):
            raise TypeError("ExpectedIdentity requires a RegistrationPlate")
        if self.insurer_reference is not None and not isinstance(
            self.insurer_reference, InsurerReference
        ):
            raise TypeError("insurer_reference must be an InsurerReference")
        if self.id_sinistre is not None and not isinstance(self.id_sinistre, IdSinistre):
            raise TypeError("id_sinistre must be an IdSinistre")
        if self.insurer_reference is None and self.id_sinistre is None:
            raise ValueError(
                "ExpectedIdentity requires insurer_reference and/or id_sinistre "
                "(a registration plate alone is insufficient)"
            )


@dataclass(frozen=True)
class RowOp:
    """One reviewed row operation. Structurally, no charge-mutuelle field can
    ever exist here (B.3)."""

    rubrique_id: RubriqueId
    ht: Money
    tva: Money
    vetuste: Money
    source_pointers: Tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.rubrique_id, RubriqueId):
            raise TypeError("rubrique_id must be a RubriqueId")
        for name in ("ht", "tva", "vetuste"):
            value = getattr(self, name)
            if not isinstance(value, Money):
                raise TypeError(f"{name} must be Money")
            if value.is_negative:
                raise ValueError(f"RowOp.{name} must not be negative")
        if not self.source_pointers:
            raise ValueError("RowOp requires at least one source pointer")
        if not all(p and str(p).strip() for p in self.source_pointers):
            raise ValueError("RowOp source pointer cannot be empty")


# FormFieldIntent moved to mcma.domain.values (pilot-integration
# correction) so mcma.portal.writer can consume it too without violating
# "persistence/portal may import only domain and core" -- re-exported
# here for backward compatibility (existing imports of
# `from mcma.planning.plan import FormFieldIntent` keep working).


@dataclass(frozen=True)
class Provenance:
    input_hash: str
    plan_hash: str
    builder_version: str


@dataclass(frozen=True)
class ProposedPlan:
    expected_identity: ExpectedIdentity
    repair_workflow: RepairWorkflow
    steps: Tuple[RowOp, ...]
    needs_review: Tuple[NeedsReview, ...]
    provenance: Provenance
    form_field_intents: Tuple[FormFieldIntent, ...] = ()

    @property
    def is_writeable(self) -> bool:
        """Non-empty needs_review ⇒ NON-WRITEABLE (structural gate, F11 fixed).
        Zero steps ⇒ NON-WRITEABLE."""
        return not self.needs_review and len(self.steps) > 0

    def canonical_json(self) -> str:
        return _canonical_json(_canonicalize(self))


# ---------------------------------------------------------------------------
# Canonical serialization + hashes (deterministic by construction)
# ---------------------------------------------------------------------------

def _canonicalize(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: _canonicalize(getattr(obj, f.name)) for f in dataclasses.fields(obj)
        }
    if isinstance(obj, Money):
        return str(obj.amount)
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _canonicalize(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    # Anything else (float, set, arbitrary repr) is a nondeterminism hazard
    # in the hash pipeline — refuse instead of stringifying (G1 review M6).
    raise TypeError(f"non-canonicalizable type in plan data: {type(obj).__name__}")


def _canonical_json(canonical) -> str:
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_input_hash(typed_input) -> str:
    """Order-insensitive over line lists: each chiffrage's lines are sorted by
    their own canonical form before hashing, so shuffled input hashes alike."""
    dumped = typed_input.model_dump(mode="json")
    for chiffrage in dumped.get("chiffrages", []):
        for key in ("lignes_pieces", "lignes_mo"):
            lines = chiffrage.get(key) or []
            chiffrage[key] = sorted(lines, key=lambda l: _canonical_json(_canonicalize(l)))
    return _sha256(_canonical_json(_canonicalize(dumped)))


def _content_pointer(prefix: str, line, seen: dict) -> str:
    """Content-derived source pointer (index-free so line order cannot leak
    into the plan); identical lines get stable occurrence suffixes."""
    digest = _sha256(_canonical_json(_canonicalize(line.model_dump(mode="json"))))[:12]
    occurrence = seen.get((prefix, digest), 0)
    seen[(prefix, digest)] = occurrence + 1
    return f"{prefix}:{digest}#{occurrence}"


# ---------------------------------------------------------------------------
# Mission-normal plan builder (pure function of typed input)
# ---------------------------------------------------------------------------

_CONV_PHRASES = ("conventionne", "garage conventionne")


def _detect_mode_fail_closed(dossier) -> str:
    """Explicit signals only; 'pec' matches as a standalone word (never inside
    'inspection'/'respecter'); NO signal at all fails closed — the mode is
    never silently defaulted (G1 review H1)."""
    signals = [
        normalize_text(dossier.mission_type),
        normalize_text(dossier.repair_mode),
        normalize_text(dossier.incident_description),
    ]
    explicit_normal = any("normal" in s.split() for s in signals if s)
    explicit_conv = any(
        any(phrase in s for phrase in _CONV_PHRASES) or "pec" in s.split()
        for s in signals
        if s
    )
    if explicit_normal and explicit_conv:
        raise PlanBuildError("conflicting explicit mission modes — fail closed")
    if not explicit_normal and not explicit_conv:
        raise PlanBuildError("no explicit mission-mode signal — fail closed")
    return "conventionne" if explicit_conv else "normal"


def _validate_chiffrage_totals(chiffrage, ht_sum: Decimal) -> None:
    """Checks the mapped HT against the chiffrage's own aggregates.

    total_cost cannot be trusted to mean one thing. Real payloads use it
    BOTH ways: in most, total_cost is HT and final_cost is HT + tax; in
    others total_cost equals final_cost, i.e. TTC. Treating it as HT
    everywhere rejects coherent dossiers, and quietly ignoring it when it
    disagrees would drop the only cross-check on the total.

    So the shape is decided by ARITHMETIC, never by document_type,
    scenario_type, status, filename or anything else about the dossier's
    identity. total_cost is accepted when it equals HT, or when it equals
    a final_cost that has itself been proven to equal HT + tax. Anything
    else fails closed."""
    parts = chiffrage.total_parts_cost
    labour = chiffrage.total_labor_cost

    if (parts is None) != (labour is None):
        # One half of a breakdown says nothing. Treating the missing side
        # as zero would silently validate against a wrong HT.
        raise PlanBuildError(
            "chiffrage has only one of total_parts_cost/total_labor_cost — "
            "absent is not zero, fail closed"
        )

    if parts is not None and labour is not None:
        aggregate_ht = Money.of(parts).amount + Money.of(labour).amount
        if abs(ht_sum - aggregate_ht) > _CENT:
            raise PlanBuildError(
                f"HT sum {ht_sum} differs from total_parts_cost + total_labor_cost "
                f"{aggregate_ht} by > 0.01"
            )
    else:
        # Legacy payloads carry no breakdown; total_cost is HT there, which
        # is the rule this validation has always applied.
        aggregate_ht = None

    tva = Money.of(chiffrage.tax_amount).amount
    total_cost = Money.of(chiffrage.total_cost).amount

    proven_ttc = None
    if chiffrage.final_cost is not None:
        final_cost = Money.of(chiffrage.final_cost).amount
        if abs((ht_sum + tva) - final_cost) > _CENT:
            raise PlanBuildError(
                f"HT {ht_sum} + TVA {tva} differs from final_cost {final_cost} by > 0.01"
            )
        proven_ttc = final_cost

    if abs(total_cost - ht_sum) <= _CENT:
        return                                   # Shape A: total_cost is HT
    if proven_ttc is not None and abs(total_cost - proven_ttc) <= _CENT:
        return                                   # Shape B: total_cost is TTC
    # Shape B is never inferred from total_cost merely differing from HT --
    # without final_cost there is nothing proving what it would be.
    raise PlanBuildError(
        f"chiffrage total_cost {total_cost} matches neither HT {ht_sum} nor a "
        f"proven TTC (final_cost={chiffrage.final_cost!r}) — fail closed"
    )


def _glass_operation_evidence(line) -> str:
    """Every field that can state the operation, joined.

    It used to be `line.operation_type or line.notes`, which silently
    picked one source and dropped the rest -- so a line whose
    operation_type was null and whose repair_action said "remplacement"
    came out AMBIGUOUS_GLASS despite saying exactly what it was. Joining
    is also the conflict-safe choice: contradictory evidence produces two
    operations and classify_glass_line fails closed, where preferring one
    field would have quietly resolved the contradiction in its favour."""
    parts = (line.operation_type, getattr(line, "repair_action", None), line.notes)
    return " ".join(str(part) for part in parts if part)


def _glass_signal_text(line) -> str:
    return f"{line.item_name} {_glass_operation_evidence(line)}"


def _select_chiffrage(chiffrages):
    """Deterministic, fail-closed selection (G1 review H2): a chiffrage is
    used only when it is the unambiguous winner — never candidates[0] by
    payload order."""
    # An explicitly archived version is a retired estimate, not a rival
    # candidate. Leaving them in manufactured ambiguity between a current
    # chiffrage and a superseded one, which fails closed on a question the
    # dossier had already answered. archived_at is the marker;
    # archive_cycle alone is not treated as proof.
    live = [c for c in chiffrages if not (getattr(c, "archived_at", None) or "")]
    candidates = [
        c
        for c in live
        if c.has_lines and "honoraire" not in normalize_text(c.scenario_type)
        and "fee" not in normalize_text(c.scenario_type)
    ]
    if not candidates:
        raise PlanBuildError("no detailed repair chiffrage — fail closed")
    approved = [c for c in candidates if normalize_text(c.status) == "approved"]
    if approved:
        final = [c for c in approved if c.is_final]
        pool = final or approved
        if len(pool) > 1:
            dumps = {_canonical_json(_canonicalize(c.model_dump(mode="json"))) for c in pool}
            if len(dumps) > 1:
                raise PlanBuildError(
                    "multiple distinct approved chiffrages — explicit selection required, fail closed"
                )
        return pool[0]
    if len(candidates) > 1:
        raise PlanBuildError(
            "multiple non-approved chiffrages and no approved winner — fail closed"
        )
    return candidates[0]


_BOTH_WORKFLOWS: Tuple[RepairWorkflow, ...] = (RepairWorkflow.MODE_NORMAL, RepairWorkflow.GARAGE_CONVENTIONNE)


def _build_form_field_intents(typed_input, chiffrage) -> Tuple[Tuple[FormFieldIntent, ...], list]:
    """Correction batch (section J) -- see the module-level evidence-matrix
    comment above BUILDER_VERSION for exactly why each of these five (and
    only these five) is implemented. Returns (intents, extra_needs_review)
    -- PartResponsabilite present but outside {0, 50, 100} becomes a
    NeedsReview entry (never guessed, never a hard PlanBuildError: the
    rest of the plan can still be produced/reviewed as normal)."""
    intents: list = []
    extra_reviews: list = []
    dossier = typed_input.dossier
    vehicule = typed_input.vehicule

    km = vehicule.mileage_km if vehicule.mileage_km is not None else dossier.mileage_km
    if km is not None:
        intents.append(FormFieldIntent(FormFieldSelector.KILOMETRAGE, str(int(km)), _BOTH_WORKFLOWS))

    market_value = vehicule.market_value if vehicule.market_value is not None else dossier.market_value
    if market_value is not None:
        intents.append(FormFieldIntent(FormFieldSelector.VALEUR_VENALE, str(int(market_value)), _BOTH_WORKFLOWS))
        intents.append(
            FormFieldIntent(FormFieldSelector.VALEUR_VENALE_ESTIME, str(int(market_value)), _BOTH_WORKFLOWS)
        )

    days = chiffrage.estimated_days
    if days is not None and int(days) > 0:
        intents.append(FormFieldIntent(FormFieldSelector.NBRE_JOUR_IMMOBILISATION, str(int(days)), _BOTH_WORKFLOWS))

    rate = dossier.responsibility_rate if dossier.responsibility_rate is not None else typed_input.assureur.responsibility_rate
    if rate is not None:
        rate_str = str(int(rate))
        if rate_str in _VALID_RESPONSIBILITY_RATES:
            intents.append(FormFieldIntent(FormFieldSelector.PART_RESPONSABILITE, rate_str, _BOTH_WORKFLOWS))
        else:
            extra_reviews.append(
                NeedsReview(
                    ReasonCode.INVALID_RESPONSIBILITY_RATE,
                    detail=f"responsibility_rate {rate_str!r} is not one of 0/50/100 — fail closed, never guessed",
                )
            )

    obs_text = typed_input.observations_expert.texte or dossier.expert_observations
    if obs_text:
        intents.append(FormFieldIntent(FormFieldSelector.OBSERVATION_MISSION, str(obs_text), _BOTH_WORKFLOWS))

    return tuple(intents), extra_reviews


def _classify_piece(line):
    """Classification order: explicit id → structured labour → colle → glass →
    ordinary part (origin only)."""
    if line.is_labour:
        sem_result = classify_labour_line(
            operation_type=line.operation_type,
            labor_type_id=line.labor_type_id,
            item_type=line.item_type,
            text=f"{line.item_name} {line.notes}",
        )
    else:
        colle = classify_colle(line.item_name)
        if colle is not None:
            sem_result = colle
        else:
            peinture = classify_peinture_materials(line.item_name)
            if peinture is not None:
                sem_result = Mapped(peinture)
            elif has_glass_signal(_glass_signal_text(line)):
                sem_result = classify_glass_line(line.item_name, _glass_operation_evidence(line))
            else:
                sem_result = classify_ordinary_part(part_type=line.part_type, is_original=line.is_original)

    if line.mcma_rubric_id:
        explicit_result = resolve_explicit_rubrique(line.mcma_rubric_id)
        if isinstance(explicit_result, NeedsReview):
            return explicit_result
        if isinstance(sem_result, NeedsReview):
            return sem_result
        if explicit_result.value != sem_result.value:
            return NeedsReview(
                ReasonCode.UNKNOWN_RUBRIC_ID,
                detail=f"explicit rubric conflicts with semantic classification (explicit={explicit_result.value.value}, semantic={sem_result.value.value})"
            )
        return explicit_result

    return sem_result


def _build_plan_core(typed_input, expected_workflow: RepairWorkflow) -> ProposedPlan:
    dossier = typed_input.dossier
    if dossier.is_reform is None:
        raise PlanBuildError("is_reform marker missing from the payload — fail closed")
    if dossier.is_reform:
        raise PlanBuildError("reform dossiers are excluded from automation — fail closed")
    mode = _detect_mode_fail_closed(dossier)
    if mode == "normal" and expected_workflow != RepairWorkflow.MODE_NORMAL:
        raise PlanBuildError(
            f"mission mode {mode!r} is not handled by this builder — fail closed"
        )
    if mode == "conventionne" and expected_workflow != RepairWorkflow.GARAGE_CONVENTIONNE:
        raise PlanBuildError(
            f"mission mode {mode!r} is not handled by this builder — fail closed"
        )

    plate_raw = typed_input.registration_raw
    if not plate_raw or not str(plate_raw).strip():
        raise PlanBuildError("registration plate is mandatory — fail closed")
    reference = typed_input.primary_reference
    id_sin = typed_input.id_sinistre_raw
    if not reference and not id_sin:
        raise PlanBuildError("insurer reference or idSinistre is required — fail closed")

    identity = ExpectedIdentity(
        registration=RegistrationPlate(str(plate_raw)),
        insurer_reference=InsurerReference(str(reference)) if reference else None,
        id_sinistre=IdSinistre(str(id_sin)) if id_sin else None,
    )

    chiffrage = _select_chiffrage(typed_input.chiffrages)
    if chiffrage.total_cost is None or chiffrage.tax_amount is None:
        raise PlanBuildError(
            "chiffrage total_cost/tax_amount missing — absent is not zero, fail closed"
        )

    groups: dict = {}
    reviews: list = []
    seen_pointers: dict = {}

    form_field_intents, form_field_reviews = _build_form_field_intents(typed_input, chiffrage)
    reviews.extend(form_field_reviews)

    def _add(rubrique: RubriqueId, ht: Money, vetuste: Money, pointer: str):
        entry = groups.setdefault(
            rubrique.value, {"ht": Money.ZERO, "vetuste": Money.ZERO, "pointers": []}
        )
        entry["ht"] = entry["ht"] + ht
        entry["vetuste"] = entry["vetuste"] + vetuste
        entry["pointers"].append(pointer)

    for line in chiffrage.lignes_pieces:
        if line.subtotal < 0 or line.depreciation_amount < 0:
            raise PlanBuildError("negative subtotal or depreciation not allowed")
        if line.subtotal == 0:
            continue
        pointer = _content_pointer("piece", line, seen_pointers)
        result = _classify_piece(line)
        if isinstance(result, NeedsReview):
            reviews.append(result)
        else:
            _add(result.value, Money.of(line.subtotal), Money.of(line.depreciation_amount), pointer)

    for line in chiffrage.lignes_mo:
        if line.subtotal < 0:
            raise PlanBuildError("negative subtotal not allowed")
        if line.subtotal == 0:
            continue
        pointer = _content_pointer("mo", line, seen_pointers)
        result = classify_labour_line(
            operation_type=line.operation_type,
            labor_type_id=line.labor_type_id,
            item_type="labor", # lines from lignes_mo intrinsically have item_type="labor"
            text=f"{line.operation_type or ''} {line.notes}",
        )
        if isinstance(result, NeedsReview):
            reviews.append(result)
        else:
            _add(result.value, Money.of(line.subtotal), Money.ZERO, pointer)

    if not groups and not reviews:
        raise PlanBuildError(
            "no plannable line survived filtering — an empty writeable plan is not allowed"
        )

    # Deterministic step order: rubrique_id (numeric), then first source pointer.
    ordered = sorted(
        groups.items(), key=lambda kv: (int(kv[0]), sorted(kv[1]["pointers"])[0])
    )

    # Totals check (fail closed; 0.01 MAD bound) — only meaningful when every
    # line mapped; with reviews present the plan is non-writeable anyway.
    if not reviews:
        ht_sum = sum((entry["ht"].amount for _, entry in ordered), Decimal("0"))
        _validate_chiffrage_totals(chiffrage, ht_sum)

    line_hts = [entry["ht"] for _, entry in ordered]
    tva_result = tva_allocation_result(line_hts, Money.of(chiffrage.tax_amount))
    if isinstance(tva_result, NeedsReview):
        reviews.append(tva_result)
        tva_amounts: Sequence[Money] = [Money.ZERO] * len(ordered)
    else:
        tva_amounts = tva_result.value

    steps = tuple(
        RowOp(
            rubrique_id=RubriqueId(rubrique_value),
            ht=entry["ht"],
            tva=tva,
            vetuste=entry["vetuste"],
            source_pointers=tuple(sorted(entry["pointers"])),
        )
        for (rubrique_value, entry), tva in zip(ordered, tva_amounts)
    )

    needs_review = tuple(sorted(reviews, key=lambda r: (r.reason.value, r.detail)))

    input_hash = compute_input_hash(typed_input)
    body = _canonical_json(
        _canonicalize(
            {
                "expected_identity": identity,
                "repair_workflow": expected_workflow,
                "steps": list(steps),
                "needs_review": list(needs_review),
                "form_field_intents": list(form_field_intents),
                "builder_version": BUILDER_VERSION,
                "input_hash": input_hash,
            }
        )
    )
    provenance = Provenance(
        input_hash=input_hash, plan_hash=_sha256(body), builder_version=BUILDER_VERSION
    )
    return ProposedPlan(
        expected_identity=identity,
        repair_workflow=expected_workflow,
        steps=steps,
        needs_review=needs_review,
        provenance=provenance,
        form_field_intents=form_field_intents,
    )


def build_mission_normal_plan(typed_input) -> ProposedPlan:
    plan = _build_plan_core(typed_input, RepairWorkflow.MODE_NORMAL)
    _enforce_mode_normal_rubrique_policy(plan)
    return plan


def _enforce_mode_normal_rubrique_policy(plan: ProposedPlan) -> None:
    """Refuses any Mode Normal row outside the agency's mapping surface.

    The classifiers already only produce allowed rubriques -- this is a
    backstop, not a fix. It exists because the old mapper's
    SYSTEM_RUBRIQUE_MATRIX derived 4/5/6, 10/11 and 13/14/15 from an
    item's physical family, so a "moteur original" became a mechanical
    rubrique instead of an origin one, and that mistake is easy to
    reintroduce one plausible-looking keyword at a time. A row outside the
    policy is a fail-closed error rather than a NeedsReview: it means a
    classifier is producing something the agency's rule has no place for,
    which is a defect in this system, not a question about the dossier.

    Mode Normal only. Garage Conventionné maps against pre-existing portal
    rows and is deliberately left alone."""
    offenders = sorted(
        {step.rubrique_id.value for step in plan.steps}
        - {r.value for r in MODE_NORMAL_ALLOWED_RUBRIQUES},
        key=int,
    )
    if offenders:
        raise PlanBuildError(
            f"Mode Normal produced rubrique(s) outside the agency mapping policy: "
            f"{offenders} — fail closed"
        )


def build_garage_conventionne_plan(typed_input) -> ProposedPlan:
    return _build_plan_core(typed_input, RepairWorkflow.GARAGE_CONVENTIONNE)


def detect_workflow(typed_input) -> RepairWorkflow:
    """Pilot-integration correction (section 3): the ONE public function
    that determines the target workflow from typed evidence alone,
    before any plan is built -- the real job runner uses this so it
    never has to accept (let alone hardcode) a workflow name from the
    browser/client. A thin public wrapper around the exact same
    fail-closed detection _build_plan_core itself calls internally (so
    build_mission_normal_plan/build_garage_conventionne_plan's own
    redundant check can never disagree with this) -- raises
    PlanBuildError on conflicting or absent signals, never guesses."""
    mode = _detect_mode_fail_closed(typed_input.dossier)
    return RepairWorkflow.MODE_NORMAL if mode == "normal" else RepairWorkflow.GARAGE_CONVENTIONNE
