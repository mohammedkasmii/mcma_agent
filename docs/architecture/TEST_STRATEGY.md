# TEST STRATEGY

**Baseline:** `0290fe9…` · target design. The existing 19 tests (`docs/recovery/TEST_EVIDENCE.md`) are preserved and
extended. This strategy is the Phase 4/5 target; nothing here changes tests in this phase.

---

## 1. Unconditional production-domain blocking (highest priority)
An **autouse, session-scoped `conftest.py`** fixture installs a socket guard that **blocks any connection to
`sinauto.mamda-mcma.ma` and, by default, all non-loopback sockets** for the entire suite. It **cannot be disabled
per-test**. This is the first migration step (`ARCHITECTURE.md` §6). Tests drive only `mock_server`/fixtures. A test
that attempts a real portal connection fails loudly.

## 2. Layers
- **Pure unit** (`domain`, `mapping`, `planning`) — no I/O.
- **Property-based** (Hypothesis) — required for: monetary/tax invariants (totals to 0.01 MAD, **no negative line TVA →
  `INVALID_TAX_ALLOCATION`**), registration normalization, glass vocabulary (component×operation→19–24, ambiguity fails
  closed), labour enums (structured-first; text never overrides), origin classification (three-origin; never 4–6/13–15/
  10/11 by keyword), identity comparison (no match-by-absence), **plan determinism** (same input → identical
  `plan_hash`), malformed inputs, and job **state-transition** legality.
- **Repository contract tests** on a temporary SQLite DB (WAL): claim identity uniqueness (`account_id, portal_claim_id`,
  NOT NULL idSinistre), staging of unmatched notifications, three-poll presence transitions (complete/valid only),
  outbox atomicity (transition + event in one transaction), account-lease acquire/fence/expire.
- **Safety tests** (the component whose failure is most consequential): context-level **default-deny** aborts unknown
  requests; **final endpoints abort** (never fake-200); **dry-run constructs no writer**; write allowlist enforced;
  **charge-mutuelle fields never appear** in any allowlist or plan; route-handler exceptions abort; `service_workers`
  blocked; external domains blocked; **lease fencing** aborts a write when the token is stale.
- **Characterization tests** pinning current mapper/notification output before refactor (regression guard).
- **Integration** against an **extended `mock_server`** that adds the notification surface and the row-op endpoints the
  current mock lacks (`docs/recovery/PORTAL_CONTRACT.md` §8), plus contract fixtures for each reviewed request tuple.
- **AuthN/AuthZ tests:** Argon2id verify; no-default-credentials; permission checks per endpoint (a viewer cannot mutate);
  CSRF enforcement; session expiry/logout; SSE authorization filtering + revocation drop.
- **Migration & backup/restore tests:** each migration applies forward on a seeded DB; the backup/restore runbook is
  exercised (online backup API), since not all migrations are reversible (`DATA_MODEL.md` §10).

## 3. Determinism & import contracts
- Import-linter (or equivalent) contract test enforces `MODULE_BOUNDARIES.md` (pure modules import no I/O libs; single
  owners for Playwright/sqlite3/FastAPI; no cycles).
- Plan builders are asserted pure (no clock/random/set-order dependence).

## 4. Runner & CI
`python -m pytest` from the repo root (no `conftest`-less collection gaps). Property tests run with a bounded example
budget in CI and an extended budget nightly. The socket guard makes the whole suite safe to run offline by construction.

## 5. Coverage goals (safety-first)
100% of: the interceptor/allowlist/final-block, the identity gate, dry-run-has-no-writer, negative-TVA fail-closed, and
charge-mutuelle-never-written. These are the invariants whose regression would be most damaging.
