# PORTAL CONTRACT

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

The portal-facing surface the agent depends on: URLs, DOM selectors and HTTP endpoints. **Verified** items are read from the automation code. Endpoint *shapes* are corroborated by the offline replica `mock_server.py` (a hand-built mock, **not** captured live traffic) — treated here as *inference* about the real portal, not proof.

> No live portal access was performed. Selectors and endpoint names below are transcribed from source, not from a live session.

---

## 1. Base URLs (verified)

- Root: `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` (`core/config.py:22`).
- Dashboard/mission: `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/` (`core/config.py:23`).

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
