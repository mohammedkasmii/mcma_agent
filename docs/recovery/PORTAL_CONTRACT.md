# PORTAL CONTRACT

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

The portal-facing surface the agent depends on: URLs, DOM selectors and HTTP endpoints. **Verified** items are read from the automation code. Endpoint *shapes* are corroborated by the offline replica `mock_server.py` (a hand-built mock, **not** captured live traffic) — treated here as *inference* about the real portal, not proof.

> No live portal access was performed. Selectors and endpoint names below are transcribed from source, not from a live session.

---

## 1. Base URLs (verified)

- Root: `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` (`core/config.py:22`).
- **Canonical mission route: `/expertise/frontexpert/`.** The current code uses the case variant `.../SinAuto_MCMA/expertise/FrontExpert/` (`core/config.py:23`). Treat the lowercase form as canonical; the deployed portal is case-insensitive on this segment *(inference — not verified live; both forms are recorded so later code can normalize to the canonical spelling)*.

## 2. Authentication surface (verified selectors)

- Logged-out indicators: URL contains `login`; page HTML marker `expert_.phtml`; DOM `input[name='login'], #login, #password` (`session_keeper.py:83-88`; `mission_navigator.py:16-21`).
- Logged-in indicators: `#formRecherche, #ReferenceCie, #Matricule, a[href*='logout'], a[href*='Login/logout']`; URL contains `/expertise/` or `/frontexpert` (`session_keeper.py:101-105`; `auth_setup.py:38,55`).
- Username scrape: `span.user-name, div.user-profile, a.dropdown-toggle:has(.fa-user), .username` (`session_keeper.py:121`).

## 3. Mission search & selection (verified selectors)

- Search inputs: `#Matricule` (`mission_navigator.py:49`), `#ReferenceCie` (`:52`).
- Search trigger: `a[onclick*='rechercheMission'], a[onclick*='RechercheMission'], a:has-text('Rechercher'), button:has-text('Rechercher')` (`:54`); fallback Enter key (`:58`).
- Result rows: `#listeSinistre tbody tr` (`:63`).
- Mission open link: `a[href*='gotoMission'], a[title*='Mission expertise'], div.text-blue a, a.btn-primary` (`:74`).
- Post-open identity fields (read only, not compared): `#MatriculeVeh, #Immatriculation, input[name="MatriculeVeh"]`; `#ReferenceDossier, #RefDossier, input[name="ReferenceDossier"]`; `#modeReparation, #ModeReparation, select[name="ModeReparation"]` (`:116-126`).

## 4. Mission mode detection (verified)

- Conventionné markers: `#DevisDetTableVal, #blocDevisValide` (`main.py:219`).
- Normal markers: `#VehRepareI, #MontantReparation, #tableRapportDet` (`main.py:222-225`).

**Historical baseline behavior, superseded by the target rule below:** `main.py:222-225` treated `#VehRepareI` as one of its Normal-mode markers. That recovered behavior is preserved above as evidence, but it is unsafe/ambiguous for the target architecture and must not be carried forward: §5 independently lists `#VehRepareI` among the *shared* header fields present on every mission regardless of mode (`browser/form_filler.py`), and the mock/DOM evidence confirms it — `#VehRepareI` is a shared mission option/header field. It may control whether the Mode Normal table is exposed, but its mere *presence* cannot identify which workflow is active, since it is present on a PEC mission too. A detector using "any Normal marker present ⇒ MODE_NORMAL" would therefore return MODE_NORMAL on every page, PEC included, and any workflow-mismatch gate built on it would pass vacuously.

**Target rule:** workflow detection must not use `#VehRepareI`. Target Mode Normal detection uses the workflow-exclusive combination `#tableRapportDet` **and** `#MontantReparation` (both required); target PEC detection uses `#DevisDetTableVal` **and** `#blocDevisValide` (both required). If both sets are present, or neither set is present, detection fails closed — it is never resolved by guessing one. Implemented in `mcma/portal/mission.py` (`detect_observed_workflow`, `_NORMAL_MARKERS`, `_PEC_MARKERS`, `WorkflowIndeterminate`); see `tests/portal/mission/test_workflow_detection.py` for the corresponding test coverage (including the ambiguous-both-present and neither-present fail-closed cases).

## 5. Header form fields (verified; from README + form_filler)

- Selector pattern `#<field_id>` (`browser/form_filler.py:29,50,60`). Known IDs (README.md:160-173): `#Kilometrage`, `#ValeurVenale` (↔ `#ValeurVenaleEstime` swap, `form_filler.py:33-38`), `#MontantReparation`, `#MontantTVA`, `#MontantTTC`, `#NbreJourImmobilisation`, `#PartResponsabilite`, `#TypeReforme`, `#VehRepareI`, `#ObservationMission`.

## 6. Rubrique row editing (verified selectors)

- **Mode Normal:** `#IdRubrique`, `#MontantHT`, `#Taxe`; add-row `a.btn-success:has-text('Ajouter'), a:has-text('Ajouter +'), a[onclick*='addRow']` and JS `edataTable_RapportDet.addRow()`; save = column-7 checkmark `td:nth-child(7)` (`browser/mode_normal.py:58-99`). Read-back table `#tableRapportDet tbody tr, table.dataTable tbody tr` (`:104-110`).
- **Garage Conventionné:** table `#DevisDetTableVal` (`mode_conventionne.py:60`); pencil `a.edit-row, a#Modifier, a[onclick*="editRow"], a[title*="Modifier"], i.fa-pencil` (`:219-230`); value fields `#MontantHTValide, #TaxeValide, #TauxVetusteValide, #MontantVetusteValide` (`:259-266`); save checkmark `a.save-row, a:has(.fa-check), a[onclick*="saveRow"], a[title*="Enregistrer"], i.fa-check` (`:291-302`); final button `#DEVISDET_Btn` (`:456-458`, **not clicked**).

## 7. Notification surface (verified)

- Categories: `#listeAlertes a[href*="notification/alerte/"]`; code regex `alerte\/([A-Za-z0-9\-]+)` (`browser/notifications.py:203,208`).
- Data fetch: POST `.../SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/{code}` with `X-Requested-With: XMLHttpRequest` and DataTables params `length=-1`, `iDisplayLength=-1` (`:37-49`).
- DOM table (fallback): `#listeAlerte tbody tr`, page-length control `select[name*='listeAlerte_length']` (`:123-133`).
- Deep link to a claim: `/SinAuto_MCMA/expertise/gestionExpert/getSinistre/idSinistre/{id}/rubrique/gestionexpert-index` (`:99`).

## 8. HTTP endpoints — mutating vs read (verified list; shapes inferred from `mock_server.py`)

**Network-blocked in `browser/safety_interceptor.py:10-22` (glob patterns):**
`garageModifierValDevis`, `createDevisDet`, `deleteDevisDet`, `expertCloturerMission`, `expertEnregistrerMission`, `cloturerMission`, `enregistrerMission`, `validerDevis`, `ajouterDocument`, `deleteDocument`, `cloturerTraitement`.

**Actively driven by the automation but NOT in the block list (critical gap):**
- `.../gestionexpert/updateDevisDet` — Garage Conventionné per-row save; awaited at `mode_conventionne.py:288`; mock at `mock_server.py:601`.
- `.../gestionExpert/createRapportDefDet` — Mode Normal per-row create; mock at `mock_server.py:668`.

**Listed but not matching a real portal endpoint (inference):**
- `**/createDevisDet` (`safety_interceptor.py:12`) — no counterpart in `mock_server.py`'s route table; appears to be a phantom that masked the fact that row *creation* was unblocked.

**Other portal POSTs mocked (for reference, `mock_server.py:705-772`):**
`/front/Login/login`, `.../FrontExpert/listeMissions`, `.../gestiongarage/garageModifierValDevis`, `.../gestionExpert/listeRapportDefDet`, `.../gestiongarage/listeDevisDet`, `.../gestionExpert/expertEnregistrerMission`, `/gestion/GED/ajouterDocument`.

## 9. Interception mechanics (verified)

- `install_safety_policy(page, enabled)` registers `page.route(pattern, block_handler)` for each glob (`safety_interceptor.py:41-42`), installed once at `main.py:210` when `TEST_MODE` is true.
- **Blocked requests are fulfilled with `status=200, body='{"state":"success",...}'`** (`:35-39`) — i.e. **fail open**: a blocked write is indistinguishable from a success to any read-back verification.
- Routes bind to the single `page`, not the `context` (`:25,42`) — a popup/new tab/`context.new_page()` is unrouted. Patterns are bare-suffix globs (a query-string or path variant could evade them). *(Inference on evasion; the fail-open and page-scope facts are verified.)*

## 10. Target row-write contract (supersedes baseline behavior; source of truth: `docs/architecture/PORTAL_ROW_WORKFLOWS.md`)

Sections 1–9 above record the **recovered baseline** — how the code at `0290fe9` actually behaved, including its unsafe
behaviors. This section records the **target contract** the rebuild implements instead. Where the two disagree, the
baseline is historical evidence only, never a license.

**Charge-split evidence classification:** the baseline directly addressed `#MontantChargeMutuelle` and
`#MontantChargeSocietaire` (`browser/mode_normal.py:122-144`), so those field selectors are **recovered/observed
evidence that the summary fields exist**. That historical direct overwrite was **unsafe and remains permanently
prohibited**: in the target contract **neither workflow may directly write the charge-mutuelle or charge-sociétaire
fields**; both workflows must trigger the SinAuto-native calculation and verify the financial summary before
`READY_FOR_HUMAN_REVIEW`. Reviewed row-level `createRapportDefDet` (Mode Normal) / `updateDevisDet` (PEC) persistence
is allowed; dossier-level final `Enregistrer`/`Valider`/`Clôturer`/GED/delete actions remain permanently prohibited and
human-controlled.

### 10.1 Mode Normal (target)

1. Verify mission identity and the observed repair workflow.
2. Ensure `#VehRepareI` exposes the table.
3. Initially empty/add-row lifecycle.
4. For every approved RowOp:
   - click Ajouter;
   - wait for one temporary row;
   - select the exact `#IdRubrique`;
   - fill `#MontantHT` and `#Taxe`;
   - dispatch the required focus/input/keyup/change/blur behavior;
   - click the column-7 checkmark exactly once;
   - await and validate `createRapportDefDet`;
   - wait for the redraw;
   - discard stale DOM references;
   - relocate the persisted row;
   - verify the exact rubrique/HT/TVA read-back;
   - only then continue.
5. Trigger and verify the workflow-specific native financial calculation. *(The exact Mode Normal native trigger,
   readiness signal, and summary read-back contract are UNCONFIRMED and mandatory G5 preconditions —
   `docs/architecture/PORTAL_ROW_WORKFLOWS.md` §3.1.)*
6. Stop at `READY_FOR_HUMAN_REVIEW`.

### 10.2 Garage Conventionné / PEC (target)

1. Verify mission identity and the observed repair workflow.
2. `#DevisDetTable` is read-only original-quote evidence.
3. Edit only `#DevisDetTableVal` inside `#blocDevisValide`.
4. Before the first mutation, preflight-match every planned rubrique to exactly one existing row.
5. Never click Ajouter.
6. For every approved RowOp:
   - relocate the exact row after each redraw;
   - click its column-7 pencil;
   - wait for edit mode;
   - fill validated HT/TVA/vétusté fields;
   - dispatch the required events;
   - verify the calculated TTC when available;
   - click the column-7 checkmark exactly once;
   - await and validate `updateDevisDet`;
   - wait for the redraw;
   - discard stale DOM references;
   - relocate and verify the exact read-back.
7. Trigger `DevisCalculerMontantCharge` and verify the PEC summary.
8. Never click `#DEVISDET_Btn` or invoke `garageModifierValDevis`.
9. Stop at `READY_FOR_HUMAN_REVIEW`.

The detailed step semantics, evidence levels, and failure behavior live in `docs/architecture/PORTAL_ROW_WORKFLOWS.md`;
this section is the recovery-side pointer, not a second authority.
