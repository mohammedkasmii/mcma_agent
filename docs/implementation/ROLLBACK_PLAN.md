# Rollback & Recovery Strategy

Every increment is reversible; blast radius is limited by design. Rollback is per-increment first, then per-phase, then
whole-branch as a last resort.

## Principles
- **Baseline write capability is removed first and permanently (INC-00):** rollback at any later point returns to the
  last safe read-only/contained version and **never** re-enables the baseline writer. There is no configuration that
  restores it; the only live-write path is the post-G5 `VerifiedMissionWriter`.
- **Additive-first (after INC-00):** INC-01..21 add new modules alongside the (now write-contained) baseline read paths;
  full baseline retirement happens at INC-22 and is recoverable from git history — but a rollback never reinstates the unsafe writer.
- **PII safety is sticky (never rolled back below protection while data exists):**
  - **Before** any production claimant data has ever been ingested, additive modules may be removed normally.
  - **Once** production claimant data has ever been ingested, rollback must **first disable production ingestion**.
  - **While any production claimant data remains stored**, ALL G-PDR controls remain **mandatory** and may not be rolled
    back below their safe state: PII-safe/redacted logging; safe screenshot behavior; protected DB location; NTFS ACL;
    BitLocker or SQLCipher; encrypted backups; safe authenticated dashboard rendering.
  - The INC-19/20/21 controls may be removed **only after** production data is securely **purged or migrated to another
    equally protected system**. Otherwise rollback **redeploys the last safe version of those controls or stops the
    affected service** — it never reverts to the baseline logger or the unsafe legacy dashboard over production data.
- **Feature flags:** where old and new coexist (dashboard read source, notification store), a flag flips back instantly.
- **Reversible-where-safe migrations:** schema migrations are compatibility-aware (expand/contract); not all are
  reversible, so the safety net is the tested **backup/restore** runbook (INC-21), not a guaranteed down-migration.
- **Live-write authorization (INC-23) is data-driven, never a switch:** to roll back writes, **revoke/expire the approved
  `confirmed_row_ops` contract record, close every writer capability/context, and redeploy the last tested read-only
  pre-G5 release.** A `VerifiedMissionWriter` can be constructed only while valid approved `confirmed_row_ops` records
  exist for the **exact deployed commit** and every G5 requirement passes. **No boolean, environment variable, CLI option,
  or feature flag controls write authorization.**

## Per-increment rollback (summary; each increment file has the authoritative entry)
| Increment | Rollback |
|---|---|
| **INC-00** | **rollback returns to the last safe read-only / contained version and NEVER restores the unsafe baseline writer.** Baseline write capability is permanently removed (no flag/env/CLI restores it); the only live-write path is the post-G5 `VerifiedMissionWriter`. |
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
| INC-19 | **never re-serve the unsafe legacy dashboard over production data**; redeploy the last safe (escaped/CSP/authenticated) dashboard, or **stop the UI** |
| INC-20 | **never restore the baseline logger** (it leaks PII); redeploy the last PII-safe/redacted logger, or **stop the service** |
| INC-21 | backup scripts revertible **before** production data exists; **while any production claimant data remains, do NOT remove the at-rest/backup protections** (DB location, NTFS ACL, BitLocker/SQLCipher, encrypted backups) — remove only after secure purge/migration, else redeploy the last safe controls or stop the service |
| INC-22A (prod ingestion) | disable production ingestion and return to synthetic/mock data; **preserve all retained-data protections and evidence** (never delete retained records or their protections) |
| **INC-22** | redeploy the **last tested, tagged, post-INC-00 contained release**; if a preserved feature regressed, restore **only the explicitly identified safe/read-only compatibility code** for it. **Never** restore the baseline writer or a legacy write flag (both permanently removed at INC-00). |
| INC-23 | **revoke/expire the approved `confirmed_row_ops` contract record, close the writer capability, redeploy the last read-only pre-G5 release** → read-only + dry-run. No flag/env/CLI restores writing. |

## Phase-level rollback
Revert the phase's increments in reverse order; re-run the previous phase's gate to confirm the system returns to its
last-green state. Baseline **read** paths are retired only at INC-22, so a rollback before Phase 7 leaves the
**write-contained** baseline read paths intact — the baseline **writer** was already permanently removed at INC-00 and is
never restored.

## Operational rollback target (definition)
After INC-00, the **operational rollback target is always the last tested, tagged, post-INC-00 contained release**
(read-only, write capability permanently removed). The production baseline `0290fe9` is **historical/reference evidence
only** — it is **never** an operational rollback target, because it contains the unsafe writer that INC-00 removed.

## Whole-branch recovery (last resort)
`refactor/solid-architecture` retains full history for **forensic/reference** purposes. Operational recovery redeploys
the last tagged post-INC-00 contained release (above); it never checks out or runs `0290fe9`. The SQLite DB is recoverable
via the INC-21 online-backup/restore runbook. No live-portal state is ever changed before INC-23's supervised canary, so
pre-canary rollback has no external side effects.

## Data recovery
- DB corruption/loss → restore from the latest verified online backup (INC-21).
- A partial write interrupted by a crash (WRITING/VERIFYING) → the job is `INTERRUPTED_NEEDS_HUMAN_REVIEW` with a diff
  report; a human inspects the portal; the automation never blind-replays (WORKFLOW_STATE_MODEL §7).
- Session compromise → revoke the session (INC-13), force re-login; sessions are DPAPI-encrypted and excluded from backups/logs.
