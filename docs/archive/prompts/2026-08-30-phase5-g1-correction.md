You are authorized to make a focused G1 correction that preserves the exact Mode Normal and Garage Conventionné/PEC workflows before INC-06 begins.

## 1. Repository authority and Git permissions

Work only in:

* Repository: `mohammedkasmii/mcma_agent`
* Branch: `phase5/inc-02-05-g1-domain`
* Expected starting HEAD: `5150f519f3eb411f2aeb258a51bb64fa300e1ab0`

Before editing:

1. Verify the exact branch.
2. Verify HEAD.
3. Run `git status --short`.
4. Preserve and do not inspect, stage, modify, delete, or commit unrelated/protected untracked files such as `data/` or `MCMA_REBUILD_MASTER_PROMPT.md`.
5. If branch or HEAD differs, stop and report before modifying anything.

You are authorized to:

* Edit the scoped documentation, G1 planning/domain code, and associated synthetic tests described below.
* Run tests and static verification.
* Commit the completed correction.
* Push normally to `phase5/inc-02-05-g1-domain`.

You are not authorized to:

* Force-push.
* Rebase, reset, merge, switch branches, or rewrite previous commits.
* Begin INC-06 or modify the mock portal.
* Implement Playwright/browser portal operations.
* Access the live SinAuto/MCMA platform.
* Launch a browser.
* Read or use real client dossiers.
* Read or modify `data/`, session files, credentials, cookies, or production logs.
* Modify dependencies, `requirements*.txt`, `uv.lock`, runtime configuration, database files, or CI unless a genuinely unavoidable issue is found; stop and report instead.
* Modify the contained legacy writer/browser implementation.
* Use subagents/background agents or an external second-opinion run. Work as one focused agent to avoid time and quota waste.

Use installed relevant skills if available, especially test-driven-development, modern-python, sharp-edges, insecure-defaults, and spec-to-code-compliance. Do not spend time discovering unrelated skills.

## 2. Purpose of this correction

The recovered documents contain the real browser behavior, but the later architecture generalized both portal workflows into a vague `write_row(...)` operation.

That is insufficient because the two workflows are structurally different:

* Mode Normal creates new rows in an initially empty table using `Ajouter`.
* Garage Conventionné/PEC edits existing rows in the validated-devis table using a pencil.
* Both must execute and verify SinAuto’s native JavaScript financial calculation.
* The current G1 planning implementation supports only Mode Normal and rejects conventionné input.
* The default workflow registry currently registers only `mission_normal`.

Correct the documentation and G1 planning model now. Do not implement the portal or mock yet.

## 3. Owner-approved authoritative rules

These rules supersede any conflicting or vague wording in recovery, architecture, ADR, implementation-planning, or historical analysis documents.

### 3.1 Mode Normal row workflow

The exact logical sequence is:

1. Verify the opened mission identity.
2. Ensure `#VehRepareI` is checked so the Mode Normal rubrique table is displayed.
3. The table may initially be empty.
4. For every planned rubrique:

   * Click the green `Ajouter` / `Ajouter +` button.
   * Wait for one temporary editable row to appear.
   * Select the intended exact `IdRubrique` in `#IdRubrique`.
   * Fill `#MontantHT`.
   * Fill `#Taxe`.
   * Reproduce the human-equivalent events required by SinAuto: focus/value entry followed by `input`, `keyup`, `change`, and `blur` where the confirmed contract requires them.
   * Click the temporary row’s green checkmark in column 7 exactly once.
   * Await and validate the row persistence request `createRapportDefDet`.
   * Wait for the table redraw.
   * Relocate the persisted row.
   * Read back and compare exact `IdRubrique`, HT, and TVA.
   * Only after successful verification, click `Ajouter` for the next rubrique.
5. After all rows are persisted, trigger SinAuto’s native financial calculation.
6. Wait for `MontantChargeMutuelle` and related totals to update.
7. Read back and verify that native calculation occurred.
8. A missing/failed/stale financial recalculation blocks `READY_FOR_HUMAN_REVIEW`.

Do not model Mode Normal as editing a row that already exists. It is an add-row lifecycle.

### 3.2 Garage Conventionné / PEC row workflow

Garage Conventionné contains two different tables:

* `#DevisDetTable`: garage’s original quote; read-only; never edit it.
* `#DevisDetTableVal`, inside `#blocDevisValide`: expert validated quote; this is the only editable table.

The exact logical sequence is:

1. Verify the opened mission identity and expected repair workflow.
2. Detect `#DevisDetTableVal`.
3. Read all existing validated rows before writing.
4. Match every planned rubrique to exactly one existing portal row before making the first mutation.
5. No `Ajouter` action is used in PEC.
6. Zero, duplicate, or ambiguous matches fail closed before writing.
7. For every planned rubrique:

   * Relocate the exact row after every previous redraw.
   * Click its pencil/edit action in column 7.
   * Wait until that row enters edit mode.
   * Fill `#MontantHTValide`.
   * Fill `#TaxeValide`.
   * Fill `#TauxVetusteValide` and/or `#MontantVetusteValide` according to the confirmed contract.
   * Dispatch human-equivalent `input`, `keyup`, `change`, and `blur` events so SinAuto calculates TTC and vétusté.
   * Verify the computed `#MontantTTCValide` where exposed.
   * Click the green checkmark in column 7 exactly once.
   * Await and validate `updateDevisDet`.
   * Wait for redraw.
   * Discard the stale DOM reference.
   * Relocate the row.
   * Read back and compare HT, TVA, TTC, vétusté rate, and vétusté amount.
   * Continue only on exact successful verification.
8. After all rows are verified, synchronize SinAuto’s financial summary:

   * Dispatch the confirmed required change event for `#DevisTvaRecupI`.
   * Invoke the confirmed native `DevisCalculerMontantCharge()` behavior.
   * Wait for the summary to update.
   * Read and verify the relevant fields, including `#DevisMontantChargeMutuelle`, `#DevisMontantChargeSocietaire`, total TVA, total TTC, vétusté, franchise, remise, montant arrêté, and base indemnité.
9. A failed native calculation or failed read-back prevents `READY_FOR_HUMAN_REVIEW`.

### 3.3 Charge-mutuelle decision

The agent must cause SinAuto’s own JavaScript calculation to run and must verify its output.

The agent must not:

* Invent a charge-mutuelle value.
* Replace SinAuto’s calculation with a locally invented formula.
* Add charge-mutuelle or charge-sociétaire fields to `RowOp`.
* Treat successful row writes alone as completion when the financial summary did not recalculate.

The distinction must be explicit everywhere:

* Mandatory: trigger and verify SinAuto-native recalculation.
* Prohibited: directly forcing an invented financial split.

### 3.4 Permanent final-action prohibition

The agent must never invoke or click:

* `#DEVISDET_Btn`
* `Valider Devis`
* `#Enregistrer`
* Enregistrer
* Valider
* Clôturer
* GED/document mutations
* Delete-row action in PEC column 8
* `garageModifierValDevis`
* Any equivalent final endpoint

`READY_FOR_HUMAN_REVIEW` remains the terminal automation state.

The employee performs final validation manually.

`GARAGE_CONVENTIONNE_ANALYSIS.md` currently contains a stale historical instruction saying that a production run clicks `#DEVISDET_Btn`. Mark that instruction explicitly superseded and replace it with the permanent stop-before-final-validation rule. Preserve useful DOM/network analysis in that document.

### 3.5 Mapping rules remain unchanged

Do not redesign the approved mapping rules.

Preserve:

* Ordinary original part → rubrique 1.
* Ordinary adaptable part → rubrique 2.
* Ordinary recovered/used part → rubrique 3.
* Normal/carrosserie labour → 7.
* Mechanical labour → 8.
* Painting labour → 12.
* Electrical labour → 28.
* Colle and confirmed kits → 25/26/27.
* Existing approved glass, painting-material, marbre, and parallelism rules.
* Unknown or contradictory classification fails closed.
* Decimal and deterministic mapping.
* No charge-mutuelle field in a plan.

## 4. Documentation changes

### 4.1 Create one authoritative source

Create:

`docs/architecture/PORTAL_ROW_WORKFLOWS.md`

This must be the detailed single source of truth for:

* Mode Normal row creation.
* PEC existing-row editing.
* Human-equivalent browser events.
* Persistence requests.
* Redraw and row-relocation behavior.
* Exact read-back verification.
* Mandatory native financial recalculation.
* Calculation verification.
* Permanent final-action prohibition.
* Failure behavior.
* The distinction between repair workflow and execution authorization.

Use concise cross-references from other documents instead of duplicating large, slightly different descriptions everywhere.

### 4.2 Align recovery documentation

Review and update only affected sections in:

* `docs/recovery/BUSINESS_RULES.md`
* `docs/recovery/PORTAL_CONTRACT.md`
* `docs/recovery/FEATURE_INVENTORY.md`
* `docs/recovery/SAFETY_INVARIANTS.md`
* `docs/recovery/KNOWN_FAILURES.md`
* `docs/recovery/WORKFLOW_CATALOG.md`
* `GARAGE_CONVENTIONNE_ANALYSIS.md`

Required outcomes:

* `BUSINESS_RULES.md` B.3 must say native recalculation and verification are mandatory in both workflows.
* `PORTAL_CONTRACT.md` must distinguish add-row versus edit-row lifecycle and include human event ordering, persistence endpoints, redraw and verification.
* `FEATURE_INVENTORY.md` must continue recording the recovered correct Mode Normal Ajouter loop and PEC pencil loop.
* INV-8 must mean: native calculation authoritative, mandatory trigger and verification, no invented direct split.
* F6 must distinguish the two defects:

  1. forcing an invented/direct split is wrong;
  2. failing to trigger or verify native recalculation is also wrong.
* The workflow catalog must contain both complete workflows.
* The stale `#DEVISDET_Btn` production-click step must be superseded.

Do not rewrite historical baseline evidence incorrectly. Clearly distinguish:

* What the baseline did.
* What part was useful/correct.
* What part was unsafe.
* What the target must do.

### 4.3 Align architecture documentation

Review and update affected sections in:

* `docs/architecture/DOMAIN_MODEL.md`
* `docs/architecture/SAFETY_MODEL.md`
* `docs/architecture/WORKFLOW_STATE_MODEL.md`
* `docs/architecture/MODULE_BOUNDARIES.md`
* `docs/architecture/TEST_STRATEGY.md`
* `docs/architecture/TRACEABILITY_MATRIX.md`
* `docs/architecture/adr/0002-deterministic-workflow-planning.md`
* `docs/architecture/adr/0003-read-write-capability-separation.md`
* `docs/architecture/adr/0004-network-default-deny.md`

Required architecture decisions:

1. Represent the repair workflow with a typed enum:

   * `MODE_NORMAL`
   * `GARAGE_CONVENTIONNE`

2. Do not call this field simply `mode`, because `mode` was previously confused with `DRY_RUN|EXECUTE`.

3. A typed `repair_workflow` is domain context, not write permission.

4. `ProposedPlan` may contain `repair_workflow`, while remaining:

   * capability-neutral;
   * without `read_only`;
   * without execution mode;
   * without a write capability;
   * without charge-mutuelle fields.

5. The workflow value must be included in canonical serialization and `plan_hash`.

6. The execution job still owns `DRY_RUN|EXECUTE`.

7. The parent dry-run and execute job must have the same workflow.

8. The opened portal mission’s observed repair workflow must agree with the plan before any writer operation.

9. Replace the vague single `write_row(...)` concept with explicit portal operations such as:

   * `add_normal_row(...)`
   * `edit_conventionne_row(...)`
   * `read_row(...)`
   * `verify_row(...)`
   * `trigger_native_recalc(...)`
   * `read_financial_summary(...)`
   * `verify_financial_summary(...)`

10. These are narrow explicit operations; no generic request method.

11. The workflow state model must state that calculation verification is part of `VERIFYING` and must pass before `READY_FOR_HUMAN_REVIEW`.

12. Add exact test coverage for both workflows and final-action prohibition.

Update traceability for:

* Mode Normal Ajouter lifecycle.
* PEC pencil lifecycle.
* Native recalculation.
* Financial-summary verification.
* Exact workflow agreement.
* Permanent final-action prohibition.
* F6/F7/INV-8 and related requirements.

### 4.4 Align implementation planning

Review and update affected sections in:

* `docs/implementation/increments/10-domain.md`
* `docs/implementation/increments/20-portal-safety.md`
* `docs/implementation/TEST_PLAN.md`
* `docs/implementation/TRACEABILITY_BACKLOG.md`
* `docs/implementation/REVIEW_FINDINGS.md`
* `docs/implementation/RELEASE_GATES.md`
* `docs/implementation/REBUILD_ROADMAP.md` only if a cross-reference needs alignment; do not change dependencies or invent a new increment unless strictly necessary.

Required corrections:

#### INC-05

Record the G1 correction:

* Typed repair workflow.
* Two registered plan builders.
* Both deterministic.
* Repair workflow included in plan hash.
* No execution authorization in the plan.

#### INC-06

The future mock must model UI behavior, not only endpoint existence.

Mode Normal mock behavior:

* Initially empty table.
* `#VehRepareI`.
* `Ajouter`.
* Temporary editable row.
* `#IdRubrique`, `#MontantHT`, `#Taxe`.
* Input/keyup/change/blur behavior.
* One checkmark.
* `createRapportDefDet`.
* Redraw into a persisted row.
* Native calculation and summary fields.
* Failure and stale-calculation scenarios.

PEC mock behavior:

* Read-only `#DevisDetTable`.
* Editable prepopulated `#DevisDetTableVal`.
* Pencil/edit state.
* Four validated amount/vétusté fields.
* Checkmark.
* `updateDevisDet`.
* Table redraw.
* Native `DevisCalculerMontantCharge`.
* Summary fields.
* Visible final button that safety tests prove is never clicked and whose endpoint is always blocked.

Do not implement INC-06 now; update its approved plan only.

#### INC-09

Replace generic writer planning with the two explicit mode-specific row operations and mandatory financial-summary verification.

Add planned tests covering:

Mode Normal:

* Table may start empty.
* `Ajouter` once per intended rubrique.
* No second `Ajouter` until previous row persisted and verified.
* Correct field/event sequence.
* Checkmark exactly once.
* Await `createRapportDefDet`.
* Redraw relocation.
* Exact read-back.
* Missing calculation blocks readiness.

PEC:

* Never clicks `Ajouter`.
* Never edits `#DevisDetTable`.
* All rows match before first write.
* Pencil only in exact intended row.
* Correct field/event sequence.
* Checkmark exactly once.
* Await `updateDevisDet`.
* Relocate after redraw.
* Exact read-back.
* Native calculation and summary verification.
* Never clicks delete or `#DEVISDET_Btn`.

Both:

* Workflow mismatch fails closed.
* Charge fields never appear in `RowOp`.
* Final endpoints permanently blocked.
* Native calculation is mandatory.
* Calculation failure blocks readiness.

## 5. G1 implementation correction

The current G1 code supports only Mode Normal.

Implement the smallest clean correction.

Expected production-code scope:

* `mcma/domain/enums.py`
* `mcma/planning/plan.py`
* `mcma/planning/registry.py`
* `mcma/mapping/wexia.py` only if a small typed-boundary change is truly necessary
* Relevant synthetic tests under `tests/domain/`, `tests/planning/`, and `tests/plan/`

Do not touch:

* `mcma/portal/`
* `mock_server.py`
* Legacy `browser/`
* Legacy `main.py`
* Real input folders
* Data/session files
* Dependencies or lockfiles

### 5.1 RepairWorkflow enum

Add a typed enum, with naming consistent with the project:

```python
class RepairWorkflow(...):
    MODE_NORMAL = "mode_normal"
    GARAGE_CONVENTIONNE = "garage_conventionne"
```

Use this enum rather than raw strings inside planning.

### 5.2 ProposedPlan

Add a typed field:

```python
repair_workflow: RepairWorkflow
```

Requirements:

* It is capability-neutral domain context.
* It does not authorize execution.
* It is included in canonical serialization.
* It is included in `plan_hash`.
* The plan still contains no field named `mode` or `read_only`.
* The plan still contains no charge-mutuelle fields.
* Zero steps or any `NeedsReview` remains non-writeable.

Bump `BUILDER_VERSION` because the canonical plan schema changes.

### 5.3 Plan builders

Avoid duplicating mapping and money logic.

Factor shared deterministic behavior into a private helper if appropriate, then expose:

* Existing normal builder, preserving a compatibility-safe public name if tests/imports already depend on it.
* New `build_garage_conventionne_plan(...)`.

Each builder must:

* Require the matching explicit repair workflow.
* Reject the other workflow.
* Fail closed on missing or contradictory workflow signals.
* Produce the same deterministic `RowOp` structure.
* Preserve all mapping, amount, identity and hash invariants.
* Set the correct typed `repair_workflow`.

Do not silently auto-route inside a caller that explicitly requested the wrong builder.

### 5.4 Workflow registry

Register exactly both supported workflows using canonical stable names:

* `mission_normal`
* `garage_conventionne`

Unknown names remain fail-closed.

Do not introduce aliases unless an existing documented API requires them.

### 5.5 Required tests-first implementation

Write focused failing tests first, run them, then implement minimally.

Add tests for:

1. Normal input produces `RepairWorkflow.MODE_NORMAL`.
2. Conventionné/PEC input produces `RepairWorkflow.GARAGE_CONVENTIONNE`.
3. Normal builder rejects conventionné input.
4. Conventionné builder rejects normal input.
5. Missing repair-workflow signal fails closed.
6. Contradictory normal + PEC signals fail closed.
7. Registry contains exactly both canonical workflow names.
8. Unknown registry workflow fails closed.
9. `repair_workflow` participates in canonical JSON and plan hash.
10. The same valid input produces the same plan and hash repeatedly.
11. Shuffle determinism remains true for both workflows.
12. Plans contain no `mode` or `read_only` field.
13. Plans contain no charge-mutuelle or charge-sociétaire field.
14. Both workflows preserve mandatory registration plus insurer reference/idSinistre identity.
15. Mapping rules and existing domain tests remain unchanged and green.
16. Existing characterization goldens remain intentionally historical and are not silently rewritten.

Use synthetic fixtures only. Do not add real names, plates, references, dossier IDs, policy numbers, or other PII.

If two otherwise identical fixtures differ only by repair workflow, ensure their canonical input/plan hashes reflect that difference.

## 6. Contradiction and stale-language sweep

After implementation, use `rg` to inspect all affected Markdown files and G1 code for stale or contradictory wording, including:

* `write_row`
* `trigger_native_recalc`
* `MontantChargeMutuelle`
* `MontantChargeSocietaire`
* `DEVISDET_Btn`
* `garageModifierValDevis`
* `Valider Devis`
* `Ajouter`
* `createRapportDefDet`
* `updateDevisDet`
* `mode`
* `read_only`
* `mission_normal`
* `garage_conventionne`
* `DevisCalculerMontantCharge`

Do not mechanically remove historical evidence. Mark it as baseline/historical/superseded where appropriate.

Final consistency requirements:

* No target architecture says PEC clicks `Ajouter`.
* No target architecture treats Mode Normal as editing a pre-existing row.
* No target architecture permits the automation to click `#DEVISDET_Btn`.
* No target architecture treats native recalculation as optional.
* No plan contains a charge-mutuelle value.
* No direct invented charge split is allowed.
* A failed summary calculation cannot reach `READY_FOR_HUMAN_REVIEW`.
* Repair workflow is never confused with `DRY_RUN|EXECUTE`.
* Both registry workflows exist.
* Current G1 code can build deterministic plans for both workflows.

## 7. Verification commands

Run at minimum:

```powershell
python -m pytest tests/domain tests/planning tests/plan tests/contracts -v
python -m pytest tests/ -m "not egress_proof" -v
python -m uv run --frozen lint-imports
git diff --check
git status --short
```

If the exact local shell is Bash, use the equivalent commands unchanged where possible.

Do not run local `egress_proof` tests outside their required isolated CI environment. The pushed CI run remains authoritative for those tests.

No network, browser, live portal, real dossier, session, or database access is permitted.

## 8. Review discipline

Perform one focused inline self-review after tests:

1. Sharp-edge review:

   * Repair workflow cannot authorize writes.
   * Wrong builder cannot accept the other workflow.
   * Native calculation is mandatory in docs/plans.
   * No final validation path appears.
   * No generic operation hides Mode Normal versus PEC behavior.

2. Insecure-defaults review:

   * Missing/unknown workflow fails closed.
   * No silent default to Mode Normal.
   * No fallback from exact matching to first row or label substring.
   * No optional calculation verification.

3. Spec-to-code review:

   * Both registry entries exist.
   * Plan hash binds workflow.
   * Documentation and implemented G1 behavior agree.
   * Portal implementation itself remains unstarted.

Do not invoke background subagents. Do not wait for external second-opinion services.

## 9. Commit and push

After all local verification passes:

1. Review the exact diff.
2. Confirm no unrelated file is staged.
3. Create one focused commit:

```text
fix(g1): preserve normal and PEC workflow contracts
```

4. Push normally to:

```text
phase5/inc-02-05-g1-domain
```

5. Do not force-push.
6. Do not create a pull request.
7. Do not begin INC-06.

## 10. Final report

Report:

* Starting and final SHA.
* Every modified/created file.
* RED→GREEN evidence.
* Test results.
* Import-linter result.
* Documentation contradiction result.
* Confirmation that both workflows are now represented.
* Confirmation that native calculation is mandatory and verified in the target specification.
* Confirmation that final validation remains human-only.
* Confirmation that no portal/mock/browser implementation was started.
* Confirmation that no real client data, portal, browser, session, database, dependency, or unrelated file was accessed.
* Commit SHA and pushed branch.
* CI status if immediately available; otherwise state that authoritative CI evidence is pending.

Then STOP and wait for owner review before INC-06.
