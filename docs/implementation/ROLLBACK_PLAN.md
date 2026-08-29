# Rollback & Recovery Strategy

Every increment is reversible; blast radius is limited by design. Rollback is per-increment first, then per-phase, then
whole-branch as a last resort.

## Principles
- **Additive-first:** INC-01..21 add new modules alongside the baseline; the baseline keeps running. Deleting baseline
  code happens **only** at INC-22 (parity) and is fully recoverable from git history.
- **Feature flags:** where old and new coexist (dashboard read source, notification store), a flag flips back instantly.
- **Reversible-where-safe migrations:** schema migrations are compatibility-aware (expand/contract); not all are
  reversible, so the safety net is the tested **backup/restore** runbook (INC-21), not a guaranteed down-migration.
- **Write-enable gate:** the live-write gate (INC-23) flips OFF instantly, reverting to read-only + dry-run.

## Per-increment rollback (summary; each increment file has the authoritative entry)
| Increment | Rollback |
|---|---|
| INC-01 | remove egress plugin/tests (additive) |
| INC-02 | delete characterization tests/fixtures |
| INC-03 | delete package skeleton + contract test |
| INC-04/05 | delete `domain`/`mapping`/`planning` (baseline mapper untouched) |
| INC-06 | revert mock-server extensions |
| INC-07/08/09 | delete new `portal` modules (baseline navigator/interceptor untouched) |
| INC-10 | delete `persistence` (no baseline dependency) |
| INC-11 | delete mutex/leases modules |
| INC-12 | delete `execution/jobs` (baseline workflow untouched) |
| INC-13 | delete vault modules (baseline `auth_setup.py` still runs, though fail-open) |
| INC-14 | flag back to legacy-JSON read; delete extractor |
| INC-15 | disable SSE route; outbox harmless if unread |
| INC-16/17 | unmount the new auth app / API |
| INC-18 | revert to loopback serve (never to plain-HTTP LAN) |
| INC-19 | re-serve the legacy static dashboard |
| INC-20 | revert to baseline logger |
| INC-21 | revert backup scripts (additive) |
| **INC-22** | **restore retired baseline files from git; re-enable legacy flags (highest blast radius — retirement list is explicit and revertible)** |
| INC-23 | flip write-enable gate OFF → read-only + dry-run; documented canary rollback |

## Phase-level rollback
Revert the phase's increments in reverse order; re-run the previous phase's gate to confirm the system returns to its
last-green state. Because baseline code is retired only at INC-22, any rollback before Phase 7 leaves the baseline intact.

## Whole-branch recovery (last resort)
`refactor/solid-architecture` retains the full history; the production baseline `0290fe9` is recoverable at any time.
The SQLite DB is recoverable via the INC-21 online-backup/restore runbook. No live-portal state is ever changed before
INC-23's supervised canary, so pre-canary rollback has no external side effects.

## Data recovery
- DB corruption/loss → restore from the latest verified online backup (INC-21).
- A partial write interrupted by a crash (WRITING/VERIFYING) → the job is `INTERRUPTED_NEEDS_HUMAN_REVIEW` with a diff
  report; a human inspects the portal; the automation never blind-replays (WORKFLOW_STATE_MODEL §7).
- Session compromise → revoke the session (INC-13), force re-login; sessions are DPAPI-encrypted and excluded from backups/logs.
