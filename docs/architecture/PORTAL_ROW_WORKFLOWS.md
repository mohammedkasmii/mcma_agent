# Portal Row Workflows

This document is the authoritative single source of truth for the explicit row-level automation workflows in the SinAuto/MCMA portal. 

The legacy concept of a single generic `write_row` is intentionally removed. Instead, automation executes narrow, explicitly typed operations bound to the deterministic repair workflow (Mode Normal vs. Garage Conventionné/PEC). The repair workflow is structural context, distinct from the authorization to write (DRY_RUN vs EXECUTE).

Live execution consumes an `AuthorizedExecution` containing approved `ExecutablePlanData`, never a bare `ProposedPlan`. The `ProposedPlan` remains a capability-neutral planning output only.

## 1. Mode Normal (Add-Row Lifecycle)

Mode Normal models an initially empty table where every planned item is added sequentially.

### Sequence
1. Verify the opened mission identity.
2. Ensure `#VehRepareI` is checked to expose the Mode Normal rubrique table.
3. For every planned rubrique in the `ExecutablePlanData`:
   - Click the green `Ajouter` / `Ajouter +` button.
   - Wait for one temporary editable row to appear.
   - Select the exact `IdRubrique` in `#IdRubrique`.
   - Fill `#MontantHT` and `#Taxe`.
   - Dispatch human-equivalent browser events: focus/value entry followed by `input`, `keyup`, `change`, and `blur`.
   - Click the temporary row’s green checkmark in column 7 exactly once.
   - Await and validate the row persistence request (`createRapportDefDet`).
   - Wait for the table redraw.
   - Relocate the persisted row in the redrawn table.
   - Read back and compare the exact `IdRubrique`, HT, and TVA.
   - Only after exact successful verification, click `Ajouter` for the next rubrique.

## 2. Garage Conventionné / PEC (Edit-Row Lifecycle)

Garage Conventionné provides a read-only table (`#DevisDetTable`) of the garage's original quote and an editable table (`#DevisDetTableVal` inside `#blocDevisValide`) for the expert's validation.

### Sequence
1. Verify the opened mission identity and expected repair workflow.
2. Detect `#DevisDetTableVal`. 
3. **Read all existing validated rows before writing.**
4. Match every planned rubrique to **exactly one** existing portal row before making the first mutation. Zero, duplicate, or ambiguous matches fail closed immediately.
5. **No `Ajouter` action is used in PEC.**
6. For every planned rubrique in the `ExecutablePlanData`:
   - Relocate the exact matched row after every previous redraw.
   - Click its pencil/edit action in column 7.
   - Wait until that row enters edit mode.
   - Fill `#MontantHTValide`, `#TaxeValide`, `#TauxVetusteValide`, and/or `#MontantVetusteValide`.
   - Dispatch human-equivalent `input`, `keyup`, `change`, and `blur` events so SinAuto's native JavaScript calculates TTC and vétusté.
   - Verify the computed `#MontantTTCValide` where exposed.
   - Click the green checkmark in column 7 exactly once.
   - Await and validate the persistence request (`updateDevisDet`).
   - Wait for redraw and discard the stale DOM reference.
   - Relocate the row, read back, and compare HT, TVA, TTC, vétusté rate, and vétusté amount.
   - Continue only on exact successful verification.

## 3. Mandatory Native Financial Recalculation

After all row operations are completed and verified, the agent **must** trigger SinAuto's native financial summary calculation. The automation must **never** invent or force its own charge-mutuelle split. Neither workflow may directly write charge-mutuelle or charge-sociétaire. Both workflows must trigger SinAuto-native calculation and verify the resulting financial summary before `READY_FOR_HUMAN_REVIEW`.

### 3.1 Mode Normal
- **Confirmed Selectors**: [UNCONFIRMED - MUST BE DISCOVERED/CONFIRMED AS G5 PRECONDITION]
- Do **not** guess or apply PEC-only `#Devis...` selectors to Mode Normal.
- Trigger the native calculation logic (exact function/event [UNCONFIRMED]).
- Read and verify all relevant fields (exact selectors [UNCONFIRMED]).

### 3.2 Garage Conventionné / PEC
- **Confirmed Selectors**: `#DevisTvaRecupI`, `#DevisMontantChargeMutuelle`, `#DevisMontantChargeSocietaire`.
- Dispatch the required change event for `#DevisTvaRecupI` if necessary.
- Invoke the confirmed native behavior (`DevisCalculerMontantCharge()`).
- Wait for the summary to update.
- Read and verify all relevant fields: `#DevisMontantChargeMutuelle`, `#DevisMontantChargeSocietaire`, total TVA, total TTC, vétusté, franchise, remise, montant arrêté, and base indemnité.

A missing, failed, or stale native financial recalculation blocks `READY_FOR_HUMAN_REVIEW` in both workflows.

## 4. Permanent Final-Action Prohibition

The automation must **never** perform dossier-level final submission, save, or validation. The terminal state of automation is `READY_FOR_HUMAN_REVIEW`. Reviewed row-level `createRapportDefDet` and `updateDevisDet` persistence remains explicitly permitted.

The agent must never click, invoke, or dispatch to:
- `#DEVISDET_Btn`
- `Valider Devis`
- `#Enregistrer`
- `Enregistrer`
- `Valider`
- `Clôturer`
- `garageModifierValDevis`
- GED/document mutations
- Delete-row action in PEC column 8
- Any equivalent endpoint or state change.

## 5. Failure Behavior

Any mismatch between the detected and planned `repair_workflow`, any unexpected read-back, any ambiguous row match, or any failure to trigger native financial recalculation must immediately fail closed and abort the execution, preserving the dossier for human intervention.
