# BUSINESS RULES

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

This document separates **(A) rules verified in the current code**, **(B) authoritative decisions** (supplied at Phase 1 approval and amended at Phase 2 — these govern intended behaviour even where the code currently diverges), and **(C) residual inferences / domain questions**. Where current code contradicts an authoritative decision, that contradiction is recorded here and in `KNOWN_FAILURES.md`. This phase does **not** design the new architecture; decisions that concern data model or security are recorded here and in `OPEN_QUESTIONS.md` but implemented only in later phases.

**Amendment note:** Section B reflects the Phase 2 amendment decisions (three-origin rule, glass terminology, charge mutuelle, mission identity, negative TVA, labour detection, persistence, LAN security). These supersede any earlier wording.

---

## A. Rubrique catalog (verified — `core/constants.py:13-42`)

28 entries. Ordinary parts belong to Fournitures Carrosserie, classified by origin; specialized families and special rubriques exist alongside.

- **Carrosserie fournitures by origin:** `1` ORIGINES · `2` ADAPTABLES · `3` TOTAL PIECES OCCASIONS / RECUPERABLES.
- **Mécanique fournitures:** `4` origines · `5` adaptables · `6` récupérables.
- **Peinture fournitures:** `10` origines · `11` adaptables · `16` PEINTURES ET INGREDIENTS.
- **Électrique fournitures:** `13` origine · `14` adaptables · `15` récupérables.
- **Special / labour:** `7` M.O. CARROSSERIE · `8` M.O. MECANIQUE · `12` M.O. PEINTURE · `28` M.O. ELECTRIQUE · `17` PASSAGE AU MARBRE · `18` PARALLELISME ET EQUILIBRAGE · `9` MONTANT TOTAL.
- **Glass:** `19` REPARATION VITRE · `20` REMPLACEMENT VITRE · `21` REPARATION PARE-BRISE · `22` REMPLACEMENT PARE-BRISE · `23` REPARATION LUNETTE ARRIERE · `24` REMPLACEMENT LUNETTE ARRIERE.
- **Colle / kits:** `25` COLLE · `26` KIT COLLE PARE-BRISE ET LUNETTE ARRIERE · `27` KIT COLLE VITRE.

## A.1 Origin aliases (verified — `core/constants.py:47-49`)

ORIGINAL = {original, origine, oem, neuf, neuve, new}; ADAPTABLE = {adaptable, equivalent, aftermarket}; RECOVERED = {recuperation, recuperable, occasion, used}.

## A.2 Fail-closed points already in code (verified)

- Unknown/missing `part_type` raises (`wexia_mapper.py:534-536`; `test_mapper.py:296`).
- Unknown labour type raises (`wexia_mapper.py:512-514`; `test_mapper.py:318`).
- Colle/kit classification (`wexia_mapper.py:483-492`; `test_mapper.py:238`).
- Decimal money + tax remainder allocation (`wexia_mapper.py:109-125,638-664`; ±0.01 assertions `:671-676`; `test_mapper.py:273`).

*(Note: several of these are narrower or looser than the decisions in section B — see the contradictions flagged there and in `KNOWN_FAILURES.md`.)*

---

## B. Authoritative decisions

### B.1 Three-origin rule for ordinary parts

Every **ordinary part** maps **only by origin**:

| Origin signal | Rubrique |
|---|---|
| original / OEM / new (`is_original=true`) | **1** |
| adaptable / equivalent / aftermarket | **2** |
| recovered / occasion / used | **3** |

- **Do not infer rubriques 4–6 (mécanique) or 13–15 (électrique) from part-description keywords** unless a future explicit business rule authorizes it.
- The origin signal is `part_type` (and/or `is_original`). `part_type` means **origin**, nothing else (see B.2).

**Dedicated exceptions** (these are NOT ordinary parts and keep their own rubriques): glass `19–24` (B.2); colle/kits `25–27`; peinture et ingrédients `16`; labour `7`, `8`, `12`, `28`; marbre `17`; parallélisme/équilibrage `18`.

**Current-code contradiction:** `_determine_part_rubrique` infers `family = mecanique/electrique` from item-name keywords and maps to 4–6 / 13–15 via `SYSTEM_RUBRIQUE_MATRIX` (`wexia_mapper.py:541-544,550`). Under B.1 this keyword-based family inference is **disallowed** for ordinary parts. Recorded as F33 in `KNOWN_FAILURES.md`. (Rubriques 10/11 peinture-fournitures are likewise not to be produced by keyword inference; painting maps to `16` or labour `12`.)

### B.2 Glass mapping and terminology

- **Do not use `part_type` to denote a glass family** — `part_type` already means origin (B.1).
- Glass mapping uses **(a) normalized component identity/description** and **(b) explicit operation type**, independent of `part_type`.

Supplied mapping for rubriques 19–24 (component identity × operation type):

| Component identity | Réparation | Remplacement |
|---|---|---|
| vitre | **19** REPARATION VITRE | **20** REMPLACEMENT VITRE |
| pare-brise | **21** REPARATION PARE-BRISE | **22** REMPLACEMENT PARE-BRISE |
| lunette arrière | **23** REPARATION LUNETTE ARRIERE | **24** REMPLACEMENT LUNETTE ARRIERE |

- **Conflicting repair/replacement signals, or ambiguous glass descriptions, must fail closed** (needs-review/blocked; never a silent default and never rubrique 1).

**Current-code contradiction:** no producer for 19–24 exists; glass part lines fall through to rubrique 1 (`wexia_mapper.py:517-551`; `test_mapper.py:68`). Recorded as F13 in `KNOWN_FAILURES.md`.

### B.3 Charge mutuelle / Native Financial Calculation

- The **portal-native calculation is always authoritative in both workflows** (Mode Normal and Garage Conventionné).
- **Native triggering AND verification are mandatory in both workflows.** The resulting financial summary must be verified before the state transitions to `READY_FOR_HUMAN_REVIEW`.
- **Neither workflow may write `MontantChargeSocietaire` or `MontantChargeMutuelle`.**
- For detailed workflow separation and mandatory financial verification steps, refer to `docs/architecture/PORTAL_ROW_WORKFLOWS.md`.

**Current-code contradiction:** `browser/mode_normal.py:122-144` writes both fields (`MontantChargeMutuelle = MontantReparation`, `MontantChargeSocietaire = '0'`). This is prohibited under B.3. `mode_conventionne` already defers to native calc and writes neither. Recorded as F6 in `KNOWN_FAILURES.md`.

### B.4 Out-of-catalogue rubrique identifiers

An out-of-catalogue `mcma_rubric_id` **must fail closed** — return needs-review/blocked; never infer or substitute silently.

**Current-code contradiction:** `wexia_mapper.py:578` accepts only in-catalog ids and otherwise falls through to inference; the matrix `.get` default at `:550` is a second fail-open. Recorded as F14 in `KNOWN_FAILURES.md`.

### B.5 Mission identity — strict two-tier gate

Authorize a write only when **both tiers agree**:

1. **Tier 1 (primary key):** exact **insurer reference** OR exact **`idSinistre`**.
2. **Tier 2 (independent cross-check):** **normalized registration** (`core/utils.py:50` `normalize_registration`, currently unused).

Rules:
- **All supplied identifiers must agree.** A registration plate **alone is insufficient** to authorize writes.
- **Search must yield exactly one candidate.** Zero matches → fail closed; multiple matches → fail closed; never first-row/sole-candidate fallback.
- **After opening**, compare **all** expected identifiers against the opened mission. Missing, contradictory, zero-match or multiple-match → **fail closed**.

**Current-code contradiction:** selection uses an unanchored substring on a lossy digit-run key with first-row/sole-candidate fallback (`mission_navigator.py:76-105`), and post-open "verification" returns True without comparing (`:116-128`). Recorded as F3/F4/F5 in `KNOWN_FAILURES.md`.

### B.6 Negative TVA

- **No line may have negative TVA. Do not silently clamp** a negative TVA line.
- If the initial remainder allocation would produce a negative line, either:
  - perform a **deterministic non-negative redistribution** that preserves exact TVA and TTC totals to **0.01 MAD**; or
  - **fail closed.**
- **For the initial implementation, prefer failing closed** with the sentinel: `NEEDS_REVIEW: INVALID_TAX_ALLOCATION`.
- **No discrepancy tolerance of 0.05 MAD is permitted** (the exactness bound is 0.01 MAD).

**Current-code contradiction:** per-line TVA at `wexia_mapper.py:646` is unguarded and can go negative with no fail-closed path. Recorded as F17 in `KNOWN_FAILURES.md`.

### B.7 Labour detection

- **Remove unrestricted substring matching for `mo`.**
- Use **structured `item_type` / `operation_type` first**. When the input explicitly marks a line as labour, classify it as labour.
- Only **explicit labour expressions** may classify an ambiguous line as labour. **Generic family words alone (peinture, mécanique, électrique) are not sufficient.**
- **Ambiguous classification fails closed** (`NEEDS_REVIEW`).

**Vocabulary examples** (to carry into `docs/architecture` test strategy and property tests in later phases):

- **Positive — explicit labour (classify as labour when `item_type`/`operation_type` indicates labour, or these appear as the operation):** `main d'oeuvre`, `main d oeuvre`, `MO carrosserie`, `MO tôlerie`, `MO mécanique`, `MO peinture`, `MO électrique`, `forfait main d'oeuvre`, `heures de main d'oeuvre`, and operation verbs on a labour line: `montage`, `démontage`, `pose`, `dépose`, `débosselage`, `redressage`.
  - Sub-routing of a labour line: carrosserie/tôlerie → `7`; mécanique → `8`; peinture → `12`; électrique → `28`; marbre → `17`; parallélisme/équilibrage → `18`.
- **Negative — must NOT alone trigger labour:** the bare tokens `peinture`, `mécanique`, `électrique`; any word merely containing the letters "mo" as a substring (`moteur`, `module`, `commande`, `amovible`, `modification`, and `démontage` when it is part of a *part* description rather than a labour operation).

**Current-code contradiction:** `_determine_labour_rubrique` (`wexia_mapper.py:494-514`) substring-tests the 2-letter `"mo"` (`:508`) and treats generic family words as sufficient. Recorded as F15 in `KNOWN_FAILURES.md`.

### B.8 Multi-account (Oujda / Nador)

Account profiles / notification scopes from **one office**, not city deployments. Support must be **extensible** (no hardcoded count of four) and is **deferred until after core safety work**. Persistence identity for a claim is defined in B.9. (Design belongs to the architecture phase.)

### B.9 Persistence identity (data decision — implemented in a later phase)

- Use **SQLite (WAL)** for durable state. **Do not identify claims by category.**
- Stable per-account claim identity is the portal **`idSinistre`**: `UNIQUE(account_id, portal_claim_id)`.
- Model **category membership / presence separately**, so a claim moving between categories does **not** become a duplicate.
- An **absence transition** (claim no longer present in a category) is valid **only after a complete, successful category poll under a valid account session**.
- Keep **monotonic state versions** for delta recovery; use **SSE** for immediate dashboard notification.

*(Recorded as an authoritative target. Not present on this branch — see `SYSTEM_OVERVIEW.md` §6. Detailed data model is out of scope for Phase 2.)*

### B.10 LAN security (security decision — implemented in a later phase)

- A **localStorage employee name is not authentication** and must not populate the authoritative audit actor.
- Require **server-side employee authentication**, **secure session cookies**, **CSRF protection**, **role authorization**, and **server-derived audit identity**.
- **IP/subnet restriction is defense-in-depth only.** The allowed office subnet must be **configurable**; **do not hardcode `192.168.1.0/24`**.
- **Separate notification-view permission from automation-job permission.**
- **Automation jobs execute asynchronously under a per-account lock.**

*(Cross-referenced in `SAFETY_INVARIANTS.md` INV-11. Not present on this branch.)*

---

## C. Residual inferences / domain questions

- **Glass component-identity vocabulary:** the exact normalized tokens for `vitre` / `pare-brise` / `lunette arrière` and for operation type (`réparation` vs `remplacement`) still need enumeration for implementation (see `OPEN_QUESTIONS.md` Q1).
- **Peinture parts vs ingredients:** whether any painting *part* should ever map to `10`/`11` rather than the `16` exception (current decision routes painting to `16`/`12`); confirm in `OPEN_QUESTIONS.md`.
- All earlier money/mission/charge/labour questions are now **resolved** by section B; see `OPEN_QUESTIONS.md` §1 for the resolution record.
