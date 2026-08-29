# DOMAIN MODEL

**Baseline:** `0290fe9…` · target design. Pure, deterministic, no I/O (`MODULE_BOUNDARIES.md`).
Authoritative business rules: `docs/recovery/BUSINESS_RULES.md` (§B). This document types them.

---

## 1. Value objects (immutable)
- `Money` — `Decimal`, 2 dp, `ROUND_HALF_UP`; all monetary arithmetic uses it. No float, no str, ever crosses a domain boundary.
- `RegistrationPlate` — normalized (accents/punctuation/hyphens/repeated-whitespace stripped); the normalized form is the comparison key.
- `InsurerReference`, `IdSinistre` — opaque typed identifiers; `IdSinistre` is the stable claim key.
- `AccountId`, `RubriqueId`.

## 2. Enums (normalization targets)
- `Origin` = {ORIGINAL, ADAPTABLE, RECOVERED}
- `LabourFamily` = {TOLERIE_CARROSSERIE, MECANIQUE, PEINTURE, ELECTRIQUE, MARBRE, PARALLELISME_EQUILIBRAGE}
- `GlassComponent` = {VITRE, PARE_BRISE, LUNETTE_ARRIERE}
- `GlassOperation` = {REPARATION, REMPLACEMENT}
- `Permission` = {notifications:read, notifications:update, jobs:submit, jobs:view, sessions:manage, accounts:manage, users:manage} (used by `app`; kept as an enum, never stringly-typed — footgun A12)

## 3. Normalization contracts
A single shared normalizer (strip accents, lowercase, collapse punctuation/hyphens/whitespace) feeds all matchers.

**Origin (three-origin rule, B.1):** ordinary parts map **only** by origin → 1 / 2 / 3. No keyword inference of
4–6 / 13–15. Painting parts still follow origin → 1/2/3; the agent never generates 10/11.

**Glass (B.2, resolved vocabulary):** requires **both** a component AND an operation.
- Component: VITRE ⊂ {vitre, glace, deflecteur}; PARE_BRISE ⊂ {pare-brise, parebrise, pare brise};
  LUNETTE_ARRIERE ⊂ {lunette arrière, lunette arriere, lunette ar}.
- Operation: REPARATION ⊂ {réparation, reparation, résine, resine, impact}; REMPLACEMENT ⊂ {remplacement, pose}.
- Mapping: (VITRE,REPARATION)→19 · (VITRE,REMPLACEMENT)→20 · (PARE_BRISE,REPARATION)→21 · (PARE_BRISE,REMPLACEMENT)→22 ·
  (LUNETTE_ARRIERE,REPARATION)→23 · (LUNETTE_ARRIERE,REMPLACEMENT)→24.
- **Fail closed** on: conflicting repair/replacement signals, missing operation, or ambiguous component → `NeedsReview(AMBIGUOUS_GLASS)`.
- **`part_type` is origin only** — never used to infer glass family.

**Painting (B.2):** materials/products/ingredients → 16; painting labour → 12; a physical painting-related part → origin 1/2/3; never 10/11.

**Labour (B.7, structured-first):** typed boundary over `lignes_pieces[].item_type`, `lignes_mo[].operation_type`,
`lignes_mo[].labor_type_id`. Structured fields decide the `LabourFamily`; text heuristics may only **validate**, never
override a structured value. Family → rubrique: TOLERIE_CARROSSERIE→7 · MECANIQUE→8 · PEINTURE→12 · ELECTRIQUE→28 ·
MARBRE→17 · PARALLELISME_EQUILIBRAGE→18. Missing/unknown/contradictory → `NeedsReview(UNKNOWN_LABOUR|CONTRADICTORY_LABOUR)`.
The old unrestricted `"mo"` substring is removed.

**Out-of-catalogue rubric id (B.4):** an explicit `mcma_rubric_id` not in the catalog → `NeedsReview(UNKNOWN_RUBRIC_ID)`. No silent inference.

## 4. Mapping result algebra
`MapLineResult = Mapped(RubriqueLine) | NeedsReview(reason_code)` where reason_code ∈
{INVALID_TAX_ALLOCATION, AMBIGUOUS_GLASS, UNKNOWN_RUBRIC_ID, UNKNOWN_LABOUR, CONTRADICTORY_LABOUR, UNKNOWN_PART_ORIGIN}.

## 5. Money & tax (B.3, B.6)
- All sums in `Money`; per-group tax remainder allocation preserves totals to **0.01 MAD** (no 0.05 tolerance).
- **Negative line TVA is invalid.** Initial policy: do **not** clamp, do **not** redistribute → `NeedsReview(INVALID_TAX_ALLOCATION)`.
- **Charge mutuelle:** portal-native calculation is authoritative in both modes; the domain never produces a write for
  `MontantChargeSocietaire`/`MontantChargeMutuelle`, and the plan cannot contain one (see §6).

## 6. Plan types (deterministic)
```text
ExecutionPlan {
  claim_ref: InsurerReference | IdSinistre
  mode: DRY_RUN | EXECUTE
  read_only: bool
  steps: [RowOp]                 # ordered, stable
  needs_review: [NeedsReview]    # non-empty ⇒ plan is NON-WRITEABLE
  provenance: {input_hash, builder_version}
}
RowOp { rubrique_id: RubriqueId, ht: Money, tva: Money, vetuste: Money, source_pointers: [str] }
```
- `RowOp` has **no field** for charge-mutuelle — it is structurally impossible to write it.
- **Determinism:** a plan builder is a pure function of typed input; steps are stably ordered (rubrique_id, then first
  source pointer); no wall-clock, randomness, or set-iteration order affects output. Same input → identical plan and
  identical `plan_hash` (property-tested, `TEST_STRATEGY.md`).
- Any `NeedsReview` present ⇒ the writer refuses the plan (fail closed).

## 7. Entities (persistence-facing shapes are in `DATA_MODEL.md`)
`Account`, `PortalSession`, `Claim` (identity = `AccountId` + `IdSinistre`), `CategoryPresence`, `PollRun`,
`AutomationJob`, `AccountLease`, `EmployeeAction`, `AuditEvent`, `User`. The domain defines their invariants; the
`persistence` module maps them to SQLite.
