# ADR-0004 — Context-level default-deny interception; permanent final-endpoint block

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
The current interceptor is page-scoped, omits the endpoints actually driven (`updateDevisDet`, `createRapportDefDet`),
lists a phantom, and **fails open** by fulfilling blocked requests with a fake `200` (`docs/recovery/KNOWN_FAILURES.md`
F8/F9). It treats GET as safe implicitly.

## Decision
Install interception at the **BrowserContext** level (`context.route("**/*", …)`) so popups/tabs/iframes are covered. A
request is allowed **only** if it matches a reviewed **contract tuple** `(host, route, method, expected-payload-shape,
capability, operation-type)`. **GET is not automatically safe.** Unknown request → **abort** (fail closed); a handler
exception → abort. `service_workers="block"`; WebSockets blocked unless an explicit reviewed contract; external domains
blocked. Write mode allows only the workflow's confirmed **row-op** contracts. A **permanent final-endpoint blocklist**
(Enregistrer/Valider/Clôture/GED/…) is enforced in **every** capability, cannot be disabled by any flag/mode, and
**aborts** (never fake-200). Enabling any live write requires **confirmed contract records + passing safety tests** (not a boolean).

## Workflow-specific row-level contracts
The only row-level persistence contracts that may ever be allowlisted are the confirmed, workflow-specific ones:
- **`createRapportDefDet`** — Mode Normal only (Ajouter/add-row lifecycle);
- **`updateDevisDet`** — Garage Conventionné/PEC only (pencil/edit-row lifecycle).

Each contract is **workflow-specific** and must include **host, route, method, payload shape, capability, and operation
type** — a contract confirmed for one workflow never authorizes the other. **Native recalculation contracts are likewise
workflow-specific** (the PEC `DevisCalculerMontantCharge()` contract does not carry over to Mode Normal, whose native
trigger contract is an unconfirmed G5 precondition — `PORTAL_ROW_WORKFLOWS.md` §3.1). **Unknown contracts fail closed**
(abort). **Dossier-level final endpoints remain permanently blocked** regardless of any confirmed row contract.

## Rubrique-row selection (correction #7 / F16)
A reviewed row-op contract carries the row's **`IdRubrique`** as its key. Row selection is by **exact `IdRubrique`** and
must match **exactly one** row; **label substring, first-row, bidirectional-substring and positional fallback are
prohibited**; zero or multiple matches **fail closed** (`SAFETY_MODEL.md` §4a). This removes the current label-text
matcher (`docs/recovery/KNOWN_FAILURES.md` F16).

## Consequences
- (+) INV-3/INV-4 become fail-closed, context-scoped, un-disableable; the old fake-success footgun is removed; row
  selection is unambiguous (F16 closed).
- (−) Every legitimate request needs a reviewed contract — a deliberate, auditable gate before writes are enabled.
