# FEATURE INVENTORY

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

Status legend: **verified** (confirmed in code) · **partial** (implemented with gaps) · **broken** (present but does not meet its stated intent) · **missing** (not implemented on this branch). Each entry cites `file:line`. Every feature from the Phase 1 inventory is preserved.

---

## Authentication & session

### Manual login + OTP — **verified (fail-open behaviour)**
- Entry: `python auth_setup.py`; `Se_Connecter_MCMA.bat:19`; `menu.py:65-69`; `POST /api/v1/auth/launch-login` (`main.py:67-75`); dashboard button (`static/app.js:294-306`).
- Files/functions: `auth_setup.py:6-73` `manual_login()`.
- Input: human types username/password/OTP into the visible browser (no credentials in repo). Output: `mcma_auth_state.json` (`auth_setup.py:62`).
- Selectors/URLs: navigates `sinauto.mamda-mcma.ma/SinAuto_MCMA/` (`:14`); success heuristics `#formRecherche, #ReferenceCie, a[href*='logout']` (`:38,55`).
- Side effects: writes storage-state file to CWD.
- Tests: none.
- Risk: **fail-open** — on 300 s timeout it still saves state (`:50-51,63`) and prints SUCCESS if file > 10 bytes (`:65-69`), so an unauthenticated file passes.

### Save Playwright session — **verified (single account, plaintext)**
- `auth_setup.py:62` (initial), `session_keeper.py:128` (refresh-rewrite).
- One file `mcma_auth_state.json`, CWD-relative; no encryption, no chmod, no lock. Filename literal duplicated across `core/config.py:26`, `auth_setup.py:62`, `session_keeper.py:34`, `menu.py:20`, and prose in `mission_navigator.py:37`.
- Tests: only the missing-file branch (`tests/test_session_keeper.py:13-18`).
- Risk: plaintext session cookies shared by 4+ concurrent writers with no lock.

### Restore + validate session — **verified (two divergent predicates)**
- Consumers build `new_context(storage_state=...)`: `main.py:140,205`, `session_keeper.py:73`, `get_notifications.py:50`.
- Validators: `browser/mission_navigator.py:14-22` `check_session_validity`; `session_keeper.py:83-116`. The two disagree — the former lacks the positive dashboard-present check the latter has.
- Logged-out markers: URL contains "login", HTML marker `expert_.phtml`, DOM `input[name='login'], #login, #password`.
- Tests: none for valid/expired branches (require a live browser).

### Detect expired session — **partial (mixed fail-closed / fail-open)**
- Fail-closed: mission path raises (`mission_navigator.py:34-40`), notifications raise (`browser/notifications.py:183-185`).
- Fail-open: `auth_setup.py` (above); `menu.py:37` shows "CONNECTED / READY" from file existence alone; `process_workflow` swallows expiry into an HTTP-200 failed body (`main.py:254-256`).

### Multi-account handling (Oujda/Nador) — **missing**
- No account concept anywhere in `.py/.js/.html`; the four profiles appear only in `PROJECT_ARCHITECTURE_BLUEPRINT.md:22-29`. Single shared auth file; `session_keeper.py --auth-file` (`:196-200`) is the only parameterized seam.
- **Resolved requirement:** Oujda/Nador are account profiles/notification scopes from one office, not city deployments. Multi-account support is deferred to after core safety and must be extensible (no hardcoded count of 4). See `OPEN_QUESTIONS.md`.

### Session keep-alive daemon — **verified (unscheduled)**
- `session_keeper.py:151-180` `run_daemon`; probes the live portal headless every 10 min (`:164`), rewrites the auth file on success (`:128`). Nothing in the repo schedules it; infinite silent retry, no escalation.

## Mission workflow (form-filling)

### Mission search — **verified**
- `browser/mission_navigator.py:25` `search_and_open_mission`; called `main.py:213`.
- Route `.../expertise/FrontExpert/` (`core/config.py:23`, navigated `:30`). Selectors `#Matricule` (`:49`), `#ReferenceCie` (`:52`); search trigger `a[onclick*='rechercheMission'], ... :has-text('Rechercher')` (`:54`).
- Search key is **lossy by design**: `extract_search_matricule` keeps the first digit run only (`core/utils.py:59-70`), e.g. `36165-B-50` → `36165`.

### Mission-result selection — **broken**
- `find_mission_link` (`:62-87`): on >1 match returns the **first** row whose concatenated text contains the (unanchored) search substring (`:76-81`); if nothing matches, returns the **sole** link-bearing row (`:84-86`) — reached after Try-3 deliberately **clears all filters** to list every assigned mission (`:101-105`).
- Does **not** require exactly one match; has a first-row/sole-candidate fallback. Tests: none. Risk: **wrong-dossier writes**.

### Open mission — **verified**
- `:107-113` click → `wait_for_load_state` → 1500 ms wait.

### Mission identity verification — **broken (absent)**
- `:116-128` reads `matricule`/`dossier_ref`/`mode_rep` from the opened DOM, **prints** "Verified", and `return True` **unconditionally**. No comparison against expected identifiers; `normalize_registration` (`core/utils.py:50`) is never called. Risk: writes proceed without identity confirmation.

### Read dossier JSON + validation — **partial**
- No schema; `FillDossierRequest.payload`/`WexiaDossierRequest.wexia_payload` are `Dict[str, Any]` (`main.py:46-51`). Load via `json.loads` with markdown-fence strip (`run_dossier.py:75-86`); format sniff `run_dossier.py:110`.
- Fails closed on: reform (`wexia_mapper.py:215-216`), conflicting modes (`:296-297`), missing explicit chiffrage (`:328`), divergent approved totals (`:352-354`), unknown part_type (`:534-536`), unknown labour (`:512-514`), invalid `PartResponsabilite` (`:457-458`), HT/TVA/TTC mismatch (`:671-676`).
- Gap: `mapping_status`/`warnings` are produced (`:278-279`) but **never consumed** — a `needs_review` dossier runs identically to a clean one.

### Form-filling, Mode Normal — **verified (performs row writes)**
- Header: `browser/form_filler.py:16` `fill_main_form` (selectors `#<field_id>`; missing fields skipped silently `:41`).
- Rows: `browser/mode_normal.py:19` `fill_mode_normal` — checks `#VehRepareI` (:41), clicks Ajouter (:58-66), fills `#IdRubrique/#MontantHT/#Taxe` (:71-74), clicks the col-7 green checkmark **twice** (locator :80-85, then unconditional JS :87-99). The checkmark triggers `createRapportDefDet` (`mock_server.py:668`) — **not** network-blocked.
- Final `#Enregistrer`: **never clicked** and network-blocked — genuinely safe.

### Garage Conventionné — **partial (performs row writes)**
- `browser/mode_conventionne.py:390` `fill_garage_conventionne` (dispatched `main.py:229`). Reads `#DevisDetTableVal` (:60,68); per-row pencil click (:219-230); fills `#MontantHTValide/#TaxeValide/#TauxVetusteValide/#MontantVetusteValide` (:259-266); clicks per-row green checkmark (:291-302); awaits `updateDevisDet` (:288) — **not** network-blocked. Final `#DEVISDET_Btn` / `garageModifierValDevis`: not clicked and blocked.
- `test_mode` parameter is used only in an f-string label (`:402`); **no `if test_mode` guard exists** — writes execute the same whether True or False.

### Rubrique discovery & mapping — **partial (fail-open holes)**
- `mapper/wexia_mapper.py:517-551` `_determine_part_rubrique`; colle/kits `_classify_colle_or_adhesive:483-492`; labour `_determine_labour_rubrique:494-514`.
- Holes: out-of-catalogue `mcma_rubric_id` is silently discarded then inferred (`:578`) — **must fail closed** (`BUSINESS_RULES.md` B.4); matrix `.get(...)` default-to-carrosserie fallback (`:550`); over-broad 2-letter `"mo"` labour token (`:508`) — **must use structured item_type/operation_type first** (`BUSINESS_RULES.md` B.7).
- Keyword-based family inference to rubriques 4–6 / 13–15 (`:541-544,550`) is **disallowed** under the three-origin rule: ordinary parts map only by origin to 1/2/3 (`BUSINESS_RULES.md` B.1; `KNOWN_FAILURES.md` F33).
- Recognized glass operations currently fold into rubrique 1 (`_determine_part_rubrique` → family carrosserie) — **must use the component×operation mapping for rubriques 19–24, ambiguous glass failing closed** (`BUSINESS_RULES.md` B.2; `KNOWN_FAILURES.md` F13).

### Row editing & native recalculation — **verified**
- `_edit_single_row_dynamic` (`mode_conventionne.py:182-351`) re-locates by normalized label, edits, awaits `updateDevisDet`, reads back — but never compares read-back to intended values and returns True regardless (`:351`).
- Native recalc deferral: `_trigger_devis_calculations:354-387`; `dom_helpers.trigger_mcma_calculations:116-155`.

### Monetary calculations — **verified (Decimal in mapper)**
- Strict `Decimal` + `ROUND_HALF_UP` + last-line tax remainder allocation (`wexia_mapper.py:109-125,638-664`); ±0.01 assertions (`:671-676`). Floats appear only at the portal JS boundary (inherent). Latent: per-line TVA can go negative (`:646`).

### Charge mutuelle — **broken (forced overwrite)**
- `browser/mode_normal.py:122-144` sets `MontantChargeMutuelle = repair total` and `MontantChargeSocietaire = '0'` after native calc, discarding the portal split. **Authoritative decision:** portal-native calculation is authoritative in **both** workflows; neither workflow may write `MontantChargeSocietaire` or `MontantChargeMutuelle`; native triggering AND verification are mandatory in both workflows (refer to `docs/architecture/PORTAL_ROW_WORKFLOWS.md`); independent of final save. See `BUSINESS_RULES.md` B.3.
- **Baseline classification:** Mode Normal baseline is **unsafe — a prohibited direct charge-split overwrite**. The PEC baseline (`mode_conventionne`) is **partially aligned** — it delegates calculation to SinAuto and does not directly write the split — but is **not fully target-compliant** until native-trigger completion and exact financial-summary verification are proven. Full compliance in both workflows requires trigger + read-back + verification before `READY_FOR_HUMAN_REVIEW`.

## Notifications, dashboard, API

### Notification extraction — **verified**
- `browser/notifications.py:175-268` `fetch_all_notifications`; per-category `_fetch_category_rows:24-172`. Strategy 1 in-page fetch POST to `.../notification/getAlerte/CodeAlerte/{code}` with `length:'-1'`, `iDisplayLength:'-1'` (:37-46); Strategy 2 DOM DataTable fallback (:108-170). Output `logs/mcma_notifications.json`. Account scopes: none in code.

### Relance extraction / mutation — **partial read-only; mutation missing (safe)**
- No dedicated relance code; a `RELANCES` category is picked up by the generic loop (`:243-266`). **No code mutates a relance.** The dashboard "WAITING / Relancé" pill is a **local** annotation (`main.py:91-116`), never pushed to the portal *(inference: semantic trap for employees)*.

### FastAPI endpoints — **verified (no auth, no CORS)**
- `main.py`: `GET /health` (:61); `POST /api/v1/auth/launch-login` (:67, spawns subprocess); `GET/POST /api/v1/notification-actions` (:78-116); `GET /api/v1/cached-notifications` (:119); `GET /api/v1/notifications` (:132, live portal); `POST /api/v1/fill-dossier` (:156); `POST /api/v1/fill-dossier-from-wexia` (:166); static mount `/` (:259-260). Binds `0.0.0.0:8000` (:287). No auth dependency, no CORS middleware anywhere.

### SSE / live events — **missing**
- No `StreamingResponse`/`EventSource`/`text/event-stream`. Dashboard refresh is button-click only (`static/app.js:600-624`); no timer.

### Dashboard — **verified**
- `static/index.html` + `static/app.js`. KPI cards, category tabs, 9-column table, status pills, notes modal, `localStorage` + server sync. All fetch URLs relative. Risks: XSS via unescaped `innerHTML` (`app.js:419-487`); last-write-wins on shared actions (`main.py:105`); fabricated demo data renders by default and on failure (`app.js:161,619`).

### Screenshots & diagnostics — **verified**
- `core/logger.py:81-92` `capture_screenshot` → `logs/screenshots/{label}_{HHMMSS}.png`; callers in `mode_conventionne.py:409-460`, `mode_normal.py:38,146`. HHMMSS-only names collide/overwrite.

### Readiness reports — **broken/misleading**
- No real readiness endpoint. `menu.py:37` "READY" from file existence; `app.js:622` "Prêt" even after a failed refresh; `wexia_mapper.py:168` `mapping_status` defaults "ready" (fail-open).

### Windows launchers & startup — **verified**
- 7 `.bat` + 1 `.url`. `Autoriser_Reseau_Local.bat:21` adds firewall rule TCP 8000 `profile=any`. Hardcoded `192.168.1.17` in `Ouvrir_MCMA_Employe.bat:4` and `MCMA_Dashboard_Employe.url:2`. `setup_new_pc.bat` lacks `cd /d "%~dp0"`.

### Tests & fixtures — **partial**
- 19 tests (`tests/test_mapper.py` 12, `tests/test_garage_conventionne.py` 5, `tests/test_session_keeper.py` 2). No `conftest.py`; no production-domain (network) blocking. See `TEST_EVIDENCE.md`.
