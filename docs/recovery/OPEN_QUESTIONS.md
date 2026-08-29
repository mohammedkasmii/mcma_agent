# OPEN QUESTIONS

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

Two parts: **(1) Resolved** during Phase 2 approval (recorded here for traceability; authoritative text lives in `BUSINESS_RULES.md`), and **(2) Still open** — genuinely unresolved items that need a decision before or during later phases. Architecture design is out of scope for this phase.

---

## 1. Resolved during Phase 2 approval

| # | Question | Resolution (authoritative) |
|---|---|---|
| R1 | Glass mappings | Use dedicated rubriques **20 (REMPLACEMENT VITRE)** and **22 (REMPLACEMENT PARE-BRISE)**; never silently fold recognized glass into rubrique 1; remaining glass categories need explicit domain mapping; unknown glass **fails closed**. (`BUSINESS_RULES.md` B.1) |
| R2 | Charge mutuelle | Do **not** force `MontantChargeSocietaire` to 0; do **not** overwrite with an invented formula; preserve native portal values unless a verified rule authorizes a change; otherwise require human review and do not overwrite. (`BUSINESS_RULES.md` B.2) |
| R3 | Out-of-catalogue `mcma_rubric_id` | **Fail closed** — return needs-review/blocked; never infer/substitute silently. (`BUSINESS_RULES.md` B.3) |
| R4 | Multi-account (Oujda/Nador) | Account profiles / notification scopes from one office, not city deployments. Support must be **extensible** (no hardcoded four); implement only **after** core safety work. (`BUSINESS_RULES.md` B.5) |
| R5 | Other-branch lead | An unverified cross-branch lead raised during Phase 1 is **excluded** from recovery documentation — out of approved scope. This branch (`refactor/solid-architecture`) is the only source of truth; no other branch was inspected. |
| R6 | Phase 1 plan file | Path reported and confirmed documentation-only in `BASELINE.md` §6. |

---

## 2. Still genuinely unresolved

### Q1 — Remaining glass categories (rubriques 19, 21, 23, 24)
R1 fixes replacement of vitre (20) and pare-brise (22). The mapping for **réparation vitre (19)**, **réparation pare-brise (21)**, **réparation lunette arrière (23)** and **remplacement lunette arrière (24)** is not yet defined. Per R1 these remain **pending / fail-closed** until the business supplies an authoritative operation→rubrique mapping. **Decision needed:** the exact input signals (item names / operation codes) that map to each.

### Q2 — Authoritative charge-mutuelle distribution
R2 says preserve native values unless a rule is verified. `GARAGE_CONVENTIONNE_ANALYSIS.md:146-151` proposes `Charge Sociétaire = (Franchise × PartResponsabilité/100) + Vétusté [+ TVA if récupérable]` and `Charge Mutuelle = Réparation − Sociétaire − Remise`, but this is documentation, not verified portal behaviour. **Decision needed:** confirm whether the portal's native calculation is always authoritative, or whether/when this formula may override it — otherwise the path stays "human review, no overwrite".

### Q3 — Should the two fill modes share money semantics?
`mode_normal` forces charge-mutuelle (to be removed per R2) while `mode_conventionne` relies on native calc. **Decision needed:** confirm both modes must defer to native portal calculation, and whether Mode Normal has any legitimate charge-mutuelle write at all.

### Q4 — Search-key strategy for mission identity
The current lossy digit-run key (`core/utils.py:59-70`) cannot distinguish plates sharing a digit run. **Decision needed:** which identifiers (full normalized registration, insurer reference, internal sinistre/mission ids) constitute a unique match, and the exact rule for "exactly one" — input for the mission-identity gate (`BUSINESS_RULES.md` B.4).

### Q5 — Negative-TVA policy
Per-line TVA can go negative under remainder allocation (`wexia_mapper.py:646`). **Decision needed:** clamp to zero, redistribute, or fail closed to human review?

### Q6 — Labour `"mo"` token
The 2-letter `"mo"` labour token (`wexia_mapper.py:508`) over-matches. **Decision needed:** the precise labour-detection vocabulary so unrelated descriptions do not collapse to rubrique 7.

### Q7 — Notification/employee-action persistence model
Employee notes/status and the notification cache currently live in `logs/*.json` with non-atomic rewrites and no history. **Decision needed** (architecture phase): the intended durable store and whether notification presence/lifecycle history must be retained. *(Recorded as a question only; not designed here.)*

### Q8 — API exposure model on the office LAN
The API is currently unauthenticated on `0.0.0.0:8000`. **Decision needed** (architecture phase): the intended authentication/authorization and network-exposure model, and whether the auth-launch/fill-dossier powers should be reachable over the LAN at all.
