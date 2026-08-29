# OPEN QUESTIONS

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

Two parts: **(1) Resolved** by authoritative decisions (Phase 1 approval + Phase 2 amendments; authoritative text lives in `BUSINESS_RULES.md`), and **(2) Still open** — genuinely unresolved items needing a decision later. Architecture design is out of scope for this phase.

---

## 1. Resolved (authoritative — recorded for traceability)

| # | Topic | Resolution |
|---|---|---|
| R1 | Three-origin rule | Ordinary parts map only by origin: original/OEM/new→**1**, adaptable/equivalent/aftermarket→**2**, recovered/occasion/used→**3**. No keyword inference of 4–6 or 13–15 without a future explicit rule. Dedicated exceptions: glass 19–24, colle/kits 25–27, peinture-et-ingrédients 16, labour 7/8/12/28, marbre 17, parallélisme/équilibrage 18. (`BUSINESS_RULES.md` B.1) |
| R2 | Glass terminology & mapping | `part_type` = origin only; glass uses normalized component identity + explicit operation type. Supplied 19–24 mapping applied (vitre/pare-brise/lunette × réparation/remplacement). Conflicting/ambiguous glass **fails closed**; never rubrique 1. (`BUSINESS_RULES.md` B.2) |
| R3 | Charge mutuelle | Portal-native calculation authoritative in **both** modes; neither mode may write `MontantChargeSocietaire`/`MontantChargeMutuelle`; independent of final save; final save stays blocked/human. (`BUSINESS_RULES.md` B.3) |
| R4 | Out-of-catalogue `mcma_rubric_id` | **Fail closed** (needs-review/blocked); never infer/substitute. (`BUSINESS_RULES.md` B.4) |
| R5 | Mission identity | Strict two-tier gate: Tier 1 exact insurer reference or exact `idSinistre`; Tier 2 normalized registration cross-check; all identifiers must agree; plate alone insufficient; exactly one candidate; compare all after opening; zero/multiple/missing/contradictory → fail closed. (`BUSINESS_RULES.md` B.5) |
| R6 | Negative TVA | No negative-TVA line; no silent clamp; deterministic non-negative redistribution preserving TVA/TTC to 0.01 MAD, **or** fail closed. Initial implementation: fail closed with `NEEDS_REVIEW: INVALID_TAX_ALLOCATION`. No 0.05 MAD tolerance. (`BUSINESS_RULES.md` B.6) |
| R7 | Labour detection | Remove unrestricted `mo` substring; use structured `item_type`/`operation_type` first; only explicit labour expressions classify an ambiguous line as labour; generic peinture/mécanique/électrique alone insufficient; ambiguous fails closed. Positive/negative vocabulary recorded. (`BUSINESS_RULES.md` B.7) |
| R8 | Persistence identity | SQLite WAL; claims identified by portal `idSinistre` with `UNIQUE(account_id, portal_claim_id)`, never by category; category membership modelled separately; absence transitions valid only after a complete successful category poll under a valid session; monotonic state versions for delta recovery; SSE for dashboard notification. (`BUSINESS_RULES.md` B.9) |
| R9 | LAN security | Server-side employee auth, secure session cookies, CSRF, role authorization, server-derived audit identity; localStorage name is not auth; IP/subnet is defense-in-depth only with a configurable office subnet (no hardcoded `192.168.1.0/24`); notification-view permission separated from automation-job permission; automation jobs async under a per-account lock. (`BUSINESS_RULES.md` B.10, `SAFETY_INVARIANTS.md` INV-11) |
| R10 | Multi-account (Oujda/Nador) | Account profiles/notification scopes from one office; extensible (no hardcoded four); deferred until after core safety. (`BUSINESS_RULES.md` B.8) |
| R11 | Final-endpoint invariant | Reclassified from "HOLDS (with caveats)" to **PARTIALLY HOLDS / NOT A PERMANENT GUARANTEE**. (`SAFETY_INVARIANTS.md` INV-4) |
| R12 | Canonical mission route | `/expertise/frontexpert/` is canonical; current code uses the case variant `expertise/FrontExpert/`. (`PORTAL_CONTRACT.md`, `SYSTEM_OVERVIEW.md`, `WORKFLOW_CATALOG.md`) |
| R13 | Phase 1 plan file | Path reported, documentation-only confirmed. (`BASELINE.md` §6) |
| R14 | Cross-branch lead | Excluded — unverified, out of scope; this branch is the only source of truth. |

---

## 2. Still genuinely unresolved

### Q1 — Glass component-identity & operation vocabulary
The 19–24 mapping is decided (R2), but the exact **normalized token lists** that identify each component (`vitre`, `pare-brise`, `lunette arrière` — and any synonyms/accents) and each **operation type** (`réparation` vs `remplacement`, and their aliases) still need enumeration for implementation. **Decision needed:** the authoritative token/synonym lists and which input field carries the operation type.

### Q2 — Painting parts vs ingredients
Current decision routes painting to `16` (ingredients) or labour `12`. **Decision needed:** confirm no painting *part* should ever map to peinture-fournitures `10`/`11`, or define the signal that would.

### Q3 — Labour `operation_type` source field
R7 requires "structured `item_type` / `operation_type` first". **Decision needed:** confirm the exact input-schema field names/values that mark a line as labour (and, where present, its labour sub-family), so detection does not fall back to text heuristics.

### Q4 — Redistribution vs fail-closed for tax allocation (post-initial)
R6 sets the initial behaviour to fail closed. **Decision needed (later):** whether/when to enable the deterministic non-negative redistribution alternative, and its exact algorithm, once characterization tests exist.

### Q5 — Account onboarding / identity source
R8/R10 define per-account claim identity and extensible multi-account, but not **how an `account_id` is provisioned** or how a saved session is bound to a specific account. **Decision needed (architecture phase):** the account registry and session→account binding.

*(All items in this section are questions only; none are designed or implemented in Phase 2.)*
