# MCMA Rebuild — Implementation Plan (Phase 4)

> **Planning/documentation only.** No production code, tests, dependencies, configuration, databases or session
> files are changed by this phase. Implementation happens only after explicit per-increment approval (Phase 5).

## Authority & baseline
- Branch: `refactor/solid-architecture`
- **Production-code baseline:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12` (production code is unchanged from baseline).
- **Approved Phase 3 architecture revision:** `4a3483cb46fa479e4241f7c17e85c7c93c1bb791` (the approved architecture set;
  it is **not** the current HEAD — later commits add/refine this Phase 4 plan).
- Sources of truth: `docs/recovery/*` (recovered system + business rules + safety invariants + known failures) and
  `docs/architecture/*` + `docs/architecture/adr/*` (approved target).

## Package namespace (correction #4)
All **new** modules live under the top-level package **`mcma/`** (`mcma/core`, `mcma/domain`, `mcma/mapping`,
`mcma/planning`, `mcma/persistence`, `mcma/portal`, `mcma/execution`, `mcma/notifications`, `mcma/app`) to avoid
collisions with the existing baseline `core/`, `browser/`, `mapper/`, `main.py`, `mock_server.py`. Wherever an increment
writes a bare path like `domain/x.py` it denotes `mcma/domain/x.py`. Ownership/import rules and the temporary legacy
allowlist are defined in INC-03; the allowlist is removed at INC-22.

## Implementation choices (resolved — correction #6; not owner decisions)
| Concern | Decision | Justification |
|---|---|---|
| Package/dependency manager + lock | **`uv`** with `pyproject.toml` + **`uv.lock`** (hashes, fully pinned) | modern-python default; reproducible, fast, hash-locked; single lockfile |
| Import-boundary enforcement | **`import-linter`** contracts in `pyproject.toml` | declarative layered contracts; runs in CI; matches MODULE_BOUNDARIES |
| Windows single-instance mutex | **`pywin32` `win32event.CreateMutex`** (named kernel mutex) | authoritative cross-process single-instance on Windows |
| DPAPI | **`pywin32` `win32crypt.CryptProtectData`/`CryptUnprotectData`** with `CRYPTPROTECT_LOCAL_MACHINE` | the single chosen vault model (LocalMachine + NTFS ACL) |
| SSE | **`sse-starlette` `EventSourceResponse`** | maintained ASGI SSE for FastAPI; supports `Last-Event-ID` |
| Dashboard | **Hardened vanilla TS/JS with strict output-escaping + CSP, no build step** | single-office LAN, no build infra, minimal attack surface, CSP-clean/air-gap-friendly |
| Structured logging | **stdlib `logging` + a JSON formatter + a redaction filter** (no new runtime dep) | no dependency; deterministic; redaction enforced by a filter |
| Dependency pinning + Py 3.14 | **all deps pinned+hashed in `uv.lock`; a CI matrix job runs the suite on Python 3.14** | INC-03 acceptance verifies each dep (playwright, pydantic, fastapi, argon2-cffi, sse-starlette, pywin32) has a working 3.14 wheel; a dep lacking 3.14 support is escalated as an owner decision, not silently downgraded |

These replace all prior "A or B" / "optional" / "where feasible" wording in the plan. Genuine **owner** decisions (not
resolved here) are listed at the end of `REVIEW_FINDINGS.md`.

## How to use this plan
1. Read `REBUILD_ROADMAP.md` for the increment list, execution order, dependency graph and critical path.
2. Each increment is fully specified in `increments/*.md` with a fixed field set (see below).
3. `TEST_PLAN.md` is the cross-cutting test strategy; `TRACEABILITY_BACKLOG.md` proves nothing was dropped from Phase 3.
4. `RELEASE_GATES.md` lists the safety gates that block progression; `ROLLBACK_PLAN.md` is the recovery strategy.
5. `REVIEW_FINDINGS.md` records the post-plan reviews (contradiction, traceability, spec-to-code, sharp-edges,
   insecure-defaults, test-strategy, DB/migration, second-opinion) and their accepted/rejected/deferred outcomes.

**Execution discipline (from the loaded skills):** every increment is **tests-first** (TDD Iron Law — no production code
without a failing test first). **The unit of work is one TDD micro-cycle per listed test** — write the failing test →
run it → watch it fail for the right reason → minimal code → run → green → commit — which *is* the bite-sized (≈2–5 min)
step; each increment's "tests-first" list enumerates those cycles in order. **Large increments are split into
subincrements** (INC-10A/10B, INC-12A/12B, INC-13A/13B, INC-17A/17B, INC-19A/19B, INC-22A/22B — see their files) so each
subincrement is a single reviewable, independently-testable deliverable. The literal numbered per-file/per-command task
breakdown for a subincrement is produced at execution time by the `superpowers:subagent-driven-development` flow from the
subincrement's test list; this plan is not claiming a pre-written 2–5 min bullet for every line. Increments are
**feature-flagged** where old and new behavior coexist, **fail-closed**, and **independently verifiable** offline.

## Global constraints (apply to every increment)
- **Live form filling is PROHIBITED** until every write-safety gate (INV-1..INV-4, INV-6..INV-8) is implemented and
  verified, AND the endpoint-contract confirmation + write-enable gate (INC-23) has passed. No increment enables a live
  row write before then. **This prohibition binds the BASELINE too:** the first increment (INC-00) structurally disables
  the baseline's own live-write entrypoints and LAN exposure for the entire rebuild (the baseline is additive and would
  otherwise keep running its known-unsafe writer). INC-00 is the sole pre-INC-22 baseline edit and only *removes* capability.
- **No test may contact the live portal** (`sinauto.mamda-mcma.ma`). INC-01 establishes unconditional egress blocking
  and must land before any browser-related test or code.
- **Decimal** for all money; **fail-closed** for all mapping/identity/tax/mission ambiguity.
- Python **3.14** (baseline interpreter); dependencies are managed with **`uv`** and fully pinned+hashed in **`uv.lock`**
  (see §Implementation choices); a CI job runs the suite on Python 3.14 and INC-03 verifies each dependency has a working
  3.14 wheel.
- Windows single on-prem server, **one Uvicorn worker**; the OS single-instance mutex + one write-capable service
  process is the authoritative single-writer guarantee (the DB lease is coordination + loss detection only).
- `part_type` means **origin only** (never glass family). Charge-mutuelle is **native-only** and never written.

## Per-increment field set (defined once; used by every increment)
ID & title · purpose/outcome · why here (position rationale) · prerequisites & dependencies · recovery features /
INV / F-items / ADRs addressed · baseline files modified/retired · target modules/files introduced · DB migration
impact · dependency/config impact · feature flags / compatibility adapters · out-of-scope · tests-first (names) ·
initial failing-test expectation · mock-server / portal-contract fixtures · implementation steps (safe order) ·
acceptance criteria · safe offline verification commands · safety gates that block progression · expected git-diff
scope · rollback procedure · risks & failure behavior · Definition-of-Done checklist · approval boundary.

## Document map
- `REBUILD_ROADMAP.md` — increments, order, dependency graph, critical path, phase gates.
- `increments/00-test-safety.md` — INC-00 (baseline containment), INC-01, INC-02.
- `increments/10-domain.md` — INC-03, INC-04, INC-05.
- `increments/20-portal-safety.md` — INC-06, INC-07, INC-08, INC-09.
- `increments/30-persistence.md` — INC-10, INC-11, INC-12, INC-13.
- `increments/40-notifications-events.md` — INC-14, INC-15.
- `increments/50-api-auth.md` — INC-16, INC-17, INC-18.
- `increments/60-dashboard-ops.md` — INC-19, INC-20, INC-21.
- `increments/70-cutover.md` — INC-22, INC-23.
- `TEST_PLAN.md` · `TRACEABILITY_BACKLOG.md` · `RELEASE_GATES.md` · `ROLLBACK_PLAN.md` · `REVIEW_FINDINGS.md`.
