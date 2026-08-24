# MCMA assisted dossier filler

This application receives a Wexia dossier as JSON, resolves exactly one MCMA
mission, fills supported form fields, optionally prepares draft rubrique rows,
and leaves the browser open for human review.

It is deterministic and does not use an LLM.

## Current scope

- Wexia JSON validation and deterministic mapping
- Mission search using the first numeric registration block, matching the
  registration column and verifying the opened vehicle plate
- Normal and garage conventionné form preparation
- Normal rubrique creation when the table is empty
- Conventionné validated-row updates using exact rubrique matching
- Human review with an open, visible browser
- Network-level default-deny policy for MCMA writes

The following capabilities are disabled in every execution mode:

- GED upload and deletion
- mission save and closure
- final garage quote validation
- accept/refuse mission
- reform report submission
- suspicious-claim decisions
- relance writes
- all unknown MCMA POST operations

## Architecture

```text
mcma/
  domain/       Typed dossier, identity, rubrique, and execution models
  mapping/      Wexia-to-MCMA deterministic translation
  planning/     Explicit form and rubrique plan creation
  adapters/     Browser authentication, search, identity verification, form fill
  workflows/    Normal and conventionné rubrique workflows
  safety/       Default-deny network policy
  application/  Use-case orchestration
```

Dependencies point inward: browser and application layers depend on domain
models; the domain layer does not depend on Playwright, FastAPI, or Wexia.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Create the authenticated browser state on the company network:

```powershell
python auth_setup.py
```

Enter the username, password, and OTP manually. The filler never receives these
credentials.

## Commands for the platform test

### 1. Validate the JSON and inspect the plan

Run this before opening MCMA:

```powershell
python run_dossier.py --json input_dossier/dossier-se00005.json --plan-only
```

The supplied dossier currently produces four conventionné rubriques: 3, 7, 12,
and 16. The plan warns that its approved final chiffrage has no detail and has
different totals from the approved detailed estimate.

### 2. Fill only the main MCMA form

```powershell
python run_dossier.py --json input_dossier/dossier-se00005.json
```

This is the default preview mode. It fills supported form fields, prints the
rubrique plan, blocks all rubrique requests, and leaves the browser open.

### 3. Fill the form and write draft rubrique rows

```powershell
python run_dossier.py --json input_dossier/dossier-se00005.json `
  --rubric-mode draft `
  --confirm-draft-writes
```

Important: editable-table checkmarks send row-level requests immediately.
`draft` therefore permits only:

- `createRapportDefDet` / `updateRapportDefDet` for normal rubriques
- `updateDevisDet` for conventionné validated rows

It still blocks mission save, closure, `garageModifierValDevis`, GED, and every
other final or unknown MCMA mutation. A normal mission with existing rubrique
rows stops instead of creating duplicates. A conventionné rubrique must match
exactly one existing row or the workflow stops.

When review is complete, return to the terminal and press Enter to close the
controlled browser session.

## Tests

```powershell
python -m unittest discover -v
python -m compileall -q .
```

The offline suite covers mapping, decimal precision, chiffrage ambiguity,
rubrique aggregation, identifier normalization, row matching, and the network
safety policy.

## Planning API

The HTTP service is intentionally read-only:

```powershell
python main.py
python trigger.py --json input_dossier/dossier-se00005.json
```

`POST /api/v1/plan-dossier` returns a deterministic plan. Browser filling remains
an operator-visible CLI use case.
