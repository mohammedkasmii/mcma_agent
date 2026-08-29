# BUSINESS RULES

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

This document separates **(A) rules verified in the current code**, **(B) resolved requirements** (authoritative decisions supplied during Phase 2 approval — these govern intended behaviour even where the code currently diverges), and **(C) inferences / domain questions**. Where current code contradicts a resolved requirement, that contradiction is recorded here and in `KNOWN_FAILURES.md`. This phase does **not** design the new architecture.

---

## A. Rubrique catalog (verified — `core/constants.py:13-42`)

The canonical catalog has 28 entries. Parts belong to Fournitures Carrosserie, classified by origin; specialized families and special rubriques exist alongside.

- **Carrosserie fournitures by origin:** `1` ORIGINES · `2` ADAPTABLES · `3` TOTAL PIECES OCCASIONS / RECUPERABLES.
- **Mécanique fournitures:** `4` origines · `5` adaptables · `6` récupérables.
- **Peinture fournitures:** `10` origines · `11` adaptables · `16` PEINTURES ET INGREDIENTS.
- **Électrique fournitures:** `13` origine · `14` adaptables · `15` récupérables.
- **Special / labour rubriques:** `7` MAIN D'OEUVRE CARROSSERIE · `8` MAIN D'OEUVRE MECANIQUE · `12` MAIN D'OEUVRE PEINTURE · `28` MAIN D'OEUVRE ELECTRIQUE · `17` PASSAGE AU MARBRE · `18` PARALLELISME ET EQUILIBRAGE · `9` MONTANT TOTAL.
- **Glass rubriques:** `19` REPARATION VITRE · `20` REMPLACEMENT VITRE · `21` REPARATION PARE-BRISE · `22` REMPLACEMENT PARE-BRISE · `23` REPARATION LUNETTE ARRIERE · `24` REMPLACEMENT LUNETTE ARRIERE.
- **Colle / kits:** `25` COLLE · `26` KIT COLLE PARE-BRISE ET LUNETTE ARRIERE · `27` KIT COLLE VITRE.

## A.1 Part origin classification (verified)

- Origin aliases (`core/constants.py:47-49`): ORIGINAL = {original, origine, oem, neuf, neuve, new}; ADAPTABLE = {adaptable, equivalent, aftermarket}; RECOVERED = {recuperation, recuperable, occasion, used}.
- Family × origin → rubrique via `SYSTEM_RUBRIQUE_MATRIX` (`:54-67`).
- **Unknown/missing `part_type` fails closed** (`wexia_mapper.py:534-536`, raises) — proven by `test_mapper.py:296`.
- **Unknown labour type fails closed** (`wexia_mapper.py:512-514`, raises) — proven by `test_mapper.py:318`. *(Caveat: the labour catch-all list includes the 2-letter token `"mo"` (`:508`), so descriptions merely containing the letters "mo" collapse to rubrique 7 — see `KNOWN_FAILURES.md`.)*

## A.2 Colle / adhesive (verified — `wexia_mapper.py:483-492`)

`colle`/`mastic` present → if `kit` and `vitre` ⇒ `27`; else if `kit` ⇒ `26`; else ⇒ `25`. Proven by `test_mapper.py:238`.

## A.3 Monetary calculation (verified)

- **Decimal only** in the mapper: `to_decimal`, `quantize_money(ROUND_HALF_UP)`, `format_money` (`wexia_mapper.py:109-125`); `DEFAULT_TVA_RATE = Decimal("0.20")`, `CENT = Decimal("0.01")` (`core/constants.py:186-187`).
- **Tax remainder allocation:** per-line TVA = `HT × 0.20` except the last line of a group, which takes `target_tva − running_tva`, so `Σ Taxe` equals the chiffrage tax exactly (`wexia_mapper.py:638-664`); enforced by ±0.01 assertions (`:671-676`). Proven by `test_mapper.py:273`.
- **Vétusté rate** = `vétusté / TTC × 100` (`:663`), consistent with the portal's `CalculerTauxVetusteValide()` *(inference from `GARAGE_CONVENTIONNE_ANALYSIS.md:132`; `mock_server.py:583`)*.
- Floats appear only once values cross into portal JS (`mock_server.py:571-583`) — inherent to driving the browser, not a mapper defect.
- **Latent issue:** per-line TVA (`:646`) is unguarded and can go negative if earlier rounding overshoots the target — a negative `Taxe` could be written. See `KNOWN_FAILURES.md`.

---

## B. Resolved requirements (authoritative — govern intended behaviour)

### B.1 Glass mappings

Glass-related operations **must use their dedicated rubriques** when applicable:
- **Rubrique 20 — REMPLACEMENT VITRE**
- **Rubrique 22 — REMPLACEMENT PARE-BRISE**

Rules:
- Recognized glass operations **must not be silently folded into rubrique 1**.
- Remaining glass categories (`19` réparation vitre, `21` réparation pare-brise, `23` réparation lunette arrière, `24` remplacement lunette arrière) require **explicit domain mapping** before use — document them as pending, do not auto-map.
- **Unknown glass mappings must fail closed** (needs-review or blocked; never a silent default).

**Current-code status (contradiction to record):** the mapper has **no producer** for glass rubriques 19-24. A `pare-brise`/`vitre` part line falls through `_determine_part_rubrique` (`wexia_mapper.py:517-551`) to `family = carrosserie` ⇒ **rubrique 1** (demonstrated by `test_mapper.py:68`, where a pare-brise amount is aggregated into rubrique 1). The alias table does list `20`/`22` (`core/constants.py:170,172`) but only the garage-conventionné label matcher consumes aliases; the Wexia mapper never emits 20/22. This diverges from B.1 and is logged in `KNOWN_FAILURES.md` as a required correction (no code change in this phase).

### B.2 Charge mutuelle

- **Do not force `MontantChargeSocietaire` to zero.**
- **Do not overwrite charge-mutuelle values with an invented formula.**
- Preserve the portal's **native calculated values** unless an explicitly verified business rule authorizes a change.
- If the correct distribution cannot be established, **require human review and perform no overwrite.**

**Current-code status (contradiction to record):** `browser/mode_normal.py:122-144` sets `MontantChargeMutuelle = MontantReparation` and `MontantChargeSocietaire = '0'` after triggering native calculation — overwriting the portal split and zeroing the insured's share (franchise / vétusté / part-responsabilité). This directly violates B.2 and is logged in `KNOWN_FAILURES.md`. (`browser/mode_conventionne.py` does **not** do this; it relies on native `DevisCalculerMontantCharge()` at `:354-387` — so the two modes currently disagree on money semantics.)

### B.3 Out-of-catalogue rubrique identifiers

- An out-of-catalogue `mcma_rubric_id` **must fail closed** — return a needs-review or blocked mapping result. **Do not infer or substitute a rubrique silently.**

**Current-code status (contradiction to record):** `wexia_mapper.py:578` (`if explicit_rub and explicit_rub in RUBRIQUE_CATALOG:`) accepts an in-catalog id but, for an out-of-catalog id, **silently falls through to heuristic inference** rather than failing closed. The matrix `.get(...)` default at `:550` is a second latent fail-open. Both violate B.3 and are logged in `KNOWN_FAILURES.md`.

### B.4 Mission identity (safety-critical business rule)

Before any write-capable operation the system must: search by available identifiers; require exactly one unique match; stop on zero or multiple matches; never select the first row as a fallback; open the candidate; verify registration, insurer reference and every other available identifier; and stop if verification is incomplete or contradictory. Partial matches must never proceed to writes. **Current code does not meet this** (see `SAFETY_INVARIANTS.md` and `KNOWN_FAILURES.md`).

### B.5 Multi-account (Oujda / Nador)

Oujda and Nador are **account profiles / notification scopes used from the same office**, not separate city deployments. Multi-account support must be **extensible** (no hardcoded count of four) and is **deferred until after the core safety work** (production-domain test blocking, read/write separation, mission-identity verification, fail-closed interception, mapping enforcement). Design belongs to the architecture phase, not this one.

---

## C. Inferences / open domain questions

- **Glass rubriques 19, 21, 23, 24** need an authoritative operation→rubrique mapping from the business before they can be produced (per B.1, they stay pending / fail-closed).
- **Correct charge-mutuelle distribution:** `GARAGE_CONVENTIONNE_ANALYSIS.md:146-151` states `Charge Sociétaire = (Franchise × PartResponsabilité/100) + Vétusté [+ TVA if récupérable]` and `Charge Mutuelle = Réparation − Sociétaire − Remise`. This is documentation, not verified portal behaviour; per B.2 the **native portal values** are authoritative unless this formula is explicitly verified. See `OPEN_QUESTIONS.md`.
- **`charge mutuelle` must not be forced/overwritten** — reaffirmed by B.2.
