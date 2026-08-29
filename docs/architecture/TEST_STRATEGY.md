# TEST STRATEGY

**Baseline:** `0290fe9…` · target design. The existing 19 tests (`docs/recovery/TEST_EVIDENCE.md`) are preserved and
extended. This strategy is the Phase 4/5 target; nothing here changes tests in this phase.

---

## 1. Unconditional production-domain blocking (highest priority; correction #8 — defense in depth)
A single session-scoped fixture is **insufficient**: collection-time imports and subprocesses/Chromium can run before or
outside it. The block is layered, and **OS/CI egress denial is the authoritative control** — the Python-level guards are
defense-in-depth only (correction #7):
1. **Authoritative — OS/CI-level outbound blocking:** the CI job (and the documented local run) **blocks all outbound
   network** except an explicit `mock_server` loopback allowance, covering **Python, Chromium, and any subprocess** (e.g.,
   a firewall rule / network namespace / a container with no egress). This is the guarantee: it catches what an in-process
   Python guard cannot (a spawned browser, a C-extension socket, a subprocess).
2. **Defense-in-depth — guard before test collection:** a `conftest.py` at the repo root (and/or a pytest plugin
   registered via `pyproject`/`pytest.ini` entry points) installs a socket guard before collection so import-time network
   attempts fail early with a clear message. **`PYTHONSTARTUP` and `sitecustomize` are NOT relied upon as a security
   mechanism** — they are not guaranteed for non-interactive/embedded Python and can be bypassed; at most they are a
   convenience for local runs.
3. **Defense-in-depth — pytest socket blocking:** `pytest-socket` (or equivalent) disables sockets by default, allowing
   only loopback.
4. **Explicit proof test:** a dedicated test **spawns a subprocess and launches a headless Chromium** and asserts **each
   cannot reach the production host** (`sinauto.mamda-mcma.ma`) — proving the OS/CI block covers subprocesses and the
   browser, not just the test process.
Tests drive only `mock_server`/fixtures; any real-portal connection fails loudly. This is the first migration step
(`ARCHITECTURE.md` §6).

## 2. Layers
- **Pure unit** (`domain`, `mapping`, `planning`) — no I/O.
- **Property-based** (Hypothesis) — required for: monetary/tax invariants (totals to 0.01 MAD, **no negative line TVA →
  `INVALID_TAX_ALLOCATION`**), registration normalization, glass vocabulary (component×operation→19–24, ambiguity fails
  closed), labour enums (structured-first; text never overrides), origin classification (three-origin; never 4–6/13–15/
  10/11 by keyword), identity comparison (no match-by-absence), **plan determinism** (same input → identical
  `plan_hash`), malformed inputs, and job **state-transition** legality.
- **Repository contract tests** on a temporary SQLite DB (WAL): claim identity uniqueness (`account_id, portal_claim_id`,
  NOT NULL idSinistre), staging of unmatched notifications, **category-scoped** three-poll transitions using
  `poll_run_categories` (a category increments only when **that category** completed under a valid session; a failed
  category never affects another — correction #1), outbox atomicity (transition + event in one transaction), account-lease
  acquire/heartbeat/expire, **`job_inputs`** round-trip (content_hash match, expiry, missing-input → fail closed), and
  `observed_finalizations` never mutating `automation_jobs`.
  - **Cross-account integrity (correction #4):** inserting a `category_presence` row that pairs an `account_id` with
    another account's `claim_pk` **fails** (composite FK); `parent_job_id` must reference a `DRY_RUN_VERIFIED` DRY_RUN of
    the **same account+workflow** (repository invariant test).
  - **Durable enqueue & restart (correction #5):** the atomic enqueue commits `automation_jobs`(QUEUED)+`job_inputs`+
    state-version+outbox together or not at all; **crash-point tests** between enqueue / planning / execution assert:
    `QUEUED` with valid input resumes, `QUEUED` without valid input fails closed, `WRITING`/`VERIFYING` are never
    auto-resumed; the status CHECK rejects an unknown status.
- **API authorization tests (correction #3):** there is **no** `mode` field; a DRY_RUN is created only at `/jobs/dry-runs`
  and an EXECUTE only at `/jobs/{dry_run_job_id}/executions`; the executions endpoint rejects a non-`DRY_RUN_VERIFIED`
  parent, a different account/workflow, a `NEEDS_REVIEW`/`IDENTITY_FAILED` parent, mismatched `input_hash`/`plan_hash`, an
  expired input, and any client-supplied `authorized_by`; `jobs:plan` does not grant `jobs:execute`.
- **Safety tests** (the component whose failure is most consequential): context-level **default-deny** aborts unknown
  requests (GET not auto-safe); **final endpoints abort** (never fake-200); **dry-run constructs no writer**; write
  allowlist enforced; **charge-mutuelle fields never appear** in any allowlist or plan; route-handler exceptions abort;
  `service_workers` blocked; external domains blocked; **plan has no `mode`/`read_only`**; **`ExecutablePlanData` cannot be
  produced without passing authorization + `input_hash`/`plan_hash` checks**, and **`AuthorizedExecution` cannot be
  constructed without both valid `ExecutablePlanData` and a `VerifiedMissionWriter`** (correction #3); **rubrique-row
  selection by exact `IdRubrique`, exactly one match** — substring/
  first-row/positional fallback rejected, zero/multiple fail closed (F16, correction #7); **truthful readiness** — a
  "READY/Verified/Prêt" label is set only after a real check passes, never from file existence or a `finally` block
  (F12, correction #7); **portal never re-acquires the lease / never imports persistence** (import contract) and on
  heartbeat loss the write context is closed (correction #5).
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
