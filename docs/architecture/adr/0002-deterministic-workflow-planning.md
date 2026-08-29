# ADR-0002 — Deterministic workflow planning with typed execution plans

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
The current mapper mixes normalization, business rules and side effects, has fail-open holes (glass→1, out-of-catalogue
inference, `"mo"` labour), and workflows drive the browser imperatively with no reviewable plan. Charge-mutuelle is
force-written; negative TVA is possible.

## Decision
Introduce a **typed normalization boundary** and a **deterministic planning** step. A `WorkflowRegistry` maps a workflow
name to a **pure** plan builder `(typed input) -> ExecutionPlan`. `ExecutionPlan` is an ordered list of `RowOp`
(`rubrique_id, ht, tva, vetuste` as `Money`) plus a `needs_review` list. Rules: three-origin parts (1/2/3, no keyword
4–6/13–15/10–11); glass by component×operation (19–24, ambiguity fails closed); labour structured-first; out-of-catalogue
`mcma_rubric_id` fails closed; **negative line TVA → `NeedsReview(INVALID_TAX_ALLOCATION)`** (no clamp/redistribute).
`RowOp` has **no** charge-mutuelle field (native-only). Any `NeedsReview` ⇒ non-writeable plan. Plans are deterministic
(same input → identical `plan_hash`). EXECUTE references an approved plan and re-checks `input_hash`+`plan_hash`.

## Consequences
- (+) Reviewable, testable, reproducible plans; fail-closed by construction; charge-mutuelle un-writable structurally.
- (−) More types and a planning stage than the current inline approach.
- Enforced by property tests (determinism, money, glass, labour, identity) — `TEST_STRATEGY.md`.
