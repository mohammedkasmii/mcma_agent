# SAFETY INVARIANTS

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

The safety invariants the system **must** uphold, each with its status on this baseline (**HOLDS** / **PARTIALLY HOLDS** / **VIOLATED**) and `file:line` evidence. Invariant text reflects the Phase 2 amendment decisions (`BUSINESS_RULES.md` §B).

---

## 0. Overall safety classification (authoritative)

> **This branch is a functional recovery baseline but is NOT production-safe for form filling.**
>
> - **Live form-filling (mission writes) is PROHIBITED** until the invariants marked VIOLATED / PARTIALLY HOLDS below are fixed and covered by tests.
> - **"Preview", "dry-run" and "safety/test mode" are UNSAFE in the current implementation** — they do not prevent row-level writes to the portal.
> - The 19 passing tests do **not** prove mission safety, preview safety, browser-write safety or API security.

---

## INV-1 — Dry-run / preview must be technically incapable of writes — **VIOLATED**

A boolean such as `if preview: don't click` is insufficient while the session retains write-capable network access.

- `TEST_MODE` is a single module constant, hardcoded `True`, no env override (`core/config.py:19`).
- `fill_garage_conventionne(..., test_mode=True, ...)` uses `test_mode` **only in an f-string label** (`browser/mode_conventionne.py:402`); there is **no `if test_mode` guard**. `fill_mode_normal` has **no safety parameter at all** (`browser/mode_normal.py:19`).
- The only technical control is the network interceptor — which has the gap in INV-3. **Result: preview/dry-run writes rows.**

## INV-2 — Mission identity must be verified before any write (strict two-tier gate) — **VIOLATED**

Required (`BUSINESS_RULES.md` B.5): Tier 1 = exact insurer reference **or** exact `idSinistre`; Tier 2 = normalized registration as an independent cross-check; all supplied identifiers must agree; a plate alone is insufficient; search must yield exactly one candidate; after opening, compare all expected identifiers; missing / contradictory / zero-match / multiple-match → fail closed.

- Current selection uses an unanchored substring on a lossy digit-run key with first-row/sole-candidate fallback (`mission_navigator.py:76-105`).
- Post-open "verification" reads and prints identifiers, then `return True` **unconditionally** — no comparison; `normalize_registration` (`core/utils.py:50`) is never called (`:116-128`).
- **Result: the agent can open and write to the wrong mission.**

## INV-3 — Network interception must be default-deny and fail-closed for write endpoints — **VIOLATED**

- The block list (`browser/safety_interceptor.py:10-22`) is **allow-by-omission**, not default-deny, and **omits the two endpoints the automation actively triggers**: `updateDevisDet` (`mode_conventionne.py:288`) and `createRapportDefDet` (`mock_server.py:668`). It also lists a phantom `createDevisDet` (`:12`).
- Blocked requests **fail open**: fulfilled with `status=200, body='{"state":"success",...}'` (`:35-39`), so read-back verification reports success for writes that never happened.
- Routes bind to `page`, not `context` (`:25,42`) — popups/new tabs are unrouted.

## INV-4 — Final / irreversible endpoints must remain blocked — **PARTIALLY HOLDS / NOT A PERMANENT GUARANTEE**

- Currently blocked at the network layer: `garageModifierValDevis`, `validerDevis`, `expertEnregistrerMission`, `enregistrerMission`, `expertCloturerMission`, `cloturerMission`, `cloturerTraitement`, `ajouterDocument`, `deleteDocument` (`safety_interceptor.py:11-21`); final buttons are not clicked (`#Enregistrer` never referenced; `#DEVISDET_Btn` only logged, `mode_conventionne.py:456-458`).
- **Why this is not a permanent guarantee:** the block **fails open** (INV-3), is **page-scoped** (INV-3), and the entire guarantee rests on a single hardcoded `TEST_MODE=True` (INV-1). A single flag flip, popup, new tab, or endpoint-name variant removes the protection. Final save must remain **blocked and human-controlled** by design, not by an omission-list plus a boolean.

## INV-5 — Human final validation must remain mandatory — **HOLDS**

- `process_workflow` calls `page.pause()` for human review (`main.py:236-244`); no code performs a final save/validation/clôture. *(Caveat: the pause runs **after** row writes, and `page.pause()` inside an HTTP handler blocks the request — see `KNOWN_FAILURES.md` F25.)*

## INV-6 — Mapping must fail closed and follow the three-origin rule — **VIOLATED / PARTIALLY VIOLATED**

Required (`BUSINESS_RULES.md` B.1–B.4): ordinary parts map only by origin (1/2/3); no keyword inference of 4–6 / 13–15; glass uses component identity × operation (19–24) and fails closed on ambiguity; out-of-catalogue `mcma_rubric_id` fails closed.

- Holds: unknown `part_type` (`wexia_mapper.py:534-536`) and unknown labour (`:512-514`) raise.
- Violated: keyword-based family inference to 4–6 / 13–15 (`:541-544,550`); glass folded into rubrique 1 (no 19–24 producer); out-of-catalogue `mcma_rubric_id` inferred not failed (`:578`); matrix `.get` default (`:550`). See `KNOWN_FAILURES.md` F13, F14, F33.

## INV-7 — Monetary values must use Decimal, with no negative TVA — **PARTIALLY HOLDS**

- Decimal + `ROUND_HALF_UP` + remainder allocation in the mapper (`wexia_mapper.py:109-125,638-664`); exactness bound **0.01 MAD** (`:671-676`).
- **Required (`BUSINESS_RULES.md` B.6):** no line may have negative TVA; do not silently clamp; either deterministic non-negative redistribution preserving TVA/TTC to 0.01 MAD, or fail closed with `NEEDS_REVIEW: INVALID_TAX_ALLOCATION`; **no 0.05 MAD tolerance**.
- Current code: per-line TVA at `:646` is unguarded and can go negative with no fail-closed path — **violates B.6**. See `KNOWN_FAILURES.md` F17.

## INV-8 — Charge mutuelle: native calculation authoritative; agent must not write it — **VIOLATED (Mode Normal) / PARTIALLY HOLDS (PEC)**

Required (`BUSINESS_RULES.md` B.3): the portal-native calculation is authoritative in **both** workflows; **neither workflow may write `MontantChargeSocietaire` or `MontantChargeMutuelle`**. Native triggering AND verification are mandatory in both workflows (refer to `docs/architecture/PORTAL_ROW_WORKFLOWS.md`); this is independent of final save (final save stays blocked/human regardless).

- Mode Normal writes both fields (`browser/mode_normal.py:122-144`) — **unsafe, prohibited direct charge-split overwrite**. Mode Conventionné (PEC) is **partially aligned**: it delegates calculation to native `DevisCalculerMontantCharge()` (`:354-387`) and does not directly write the split, but it does not prove native-trigger completion or perform exact financial-summary verification, so it is **not fully target-compliant**. Full compliance in both workflows requires native trigger + read-back + exact verification before `READY_FOR_HUMAN_REVIEW`. See `KNOWN_FAILURES.md` F6.

## INV-9 — Relance / notification data must not be mutated — **HOLDS**

- No code mutates a relance; notification extraction is read-only (`browser/notifications.py`). The dashboard "WAITING/Relancé" pill is a local annotation only (`main.py:91-116`).

## INV-10 — Session secrets must not be exposed — **PARTIALLY HELD**

- No hardcoded credentials/tokens; `.gitignore` covers `mcma_auth_state.json` (exact name only). Weaknesses: `.gitignore` has no glob (a `--auth-file` copy is unignored); auth file plaintext/unencrypted/unlocked; logs and screenshots contain claimant PII (`core/logger.py:38-58,81-92`); raw `str(e)` to unauthenticated callers (`main.py:75,116,153,163,175,256`).

## INV-11 — API must authenticate employees and not expose session/automation powers to the LAN — **VIOLATED**

Required (`BUSINESS_RULES.md` B.10): server-side employee authentication, secure session cookies, CSRF protection, role authorization, server-derived audit identity; a localStorage employee name is **not** authentication and must not populate the audit actor; IP/subnet limits are defense-in-depth only with a **configurable** office subnet (no hardcoded `192.168.1.0/24`); notification-view permission separated from automation-job permission; automation jobs run asynchronously under a per-account lock.

- Current: `main.py:287` binds `0.0.0.0:8000` with **no auth and no CORS**; `POST /api/v1/auth/launch-login` spawns processes; `POST /api/v1/fill-dossier` drives the portal; audit actor comes from client-side data (`main.py:91-116`, `app.js`); `Autoriser_Reseau_Local.bat:21` opens the port on `profile=any`. See `KNOWN_FAILURES.md` F18–F23.

---

## Summary

| Invariant | Status |
|---|---|
| INV-1 Dry-run write-incapable | **VIOLATED** |
| INV-2 Mission identity (two-tier gate) | **VIOLATED** |
| INV-3 Interception default-deny, fail-closed | **VIOLATED** |
| INV-4 Final endpoints blocked | **PARTIALLY HOLDS / NOT A PERMANENT GUARANTEE** |
| INV-5 Human final validation | HOLDS (caveat) |
| INV-6 Three-origin mapping fails closed | **VIOLATED / PARTIALLY VIOLATED** |
| INV-7 Decimal money, no negative TVA | **PARTIALLY HOLDS** |
| INV-8 Charge mutuelle native-authoritative, not written | **VIOLATED (Mode Normal) / PARTIALLY HOLDS (PEC)** |
| INV-9 Relance not mutated | HOLDS |
| INV-10 Secrets not exposed | PARTIAL |
| INV-11 API authn / no LAN session exposure | **VIOLATED** |

**Until INV-1, INV-2, INV-3, INV-6, INV-7, INV-8 and INV-11 are fixed and proven by tests — and INV-4 is made a permanent, fail-closed, context-scoped guarantee — live form-filling must be treated as prohibited.**
