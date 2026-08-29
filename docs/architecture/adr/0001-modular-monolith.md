# ADR-0001 — Incremental modular monolith over service decomposition

**Status:** Accepted (design). **Baseline:** `0290fe9…`.

## Context
One on-prem office server, a handful of accounts (MAMDA/MCMA × Oujda/Nador), low concurrency. The current code is a flat
FastAPI + Playwright script with safety and maintainability defects (`docs/recovery/*`). We must fix safety while
preserving working features, incrementally.

## Decision
Adopt an **incremental modular monolith**: one FastAPI service (one Uvicorn worker) with internally layered modules
(`core, domain, mapping, planning, persistence, portal, execution, notifications, app, web`) and a one-directional
dependency rule. A single `portal` gateway owns Playwright and all capability/interception logic. Persist to SQLite WAL.
Design module seams so `portal`/`execution` could later be extracted into a worker process **if** load demands it.

## Alternatives
- **Decomposed services + broker** — fault isolation and horizontal scale, but heavy for a single office; distributed
  default-deny and cross-process single-writer add risk/ops cost with no load to justify them.
- **Patch-in-place** — smallest change, but leaves capability-separation and maintainability defects.

## Consequences
- (+) Centralized, provable safety; low ops; incremental migration; trivial rollback/backup.
- (−) Shared failure domain; Playwright work must be isolated from the request loop; vertical scaling only.
- Correctness of per-account single-writer relies on the DB lease (ADR-0007), not on process topology.
