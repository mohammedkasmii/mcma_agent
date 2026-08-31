# Mode Normal automatic mapping policy

Agency-confirmed. Encoded in `mcma/domain/rubriques.py` as
`MODE_NORMAL_PART_RUBRIQUES`, `MODE_NORMAL_LABOUR_RUBRIQUES`,
`MODE_NORMAL_EXCEPTION_RUBRIQUES` and their union
`MODE_NORMAL_ALLOWED_RUBRIQUES`, and enforced by
`_enforce_mode_normal_rubrique_policy()` in `mcma/planning/plan.py`.

---

## The distinction this exists for

> **The MCMA 28-rubrique catalog is the chart of accounts.
> It is NOT the surface this system may map to automatically.**

Conflating the two is the mistake the old mapper made. Its
`SYSTEM_RUBRIQUE_MATRIX` read a part's physical family out of its name,
system or category and produced a rubrique from that — so a *moteur
origine* landed in a mechanical-parts rubrique instead of an origin one.
`docs/recovery/BUSINESS_RULES.md` records that behaviour as a
contradiction. It is not to be restored.

---

## Ordinary pieces — origin only

| Origin | Rubrique |
|---|---|
| origine / original / OEM / neuf | **1** — Fournitures carrosserie (origines) |
| adaptable / équivalent / aftermarket | **2** — Fournitures carrosserie (adaptables) |
| récupérable / récupération / occasion / used | **3** — Total pièces occasions / récupérables |

The physical family of the piece **must not** change this.

```
moteur origine      -> 1        moteur adaptable    -> 2
batterie origine    -> 1        batterie occasion   -> 3
radiateur origine   -> 1        porte origine       -> 1
```

`classify_ordinary_part()` takes only `part_type` and `is_original` — it
has no parameter through which a name, system, category, description or
note could reach it, which is asserted by test rather than described.

---

## Normal labour — four families

| Rubrique | Family |
|---|---|
| **7** | Main d'œuvre carrosserie / tôlerie |
| **8** | Main d'œuvre mécanique |
| **12** | Main d'œuvre peinture |
| **28** | Main d'œuvre électrique |

Structured evidence stays authoritative, and the fail-closed rules are
unchanged: a recognised structured family wins; a non-empty structured
value that is not recognised fails closed and can never be reinterpreted
by free text; contradictory structured fields fail closed; only genuinely
absent structured fields let the strict text classifier run.

Generic `"réparation"` is not evidence of carrosserie. A part merely
*named* "moteur" or "batterie électrique" does not become labour.

---

## Dedicated exceptions

Each needs its own explicit semantic signal — none is reachable through
the ordinary-piece path.

| Rubrique | Signal |
|---|---|
| **16** | Paint **materials/ingredients** — not a painted part |
| **17** | Passage au marbre (an operation, not a fifth labour family) |
| **18** | Parallélisme / équilibrage / géométrie (an operation, not a sixth) |
| **19–20** | Vitre + réparation / remplacement |
| **21–22** | Pare-brise + réparation / remplacement |
| **23–24** | Lunette arrière + réparation / remplacement |
| **25** | Colle |
| **26** | Kit colle pare-brise / lunette arrière |
| **27** | Kit colle vitre |

Glass requires a component **and** an operation. Operation evidence
includes Wexia's `repair_action` (added in C.2.2). `part_type` means
origin and is never read as a glass operation. Contradictory evidence —
`operation_type=reparation` with `repair_action=remplacement` — stays
ambiguous.

---

## Never produced automatically

```
4, 5, 6      10, 11      13, 14, 15
```

These exist in the catalog and must not be inferred from an ordinary
piece's keywords. **9** is an aggregate total and is not a line target in
any workflow.

An explicit `mcma_rubric_id` does not change this. It is reconciled
against the semantic result and a disagreement fails closed, so
`moteur + original + mcma_rubric_id=4` is a contradiction rather than an
instruction. An exception rubrique is accepted only where the semantics
independently reach it.

---

## Enforcement

`build_mission_normal_plan()` checks every emitted row against
`MODE_NORMAL_ALLOWED_RUBRIQUES` and raises `PlanBuildError` if any falls
outside it.

This is a **backstop, not a fix** — the classifiers already produce only
allowed rubriques. It exists because the old mistake is easy to
reintroduce one plausible-looking keyword at a time, and a row outside
the policy means a classifier is producing something the agency's rule has
no place for. That is a defect in this system rather than a question
about the dossier, so it fails closed instead of becoming a review item.

**Mode Normal only.** Garage Conventionné maps against pre-existing
portal rows and is deliberately untouched by this policy.
