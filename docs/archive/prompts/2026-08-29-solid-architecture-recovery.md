You are the recovery lead, senior software architect, safety reviewer and implementation planner for my MCMA SinAuto automation project.

## Repository authority

The current branch must be:

refactor/solid-architecture

This branch contains my stable working implementation.

Treat the code on this branch as the only source of truth.

Do not inspect, compare, merge, cherry-pick or copy code from other branches.

Do not rewrite the project from scratch.

Do not replace working code with generic templates, speculative abstractions, placeholder services, mocks presented as implementations or a new disconnected project.

The objective is to:

1. Understand the stable project completely.
2. Preserve every working feature.
3. Document the current implementation.
4. Detect problems and risks.
5. Design the best architecture for improving it.
6. Produce a complete incremental implementation plan.
7. Implement only after explicit approval, one phase at a time.
8. Prove that every implementation phase works.

## Approval gates

You must work in separate phases.

Never begin the next phase without my explicit approval.

The phases are:

1. Repository analysis
2. Recovery documentation
3. Architecture design
4. Implementation planning
5. Incremental implementation
6. Final verification

For your first response, perform Phase 1 only and then stop.

## Working principles

* Preserve proven behaviour before improving architecture.
* Prefer incremental refactoring over a big-bang rewrite.
* Base conclusions on repository evidence.
* Clearly distinguish verified facts from assumptions.
* Cite exact files, classes, functions, selectors, routes and tests.
* Never claim something works merely because a function exists.
* Never claim completion without verification evidence.
* Do not expose cookies, passwords, tokens, session contents or personal data.
* Preserve any existing uncommitted user changes.
* If the working tree is dirty, report it and stop before modifying anything.
* Do not upgrade dependencies unless a later approved plan explicitly requires it.

## Selective use of installed skills

Use installed skills only when appropriate for the current phase.

Do not activate every plugin simultaneously.

### During repository analysis

Use:

* Superpowers for disciplined investigation and planning.
* audit-context-building for systematic codebase understanding.
* modern-python for Python-specific analysis.
* Pyright LSP for definitions, references and diagnostics.
* backend-development for FastAPI and backend architecture analysis.
* Context7 only when documentation for the exact installed dependency version is needed.
* spec-to-code-compliance to compare requirements and code.
* insecure-defaults to identify fail-open behaviour.
* sharp-edges to identify dangerous APIs and error-prone design.
* supply-chain-risk-auditor to inspect Python and npm dependencies.
* PR Review Toolkit for a read-only quality review.

Do not use during initial analysis:

* Playwright against the live MCMA platform.
* frontend-design.
* code-simplifier.
* commit-commands.
* git-cleanup.
* full-stack orchestration.
* implementation agents.
* automatic fixing or refactoring.

### During architecture design

Use:

* Superpowers.
* backend-development.
* spec-to-code-compliance.
* insecure-defaults.
* sharp-edges.
* Context7 when version-specific technical facts are needed.
* second-opinion after the first architecture draft.

A second opinion is advisory. Verify its suggestions instead of accepting them automatically.

### During implementation

Use only after approval:

* Superpowers.
* modern-python.
* Pyright LSP.
* Context7.
* unit-testing.
* property-based-testing.
* debugging-toolkit.
* security-guidance.

### During final review

Use:

* PR Review Toolkit.
* spec-to-code-compliance.
* differential-review.
* security-guidance.
* second-opinion.
* code-simplifier only after behaviour is correct and tests pass.

## MCMA features to recover and preserve

Analyse the actual code and determine how each of these is implemented:

* Manual login and OTP.
* Saving the authenticated Playwright session.
* Restoring and validating saved sessions.
* Detecting expired sessions.
* Account handling.
* Mission searching.
* Mission-result selection.
* Opening a mission.
* Verifying mission identity.
* Reading dossier JSON.
* Validating dossier input.
* Form-filling agents.
* Normal repair workflows.
* Garage conventionné workflows.
* Rubrique discovery.
* Rubrique mapping.
* Row editing.
* Native portal calculations.
* Monetary calculations.
* Notification extraction.
* Relance extraction.
* Dashboard.
* FastAPI endpoints.
* SSE or live events.
* Screenshots and diagnostics.
* Readiness reports.
* Tests and fixtures.
* Windows launchers and employee-facing startup process.

For every feature, report:

* Status: verified, partially verified, inferred, broken or missing.
* Entry point.
* Files and functions involved.
* Input and output.
* Browser selectors or HTTP endpoints involved.
* External side effects.
* Existing tests.
* Missing tests.
* Risks.
* Evidence supporting the status.

## Known platform information

Base URL:

https://sinauto.mamda-mcma.ma/SinAuto_MCMA/

Mission route:

/expertise/frontexpert/

Authentication includes manual human login and OTP.

Saved authentication state may use:

mcma_auth_state.json

Known historical commands may include:

python auth_setup.py

python run_dossier.py --json input_dossier/dossier-se00005.json --plan-only

Verify these commands against the repository. Do not assume they still apply.

Notifications may use AJAX/DataTables extraction with `length=-1`. Verify this from code.

Oujda and Nador are account types or notification scopes used from the same office. Do not interpret them as separate city deployments.

## Mission-safety requirements

Before any write-capable operation, the system must:

1. Search using available mission identifiers.
2. Require exactly one unique match.
3. Stop on zero matches.
4. Stop on multiple matches.
5. Never select the first row as a fallback.
6. Open the candidate mission.
7. Verify registration, insurer reference, internal identifiers and every other available identifier.
8. Stop if verification is incomplete or contradictory.

Partial matches must never proceed to writes.

## Business mapping requirements

All parts belong to Fournitures Carrosserie and are classified by origin:

1. FOURNITURES CARROSSERIE (ORIGINES)

   * OEM, original, origine, neuf or `is_original=true`.

2. FOURNITURES CARROSSERIE (ADAPTABLES)

   * Adaptable, equivalent or aftermarket.

3. TOTAL PIECES OCCASIONS / RECUPERABLES

   * Used, occasion, récupération or récupérable.

Special rubriques include:

* Rubrique 7: MAIN D’OEUVRE CARROSSERIE
* Rubrique 8: MAIN D’OEUVRE MECANIQUE
* Rubrique 16: PEINTURES ET INGREDIENTS
* Rubrique 20: REMPLACEMENT VITRE
* Rubrique 22: REMPLACEMENT PARE-BRISE
* Rubrique 25: COLLE
* Rubrique 26: KIT COLLE PARE-BRISE/LUNETTE ARRIERE
* Rubrique 27: KIT COLLE VITRE

Unknown part types and unknown rubriques must fail closed.

Never silently map an unknown value to a default rubrique.

Use Decimal, not binary floating point, for monetary calculations.

Do not force or overwrite charge mutuelle.

Recover glass mappings, TVA, depreciation/vétusté and other calculations from code and evidence. Do not guess them.

## Garage conventionné requirements

The existing implementation may use:

#DevisDetTableVal

The known interaction is:

1. Select the row’s pencil/edit control.
2. Fill allowed row values such as HT, TVA and vétusté.
3. Use the green per-row checkmark.
4. Allow the portal to perform its native recalculation through `updateDevisDet`.

Verify this from the code.

The green per-row checkmark performs a real write. It must never be used in:

* plan-only;
* dry-run;
* preview;
* repository analysis;
* architecture work;
* offline tests;
* reconnaissance.

The final quote-saving action associated with `garageModifierValDevis`, `#DEVISDET_Btn` or an equivalent final action must remain permanently blocked.

## Permanent safety rules

The following actions must remain technically blocked:

* GED upload.
* Final Validation.
* Clôture.
* Final Enregistrer.
* Final garage quote save.
* Relance mutation.
* Any equivalent irreversible or final portal action.

Human final validation is mandatory.

Dry-run, preview and plan-only modes must be technically incapable of writes. A boolean instruction such as `if preview: do not click` is not sufficient if the session still has write-capable network access.

The architecture must consider:

* Separate read-only and write-capable sessions or capabilities.
* Default-deny network policy.
* Explicit allowlist for permitted row-level operations.
* Permanent blocklist for final endpoints.
* Read-before-write.
* Diff-before-write.
* Verify-after-write.
* Audit logging without secrets.
* Idempotency.
* Resumability.
* Per-account execution locking.
* Fail-closed behaviour.

## Known regressions to search for

Determine whether the current code is protected against:

* Preview clicking row checkmarks.
* Preview POSTing `updateDevisDet`.
* First-row mission fallback.
* Partial matches proceeding to writes.
* `LibRubrique` versus `_label` mismatches.
* Selecting the wrong rubrique row.
* Unknown mappings falling back to defaults.
* Repair mode being reported as ready without verification.
* Final endpoints protected only by prompt instructions.
* Forced charge-mutuelle overwrite.
* Incorrect glass mapping.
* Incorrect depreciation logic.
* Money calculated with floats.
* Dry-run retaining access to write endpoints.

Report evidence for each one.

## Safe testing rules

You may run safe offline tests during analysis.

Before executing a test:

1. Inspect what it runs.
2. Confirm that it cannot reach the live MCMA platform.
3. Confirm it cannot use real session state.
4. Confirm it cannot perform browser writes.
5. Prefer fixtures, mocked routes, saved HTML and sanitized responses.

Never run live browser automation during analysis.

Do not open or print the contents of authentication-state files.

Record:

* Exact test command.
* Result.
* Passed, failed and skipped counts.
* Important warnings.
* Whether the working tree changed.

## Phase 1 — Repository analysis

Perform only this phase first.

Steps:

1. Confirm:

   * current branch;
   * commit SHA;
   * git status;
   * Python and Node versions if relevant.

2. Inspect:

   * repository tree;
   * README;
   * CLAUDE.md;
   * dependency files;
   * entry points;
   * configuration;
   * launch scripts;
   * application modules;
   * tests;
   * existing documentation.

3. Trace all working features.

4. Run safe offline tests.

5. Analyse:

   * architecture;
   * module responsibilities;
   * dependencies;
   * coupling;
   * duplication;
   * error handling;
   * state management;
   * browser boundaries;
   * security;
   * testability;
   * maintainability;
   * observability.

6. Perform a read-only review using the relevant installed skills.

7. Return:

   * confirmed branch and SHA;
   * git status;
   * project structure;
   * feature inventory;
   * important workflows;
   * entry points;
   * safe tests executed and exact results;
   * architectural problems;
   * safety risks;
   * regressions discovered;
   * missing tests;
   * unclear requirements;
   * recommended next step.

8. Explicitly confirm:

   * no production code was modified;
   * no other branch was inspected;
   * no live MCMA access occurred;
   * no session secrets were exposed.

Stop and wait for my approval.

## Phase 2 — Recovery documentation

Begin only when I approve Phase 1.

You may create documentation files, but do not modify production code.

Create or update:

docs/recovery/BASELINE.md
docs/recovery/SYSTEM_OVERVIEW.md
docs/recovery/FEATURE_INVENTORY.md
docs/recovery/WORKFLOW_CATALOG.md
docs/recovery/PORTAL_CONTRACT.md
docs/recovery/BUSINESS_RULES.md
docs/recovery/SAFETY_INVARIANTS.md
docs/recovery/KNOWN_FAILURES.md
docs/recovery/TEST_EVIDENCE.md
docs/recovery/OPEN_QUESTIONS.md

Every document must:

* Include the baseline commit SHA.
* Cite repository evidence.
* Separate facts from recommendations.
* Avoid secrets and personal data.
* Preserve existing verified business rules.
* Avoid claims that cannot be proven.

Stop after creating and reviewing the recovery documents.

## Phase 3 — Architecture design

Begin only after I approve the recovery documents.

Do not modify production code.

First, describe the current architecture.

Then compare at least two realistic improvement strategies.

Prefer an incremental modular-monolith approach unless repository evidence demonstrates that another architecture is better.

The proposed architecture must address:

* Workflow registry.
* Typed workflow plans.
* Deterministic execution.
* Read/write capability separation.
* Technically write-incapable dry-run.
* Mission identity gates.
* Default-deny network policy.
* Forbidden final endpoints.
* Decimal money.
* Fail-closed mapping.
* Audit trail.
* SQLite transactions and event outbox where appropriate.
* Idempotency and resumability.
* Per-account lock.
* Multi-account session handling.
* Account-scoped notifications.
* Separation between portal state and employee-work state.
* FastAPI and dashboard boundaries.
* SSE event delivery if appropriate.
* Testing, deployment and rollback.

Create:

docs/architecture/ARCHITECTURE.md
docs/architecture/MODULE_BOUNDARIES.md
docs/architecture/DOMAIN_MODEL.md
docs/architecture/WORKFLOW_STATE_MODEL.md
docs/architecture/SAFETY_MODEL.md
docs/architecture/DATA_MODEL.md
docs/architecture/API_CONTRACTS.md
docs/architecture/TEST_STRATEGY.md
docs/architecture/THREAT_MODEL.md
docs/architecture/TRACEABILITY_MATRIX.md
docs/architecture/adr/

Use second-opinion to critique the first architecture proposal.

Evaluate its findings and accept only evidence-backed improvements.

Stop after completing the architecture documents.

## Phase 4 — Implementation planning

Begin only after architecture approval.

Do not modify production code.

Produce an incremental migration plan. Do not propose a complete rewrite.

Every implementation phase must contain:

* Objective.
* Behaviour being preserved.
* Tests written first.
* Files and modules affected.
* Implementation steps.
* Safety gates.
* Verification commands.
* Rollback procedure.
* Definition of done.
* Explicit non-goals.

Create:

docs/planning/REBUILD_ROADMAP.md
docs/planning/IMPLEMENTATION_PLAN.md
docs/planning/VERIFICATION_MATRIX.md
docs/planning/ROLLBACK_PLAN.md
docs/planning/RELEASE_GATES.md

The early implementation order should prioritize:

1. Production-domain blocking in tests.
2. Characterization tests for working behaviour.
3. Typed inputs and plans.
4. Read/write capability separation.
5. Mission identity verification.
6. Permanent forbidden-endpoint blocking.
7. Controlled workflow migration.
8. Dashboard and usability improvements only after core safety.

Stop after planning.

## Phase 5 — Incremental implementation

Begin only after I approve the plan and authorize a specific phase.

Before editing:

1. Confirm the current branch.
2. Confirm the working tree status.
3. Ensure implementation occurs on a dedicated rebuild branch created from `refactor/solid-architecture`.
4. Restate the exact authorized scope.

For every implementation phase:

1. Write or improve tests first.

2. Implement only the authorized scope.

3. Use Pyright and relevant linters.

4. Run unit and integration tests.

5. Use property-based testing for:

   * identifiers;
   * registration normalization;
   * mappings;
   * monetary calculations;
   * malformed inputs;
   * state transitions.

6. Use debugging-toolkit when tests fail. Identify the root cause before changing code.

7. Run security checks.

8. Compare behaviour with the recovery documentation.

9. Do not begin the next phase.

10. Provide exact evidence and wait for approval.

## Phase 6 — Final verification

After an implementation phase passes tests:

1. Use spec-to-code-compliance.
2. Use PR Review Toolkit.
3. Use differential-review for security-sensitive changes.
4. Use security-guidance.
5. Use second-opinion for important architecture or safety changes.
6. Evaluate findings and fix only confirmed issues.
7. Run all tests again.
8. Use code-simplifier only on modified code and only after tests pass.
9. Run tests again after simplification.

Playwright verification is permitted only with:

* offline fixtures;
* mocked responses;
* a safe non-production environment;
* or separate explicit authorization.

Block the live MCMA domain during automated tests.

Never treat a screenshot alone as proof of correct backend state.

## Final completion standard

A phase is complete only when:

* Requirements are traceable to code and tests.
* Tests pass.
* No forbidden action is reachable.
* Dry-run cannot write.
* Mission identity is verified.
* Unknown mappings fail closed.
* Monetary calculations use Decimal.
* The working tree contains only authorized changes.
* Verification evidence is reported.
* Rollback is documented.
* Human final validation remains mandatory.

Start now with Phase 1 only.

Do not create documents yet.
Do not modify code.
Do not inspect other branches.
Do not access the live MCMA platform.
Stop after the repository analysis and wait for my approval.
