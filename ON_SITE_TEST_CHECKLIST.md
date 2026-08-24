# MCMA on-site test checklist

Use this sequence for the first company-network run. Stop at the first mismatch;
do not improvise selectors or choose another search result.

## Before opening MCMA

- [ ] Pull/open the reviewed branch and confirm `git status` has no unexpected changes.
- [ ] Activate the Python virtual environment.
- [ ] Install dependencies and Chromium if this computer is new.
- [ ] Run `python -m unittest discover -v` and confirm all tests pass.
- [ ] Run the plan:

```powershell
python run_dossier.py --json input_dossier/dossier-se00005.json --plan-only
```

- [ ] Confirm the plan says `conventionne`.
- [ ] Confirm rubriques 3, 7, 12, and 16 and their HT/tax/TTC totals with the human dossier source.
- [ ] Resolve the warning about the detailed estimate versus the final estimate. Do not continue if the operator says the final totals must be used.

## Authentication

```powershell
python auth_setup.py
```

- [ ] Complete login and OTP manually.
- [ ] Confirm the script reports that the dashboard was detected and the session was saved.

## First browser run — no rubrique writes

```powershell
python run_dossier.py --json input_dossier/dossier-se00005.json
```

- [ ] Confirm the numeric plate search returns exactly one row in the registration column.
- [ ] Confirm the opened mission registration is correct.
- [ ] Confirm the terminal reports non-empty mission and claim IDs without displaying another dossier.
- [ ] Review every filled field against the JSON/source dossier.
- [ ] Record fields reported as missing, read-only, or unavailable.
- [ ] Do not click Enregistrer, Clôturer, Valider devis, GED, accept/refuse, reform, or relance actions.
- [ ] Press Enter in the terminal to close the controlled browser.

## Second browser run — draft rubrique row updates

Only continue after the form-only run selected the correct mission and the four
rubrique totals were approved.

```powershell
python run_dossier.py --json input_dossier/dossier-se00005.json `
  --rubric-mode draft `
  --confirm-draft-writes
```

This run permits row-level `updateDevisDet` requests. It still blocks the final
`garageModifierValDevis` request and all unknown MCMA writes.

- [ ] Confirm each planned rubrique matches exactly one existing validated row.
- [ ] After each row, confirm HT, tax, TTC, and depreciation values in the table.
- [ ] Confirm no unplanned table row changed.
- [ ] Confirm the overall totals shown by MCMA equal the plan.
- [ ] Leave the final quote-validation button untouched.
- [ ] Press Enter in the terminal to close the controlled browser.

## Information to bring back after the test

- Browser/terminal error text for any stopped step.
- Screenshot of the relevant table with personal identifiers covered.
- The list of fields that were filled, skipped, or calculated by MCMA.
- Whether each rubrique update returned a visible success message.
- Whether MCMA reformatted money or dates after editing.
- Whether the detailed estimate or final estimate is the business-approved source.

Do not change the code on-site to bypass an exact-match, row-match, or network
policy failure. Capture the evidence and fix the contract offline.
