# LIVE WRITE EVIDENCE MATRIX

What is actually **known** about writing to the real SinAuto portal, and
what is currently believed on no evidence at all.

Written during Phase C.2. Nothing here enables a live write, and nothing
here is a contract — `mcma/portal/pilot_contracts.py` remains mock-only
and `mcma.portal.writer._require_loopback_host` still refuses any
non-loopback host before a writer context exists.

---

## Evidence levels

| Level | Means |
|---|---|
| `RECOVERED_DOM_EVIDENCE` | The working baseline addressed this selector or function against the live portal. |
| `RECOVERED_NETWORK_EVIDENCE` | The working baseline observed or awaited an actual request/response. |
| `MOCK_INFERRED` | Present only in `mock_server.py` or mock fixtures. **Never observed against SinAuto.** |
| `TARGET_POLICY` | Required by the rebuilt architecture. Says nothing about what SinAuto implements. |
| `UNCONFIRMED` | No sufficient evidence. |

A level is never promoted. Seeing
`page.expect_response(lambda r: "updateDevisDet" in r.url)` proves the old
code *waited for a response whose URL contained that substring*. It does
not prove the full path, the method, the content type, the body keys or
the response schema. Those are separate facts and are classified
separately below.

Baseline commit referenced throughout:
`0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`.

---

## Headline finding

**`createRapportDefDet` — the endpoint the current writer awaits to
persist a Mode Normal row — does not appear anywhere in the baseline.**

```
browser/mode_normal.py         0 occurrences
browser/mode_conventionne.py   0
browser/form_filler.py         0
browser/dom_helpers.py         0
browser/safety_interceptor.py  0
mock_server.py                 6
mcma/portal/writer.py          5
```

The baseline's Mode Normal path clicked the row checkmark and then
re-read the DOM. It never observed a network request for that operation
at all. So the entire Mode Normal persistence contract in the rebuilt
writer — path, method, content type, body fields, response shape — is
**`MOCK_INFERRED`**, and `docs/recovery/PORTAL_CONTRACT.md` §8's own note
that the mock is where the shape came from is consistent with that.

This is the single largest blocker to live Mode Normal writing, and it is
not a detail that can be filled in by reasoning. It has to be observed.

---

## Shared navigation and read

| Fact | Level | Source |
|---|---|---|
| Mission page route `/expertise/frontexpert` | `RECOVERED_DOM_EVIDENCE` | `core/config.py:23`, navigated `mission_navigator.py:30` |
| Search fields `#Matricule`, `#ReferenceCie` | `RECOVERED_DOM_EVIDENCE` | `mission_navigator.py:49,52` |
| Search trigger `a[onclick*='rechercheMission']` | `RECOVERED_DOM_EVIDENCE` | `mission_navigator.py:54` |
| `listeMissions` POST body keys | `MOCK_INFERRED` | mock only; the baseline clicked a control, it did not build the request |
| Claim deep link `/gestionExpert/getSinistre/idSinistre/{id}/rubrique/gestionexpert-index` | `RECOVERED_DOM_EVIDENCE` | `PORTAL_CONTRACT.md` §7, `notifications.py:99` |
| Identity readback selectors | `RECOVERED_DOM_EVIDENCE` | `mission_navigator.py:116-128` |
| Workflow detection selectors | `RECOVERED_DOM_EVIDENCE` | `mode_conventionne.py` table presence checks |

---

## MODE NORMAL

### DOM lifecycle — mostly confirmed

| Fact | Level | Source |
|---|---|---|
| `#VehRepareI` must be checked to reveal the rubriques table | `RECOVERED_DOM_EVIDENCE` | `mode_normal.py:40-44` |
| Add-row control `a.btn-success:has-text('Ajouter'), a:has-text('Ajouter +'), a[onclick*='addRow']` | `RECOVERED_DOM_EVIDENCE` | `mode_normal.py:58` |
| Editable row fields `#IdRubrique`, `#MontantHT`, `#Taxe` | `RECOVERED_DOM_EVIDENCE` | `mode_normal.py:71-74` |
| Row save is the column-7 control | `RECOVERED_DOM_EVIDENCE` | `mode_normal.py:80` |
| Persisted table `#tableRapportDet tbody tr, table.dataTable tbody tr` | `RECOVERED_DOM_EVIDENCE` | `mode_normal.py:105` |
| Temporary-row id semantics (`normal_row_{temp_id}`) | `MOCK_INFERRED` | current writer + mock only; the baseline used first-row/`:has(#MontantHT)` positional selectors instead |

### Persistence — unconfirmed

| Fact | Level |
|---|---|
| An endpoint named `createRapportDefDet` exists | `MOCK_INFERRED` |
| Exact path | `MOCK_INFERRED` |
| HTTP method (POST) | `MOCK_INFERRED` |
| Content type | `MOCK_INFERRED` |
| Request body field names | `MOCK_INFERRED` |
| Success response shape (`{"state": "success"}`) | `MOCK_INFERRED` |
| Failure response shape / reason codes | `MOCK_INFERRED` |

**`MODE_NORMAL_LIVE_WRITE_READY = false`.**

### Native calculation — blocked

The baseline called three functions **defensively**, each guarded by
`typeof … === 'function'` with the failure swallowed
(`dom_helpers.py:122-131`): `CalculerMntArrete`, `CalculerMontantDommage`,
`DevisCalculerMontantCharge`. Guarded calls of that shape are evidence
that the author *hoped* the functions existed, not that they do.

| Fact | Level |
|---|---|
| Function names exist in portal JS | `UNCONFIRMED` (defensive calls only) |
| Which function is the Mode Normal trigger | `UNCONFIRMED` |
| Completion/readiness signal | `UNCONFIRMED` — the baseline used a fixed `wait_for_timeout`, which is not a signal |
| Financial summary readback selectors | `RECOVERED_DOM_EVIDENCE` for the names below; no evidence they are populated by any trigger |

Recovered selector names (`dom_helpers.py:132-139`): `#MontantReparation`,
`#MontantTVA`, `#MontantTTC`, `#TauxVetuste`, `#MontantVetuste`,
`#MontantFranchise`, `#PartResponsabilite`, `#MontantRemise`,
`#MontantChargeSocietaire`, `#MontantChargeMutuelle`.

`PORTAL_ROW_WORKFLOWS.md` §3.1 already records this trigger as
UNCONFIRMED. This audit agrees and adds why.

**`#MontantChargeMutuelle` and `#MontantChargeSocietaire` are READ
evidence only.** The baseline wrote them directly
(`mode_normal.py:127-128`), which `BUSINESS_RULES.md` B.3 classifies as
the prohibited charge-split overwrite. That behaviour is not to be
restored under any evidence level.

---

## GARAGE CONVENTIONNÉ / PEC

### DOM lifecycle — confirmed

| Fact | Level | Source |
|---|---|---|
| Table `#DevisDetTableVal` | `RECOVERED_DOM_EVIDENCE` | `mode_conventionne.py:60` |
| Row edit control (pencil) | `RECOVERED_DOM_EVIDENCE` | `mode_conventionne.py:219-230` |
| `#MontantHTValide`, `#TaxeValide`, `#TauxVetusteValide`, `#MontantVetusteValide` | `RECOVERED_DOM_EVIDENCE` | `mode_conventionne.py:259-266` |
| `#MontantTTCValide` | `RECOVERED_DOM_EVIDENCE` | present in baseline selector set |
| Row save checkmark | `RECOVERED_DOM_EVIDENCE` | `mode_conventionne.py:291-302` |
| Row re-location by label after redraw | `RECOVERED_DOM_EVIDENCE` | `mode_conventionne.py:182-351` |
| `#DevisDetTable`, `#blocDevisValide` | `UNCONFIRMED` | not addressed by the baseline |

### Persistence — partly confirmed, and this is the strongest evidence we have

| Fact | Level | Source |
|---|---|---|
| A response whose URL contains `updateDevisDet` occurs after the row save | `RECOVERED_NETWORK_EVIDENCE` | `mode_conventionne.py:287-288` |
| HTTP status is checked against 200 | `RECOVERED_NETWORK_EVIDENCE` | `mode_conventionne.py:312` |
| Exact full path | `MOCK_INFERRED` |
| Method is POST | `MOCK_INFERRED` — the baseline matched on substring only, never on method |
| Content type | `MOCK_INFERRED` |
| Request body field names | `MOCK_INFERRED` |
| Nonce / row identifier fields | `UNCONFIRMED` |
| Response JSON schema | `MOCK_INFERRED` |

Note the baseline never compared its read-back to the intended values and
returned `True` regardless (`mode_conventionne.py:351`), so it is not
evidence that a write succeeded — only that a response arrived.

### Native calculation

| Fact | Level |
|---|---|
| `DevisCalculerMontantCharge()` is invoked | `RECOVERED_DOM_EVIDENCE` (guarded `typeof` call, `mode_conventionne.py:359-360`) |
| That it exists on the live page | `UNCONFIRMED` |
| Completion signal | `UNCONFIRMED` |
| `#DevisTvaRecupI`, `#DevisMontantChargeMutuelle`, `#DevisMontantChargeSocietaire` | `RECOVERED_DOM_EVIDENCE` |
| `#DevisMontantTVA`, `#DevisMontantTTC`, `#DevisMontantVetusteTotal`, `#DevisMontantFranchise`, `#DevisMontantRemise`, `#DevisPartResponsabilite`, `#MontantArrete`, `#BaseIndemnite` | `RECOVERED_DOM_EVIDENCE` (names appear in `mode_conventionne.py`) |
| That those fields are populated by the trigger | `UNCONFIRMED` |
| Vétusté rate derivation formula | `MOCK_INFERRED` — `writer.py` states this itself |

**`GARAGE_CONVENTIONNE_LIVE_WRITE_READY = false`.**

---

## Header fields

The rebuilt plan writes five non-table fields. Baseline evidence covers
two of them.

| Field | Selector evidence | Note |
|---|---|---|
| `ValeurVenale` | `RECOVERED_DOM_EVIDENCE` | `form_filler.py:33-37`, with a documented fallback to `ValeurVenaleEstime` |
| `ValeurVenaleEstime` | `RECOVERED_DOM_EVIDENCE` | same |
| `Kilometrage` | `UNCONFIRMED` | the baseline filled `#{field_id}` from a caller-supplied dict; no evidence this id exists |
| `NbreJourImmobilisation` | `UNCONFIRMED` | same |
| `PartResponsabilite` | `RECOVERED_DOM_EVIDENCE` as a **calculation input name** (`dom_helpers.py:134`); `UNCONFIRMED` as a writable header field |
| `ObservationMission` | `UNCONFIRMED` | not addressed by the baseline |

The baseline's `fill_main_form` skipped any field that was not present and
carried on (`form_filler.py:39-41`), so its silence is not evidence of
absence — but it is not evidence of presence either.

---

## Final actions — permanently prohibited

Never in any allowlist, at any evidence level:

`#DEVISDET_Btn` · `garageModifierValDevis` · `expertEnregistrerMission` ·
`enregistrerMission` · `#Enregistrer` · Valider · Clôturer/`cloturerMission`
· `expertCloturerMission` · `cloturerTraitement` · GED
`ajouterDocument`/`deleteDocument` · `deleteDevisDet` · `validerDevis`

Enforced by `mcma/portal/final_endpoints.py` and asserted by the safety
suite. The human performs these in their own browser.

---

## What is still needed before any live write

1. **Mode Normal row persistence** — the whole request/response contract.
   No recovered evidence exists at all.
2. **Native calculation trigger** for both workflows — which function,
   and how completion is signalled. Fixed timeouts are not a signal.
3. **Financial summary population** — that the recovered selectors are
   actually filled by that trigger.
4. **`updateDevisDet`** — method, path, content type and body keys, to
   raise it from substring evidence to a contract.
5. **Header field ids** — four of six unconfirmed.

Every one of these is an observation, not a decision. That is what
`tools/capture_sinauto_write_evidence.py` is for.

---

## Readiness

```
MODE_NORMAL_LIVE_WRITE_READY          = false
GARAGE_CONVENTIONNE_LIVE_WRITE_READY  = false
```

This is the expected and correct outcome of C.2. The purpose was to learn
exactly which evidence is missing, not to reach `true`.
