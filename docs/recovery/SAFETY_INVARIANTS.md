# SAFETY INVARIANTS

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

This document states the safety invariants the system **must** uphold, and records for each whether it **HOLDS** or is **VIOLATED** on this baseline, with `file:line` evidence.

---

## 0. Overall safety classification (authoritative)

> **This branch is a functional recovery baseline but is NOT production-safe for form filling.**
>
> - **Live form-filling (mission writes) is PROHIBITED** until the invariants marked VIOLATED below are fixed.
> - **"Preview", "dry-run" and "safety/test mode" are UNSAFE in the current implementation** — they do not prevent row-level writes to the portal.
> - The 19 passing tests do **not** prove mission safety, preview safety, browser-write safety or API security.

---

## INV-1 — Dry-run / preview must be technically incapable of writes — **VIOLATED**

A boolean such as `if preview: don't click` is insufficient while the session retains write-capable network access.

- `TEST_MODE` is a single module constant, hardcoded `True`, no env override (`core/config.py:19`).
- `fill_garage_conventionne(..., test_mode=True, ...)` uses `test_mode` **only in an f-string label** (`browser/mode_conventionne.py:402`); there is **no `if test_mode` guard** in the module. Pencil click, field injection, checkmark click and the `updateDevisDet` POST run identically for True/False.
- `fill_mode_normal` has **no safety parameter at all** (`browser/mode_normal.py:19`).
- The only technical control is the network interceptor — and it has the gap in INV-3. **Result: preview/dry-run writes rows.**

## INV-2 — Mission identity must be verified before any write — **VIOLATED**

- `mission_navigator.py:116-128` reads `matricule`/`dossier_ref` from the opened DOM, **prints** "Verified", and `return True` **unconditionally**. No comparison to the expected identifiers; `normalize_registration` (`core/utils.py:50`) is never called.
- Selection does not require a unique match: first substring-match wins on >1 (`:76-81`); a sole link-bearing row is opened after all filters are cleared (`:84-86,101-105`).
- **Result: the agent can open and write to the wrong mission.** Required behaviour is specified in `BUSINESS_RULES.md` B.4.

## INV-3 — Network interception must be default-deny and fail-closed for write endpoints — **VIOLATED**

- The block list (`browser/safety_interceptor.py:10-22`) is an **allow-by-omission** list, not default-deny. It **omits the two endpoints the automation actively triggers**: `updateDevisDet` (`mode_conventionne.py:288`) and `createRapportDefDet` (`mock_server.py:668`). It also lists a phantom `createDevisDet` (`:12`) with no real counterpart.
- Blocked requests **fail open**: fulfilled with `status=200, body='{"state":"success",...}'` (`:35-39`) — so read-back verification reports success for writes that never happened.
- Routes bind to `page`, not `context` (`:25,42`) — popups/new tabs are unrouted.

## INV-4 — Final / irreversible endpoints must remain permanently blocked — **HOLDS (with caveats)**

- Blocked at the network layer: `garageModifierValDevis`, `validerDevis`, `expertEnregistrerMission`, `enregistrerMission`, `expertCloturerMission`, `cloturerMission`, `cloturerTraitement`, `ajouterDocument`, `deleteDocument` (`safety_interceptor.py:11-21`).
- Final buttons are not clicked: `#Enregistrer` (Mode Normal) never referenced; `#DEVISDET_Btn` only logged (`mode_conventionne.py:456-458`).
- **Caveats:** the block **fails open** (INV-3) and is **page-scoped** (INV-3); and the whole guarantee rests on a single `TEST_MODE=True` (INV-1). So "final endpoints protected only by prompts/flags" is **half-true** — the *final* endpoints are network-blocked, but the protection is not robust and the *row-level* endpoints are unprotected.

## INV-5 — Human final validation must remain mandatory — **HOLDS**

- `process_workflow` calls `page.pause()` for human review (`main.py:236-244`); no code performs a final save/validation/clôture. *(Caveat: the pause runs **after** row writes, and `page.pause()` inside an HTTP handler blocks the request — see `KNOWN_FAILURES.md`.)*

## INV-6 — Unknown mappings must fail closed — **PARTIALLY VIOLATED**

- Holds for unknown `part_type` (`wexia_mapper.py:534-536`) and unknown labour (`:512-514`).
- Violated for out-of-catalogue `mcma_rubric_id` (`:578`, silent inference) and the matrix `.get` default (`:550`). Recognized glass operations default into rubrique 1 instead of 20/22. Required corrections: `BUSINESS_RULES.md` B.1, B.3.

## INV-7 — Monetary values must use Decimal — **HOLDS (in the mapper)**

- Strict `Decimal` + `ROUND_HALF_UP` + remainder allocation (`wexia_mapper.py:109-125,638-664`). Floats appear only at the portal JS boundary. Latent: per-line TVA can go negative (`:646`).

## INV-8 — Charge mutuelle must not be forced / overwritten — **VIOLATED**

- `browser/mode_normal.py:122-144` forces `MontantChargeMutuelle = MontantReparation` and `MontantChargeSocietaire = '0'`, discarding the portal split. Required behaviour: preserve native values or require human review (`BUSINESS_RULES.md` B.2).

## INV-9 — Relance / notification data must not be mutated — **HOLDS**

- No code mutates a relance; notification extraction is read-only (`browser/notifications.py`). The dashboard "WAITING/Relancé" pill is a local annotation only (`main.py:91-116`).

## INV-10 — Session secrets must not be exposed — **PARTIALLY HELD**

- No hardcoded credentials/tokens anywhere; `.gitignore` covers `mcma_auth_state.json`. **Weaknesses:** `.gitignore` covers only the exact filename, not a glob (a `--auth-file` copy is unignored); the auth file is plaintext/unencrypted/unlocked; logs and screenshots contain claimant PII in cleartext (`core/logger.py:38-58,81-92`); raw `str(e)` is returned to unauthenticated LAN callers (`main.py:75,116,153,163,175,256`).

## INV-11 — The API must not expose write/authenticated-session powers to the LAN without authorization — **VIOLATED**

- `main.py:287` binds `0.0.0.0:8000` with **no auth and no CORS**; `POST /api/v1/auth/launch-login` spawns processes; `POST /api/v1/fill-dossier` drives the portal with the stored session. `Autoriser_Reseau_Local.bat:21` opens the port on `profile=any`.

---

## Summary

| Invariant | Status |
|---|---|
| INV-1 Dry-run write-incapable | **VIOLATED** |
| INV-2 Mission identity verified | **VIOLATED** |
| INV-3 Interception default-deny, fail-closed | **VIOLATED** |
| INV-4 Final endpoints blocked | HOLDS (fragile) |
| INV-5 Human final validation | HOLDS (caveat) |
| INV-6 Unknown mappings fail closed | **PARTIALLY VIOLATED** |
| INV-7 Decimal money | HOLDS (mapper) |
| INV-8 Charge mutuelle not forced | **VIOLATED** |
| INV-9 Relance not mutated | HOLDS |
| INV-10 Secrets not exposed | PARTIAL |
| INV-11 API not exposing session to LAN | **VIOLATED** |

**Until INV-1, INV-2, INV-3, INV-6, INV-8 and INV-11 are fixed and proven by tests, live form-filling must be treated as prohibited.**
