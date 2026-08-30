# KNOWN FAILURES

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

Every confirmed regression / defect on this branch, with `file:line` evidence and impact. All findings are derived from this branch only; no other branch was inspected or referenced.

Severity: **S1** = can cause a wrong or unintended live portal write · **S2** = safety control weaker than it appears · **S3** = correctness/robustness · **S4** = security/exposure · **S5** = operational/UX.

---

## S1 — Wrong-write / write-safety

### F1. Row-level writes execute in "preview"/"safety" mode — **S1, CONFIRMED**
`browser/safety_interceptor.py:10-22` omits `updateDevisDet` and `createRapportDefDet` — the two endpoints the automation actively triggers. No `test_mode` guard exists in either controller (`mode_conventionne.py:402` label only; `mode_normal.py` has no flag). Impact: dry-run/preview persists line items to the live portal.

### F2. `updateDevisDet` / `createRapportDefDet` not blocked — **S1, CONFIRMED**
`updateDevisDet` awaited at `mode_conventionne.py:288`; `createRapportDefDet` triggered by the Mode Normal checkmark (`mock_server.py:668`). Neither is in the block list. `**/createDevisDet` (`safety_interceptor.py:12`) is a phantom with no real counterpart that masked the gap.

### F3. No mission-identity gate before writing — **S1, CONFIRMED**
`mission_navigator.py:116-128` reads and prints identifiers, then `return True` unconditionally — no comparison to expected `matricule`/`dossier_ref`. Impact: writes proceed to whatever mission was opened.

### F4. First-row / sole-candidate mission fallback — **S1, CONFIRMED**
`find_mission_link` returns the first substring-matching row on >1 match (`:76-81`) and, on zero matches, the sole link-bearing row (`:84-86`) after Try-3 clears all filters (`:101-105`). Combined with the lossy digit-run search key (`core/utils.py:59-70`), an unrelated mission can be opened and written.

### F5. Partial matches proceed to writes — **S1, CONFIRMED**
`search_matricule_num in row_text` (`:76`) is an unanchored substring test over the whole row's concatenated text; the digit-run key discards the series/letter suffix, so `36165-B-50` and `36165-U-50` are indistinguishable (`test_mapper.py:344` shows such plate collisions in real data). No uniqueness check.

### F6. Forced charge-mutuelle overwrite — **S1, CONFIRMED**
`browser/mode_normal.py:122-144` sets `MontantChargeMutuelle = MontantReparation` and `MontantChargeSocietaire = '0'` after native calc, zeroing franchise/vétusté/part-responsabilité. Violates the resolved rule (`BUSINESS_RULES.md` B.2/B.3). Both workflows must trigger and verify native calculation (refer to `PORTAL_ROW_WORKFLOWS.md`). `mode_conventionne` defers to native calc and writes neither field, which is compliant.

### F7. Duplicate checkmark click (Mode Normal) — **S1/S3, CONFIRMED**
`mode_normal.py:78-99` clicks the col-7 save control twice (Playwright locator then unconditional JS) with no guard on the first succeeding. Possible duplicate row creation.

---

## S2 — Safety controls weaker than they appear

### F8. Interceptor fails open — **S2, CONFIRMED**
`safety_interceptor.py:35-39` fulfills blocked requests with `200 {"state":"success"}`. Every downstream read-back (`mode_conventionne.py:311-312,346-348`; `mode_normal.py:111-112`) reports success for writes that did not happen.

### F9. Interceptor is page-scoped, not context-scoped — **S2, CONFIRMED**
Routes bound to `page` (`safety_interceptor.py:25,42`); a popup/new tab/`context.new_page()` is unrouted.

### F10. Dry-run is a flag, not a capability — **S2, CONFIRMED**
Single hardcoded `TEST_MODE` (`core/config.py:19`); `test_mode` param cosmetic (`mode_conventionne.py:402`); `fill_mode_normal` has no flag. See `SAFETY_INVARIANTS.md` INV-1.

### F11. `mapping_status` / `warnings` never enforced — **S2, CONFIRMED**
Produced at `wexia_mapper.py:278-279`; **zero readers** in `run_dossier.py` / `process_workflow`. A `needs_review` dossier (registration conflict `:199-202`, date conflict `:432-435`, un-inferable TVA `:475-476`) runs identically to a clean one. Note the canonical example (`json_dossier_example.md:59`, `insured_type: "physique"`) trips `:475` and would still run.

### F12. "Verified"/"READY"/"Prêt" claims without verification — **S2, CONFIRMED**
`mission_navigator.py:127` prints "Verified" without comparing; `menu.py:37` shows "CONNECTED / READY" from file existence; `app.js:622` resets the badge to "Prêt" in a `finally` even after a failed refresh (`:618-623`); `wexia_mapper.py:168` defaults `mapping_status="ready"`.

---

## S2/S6 — Mapping correctness (resolved-requirement contradictions)

### F13. Recognized glass operations fold into rubrique 1 — **S2, CONFIRMED**
The mapper has no producer for glass rubriques 19-24; a `pare-brise`/`vitre` part line falls through `_determine_part_rubrique` (`wexia_mapper.py:517-551`) to `family=carrosserie` ⇒ rubrique 1 (`test_mapper.py:68`). Must use the supplied component×operation mapping for 19–24; ambiguous/conflicting glass fails closed; never rubrique 1 (`BUSINESS_RULES.md` B.2).

### F33. Keyword-based family inference to rubriques 4–6 / 13–15 — **S2, CONFIRMED**
`_determine_part_rubrique` infers `family = mecanique/electrique` from item-name keywords (`wexia_mapper.py:541-544`) and maps to 4–6 / 13–15 via `SYSTEM_RUBRIQUE_MATRIX` (`:550`). The three-origin rule forbids inferring these rubriques from part-description keywords: ordinary parts map only by origin to 1/2/3 (`BUSINESS_RULES.md` B.1). *(Rubriques 10/11 peinture-fournitures are likewise not to be produced by keyword inference; painting routes to 16 or labour 12.)*

### F14. Out-of-catalogue `mcma_rubric_id` silently inferred — **S2, CONFIRMED**
`wexia_mapper.py:578` accepts only in-catalog ids and otherwise falls through to inference instead of failing closed. Must fail closed (`BUSINESS_RULES.md` B.3). The matrix `.get` default (`:550`) is a second latent fail-open.

### F15. Over-broad `"mo"` labour token — **S3, CONFIRMED**
`_determine_labour_rubrique` (`:508`) substring-tests the 2-letter `"mo"` against the whole normalized string, so "demontage", "commande", "modification", "amovible" collapse to rubrique 7, narrowing the intended `ValueError` at `:512`. Required: remove unrestricted `mo` matching; use structured `item_type`/`operation_type` first; generic peinture/mécanique/électrique alone is insufficient; ambiguous fails closed (`BUSINESS_RULES.md` B.7).

### F16. Rubrique substring collisions (garage-conventionné matcher) — **S2, CONFIRMED (latent)**
`_match_single_rubrique` (`mode_conventionne.py:105-138`) does bidirectional substring matching ≥4 chars (`:127,135`) on first-row-wins order; `"colle"` (25) ⊂ `"kit colle vitre"` (27) / `"kit colle pare brise"` (26); aliases duplicated across ids 10/11/16 (`core/constants.py:126-165`). Matching is label-text only — `IdRubrique` is never verified. Mitigation present: `match_all_rubriques` is all-or-nothing (`:175`, aborts on any unmatched), but that does not prevent a mutually-consistent wrong assignment.

### F17. Latent negative TVA — **S1/S3, CONFIRMED**
Per-line `tva_val` (`wexia_mapper.py:646`) is unguarded and can go negative if earlier 20% rounding overshoots the target; a negative `Taxe` could be written. Required behaviour: no negative-TVA line, no silent clamp — deterministic non-negative redistribution to 0.01 MAD or fail closed with `NEEDS_REVIEW: INVALID_TAX_ALLOCATION`; no 0.05 MAD tolerance (`BUSINESS_RULES.md` B.6).

---

## S4 — Security / exposure

### F18. Unauthenticated LAN API over a live authenticated session — **S4, CONFIRMED**
`main.py:287` binds `0.0.0.0:8000`, no auth/CORS; `POST /api/v1/auth/launch-login` (`:67-75`) spawns processes; `GET /api/v1/notifications` (`:132-153`) drives the portal; `POST /api/v1/fill-dossier` (`:156-163`) runs a workflow. `Autoriser_Reseau_Local.bat:21` opens the port on `profile=any`.

### F19. Raw exception text to LAN callers — **S4, CONFIRMED**
`str(e)` returned in HTTP detail/body at `main.py:75,116,153,163,175,256` — leaks filesystem paths and internals.

### F20. Fail-open workflow status — **S3/S4, CONFIRMED**
`process_workflow` swallows exceptions into `{"status":"failed",...}` (`main.py:254-256`) but the caller wraps it as `{"status":"success","result":...}` at HTTP 200 (`:160-161`). A failed/expired run reads as success by status code.

### F21. PII in plaintext logs/screenshots — **S4, CONFIRMED**
`logs/mcma_notifications.json` stores insured names/policies/plates (`browser/notifications.py:90-100`), echoed to stdout (`:262-263`); screenshots capture the logged-in portal (`core/logger.py:81-92`). No rotation/retention. `logs/` also doubles as the application datastore.

### F22. Dashboard XSS — **S4, CONFIRMED**
Portal/imported data interpolated into `innerHTML` unescaped (`app.js:419-487`) and into inline `onclick` (`:436,439,451`); toasts use `innerHTML` (`:636`).

### F23. `.gitignore` covers only the exact auth filename — **S4, CONFIRMED**
`.gitignore:13` = `mcma_auth_state.json` (no glob); a `--auth-file` copy (`session_keeper.py:196-200`) or `*.backup.json` is committable.

### F24. Auth save is fail-open — **S3/S4, CONFIRMED**
`auth_setup.py:50-51,63,65-69` saves state on timeout and reports SUCCESS if file > 10 bytes — an unauthenticated file passes.

---

## S5 — Operational / UX / robustness

### F25. `page.pause()` inside an HTTP handler — **S5, CONFIRMED**
`main.py:244` with `headless=False` (`:204`) blocks the request and the shared event loop indefinitely; cannot run as a service.

### F26. `logs/` is the database — **S5, CONFIRMED**
Employee notes/status and the notification cache live under `logs/` with non-atomic whole-file rewrites (`main.py:147`; `core/logger.py:59-65`), no backup; corruption swallowed (`main.py:127-128`). "Clearing logs" destroys employee work.

### F27. Fabricated demo data renders as real — **S5, CONFIRMED**
`static/app.js:161` defaults `currentData = SAMPLE_NOTIFICATIONS` (12 fabricated claims `:6-158`); the failure path keeps them on screen while saying "Données de démonstration actives" (`:619`).

### F28. Constants duplicated across ≥5 sites — **S5, CONFIRMED**
`core/config.py:23,26,35` vs `auth_setup.py:14,62`, `session_keeper.py:34-36`, `menu.py:20`; `DEFAULT_KEEP_ALIVE_MINUTES` is dead. Drift already present.

### F29. Widespread silent exception swallowing — **S5, CONFIRMED**
≥12 sites: `main.py:36,86,101,127`; `browser/notifications.py:102`; `core/logger.py:56,64`; `static/app.js:215,229,238,244,535`. Failures become invisible.

### F30. `menu.py` "Preview mapped fields" is a no-op — **S5, CONFIRMED**
`menu.py:79` runs `mapper.py` as a script, but `mapper.py` is a re-export shim with no `__main__`/argv handling.

### F31. Keep-alive daemon: no scheduling, no escalation — **S5, CONFIRMED**
`session_keeper.py:164-180` loops forever on failure with only a printed warning; nothing in the repo schedules it.

### F32. HHMMSS-only screenshot names collide — **S5, CONFIRMED**
`core/logger.py:85` uses `%H%M%S`; same-second or cross-day runs overwrite silently.
