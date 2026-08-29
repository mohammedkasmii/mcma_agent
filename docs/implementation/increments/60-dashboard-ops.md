# Phase 6 — Dashboard, observability, operations

---

## INC-19 — Dashboard migration: XSS removal, truthful readiness, no demo-as-real

- **Purpose/outcome:** Rebuild the employee dashboard against the authenticated API + SSE with **safe rendering** (no
  unescaped `innerHTML`; strict output-escaping in a **hardened vanilla JavaScript** render layer — **no TypeScript, no
  build step**; **CSP enforced**), **truthful readiness** (labels from
  real checks, never a `finally` block or file existence), and **no fabricated demo data rendered as real**.
- **Why here:** depends on the authenticated API (INC-17) and SSE (INC-15).
- **Prerequisites:** INC-15, INC-17.
- **Addresses:** F12 (false READY/Prêt), F22 (XSS), F27 (demo-as-real); INV-10.
- **Baseline files modified/retired:** `static/index.html`, `static/app.js`, `static/style.css` are replaced by the new
  dashboard; the baseline static app is retired only after parity (INC-22).
- **Target modules/files introduced:** `mcma/web/` (new dashboard — **hardened vanilla JavaScript, no TypeScript, no
  build step**, strict escaping + CSP), served by `mcma.app` over TLS. Tests under
  `tests/web/` (unit tests for the escaping/render helpers) + a headless-DOM safety test.
- **DB migration impact:** none.
- **Dependency/config impact:** none — no build tool (hardened vanilla JavaScript, no build step).
- **Feature flags/adapters:** the new dashboard is served at the authenticated path; the legacy static app is removed at parity.
- **Out-of-scope:** any write UI for missions (final validation remains a human action in the real portal).
- **Tests-first:** **`test_portal_data_is_escaped_not_innerHTML`** (a `<script>`/quote in a field cannot break out);
  `test_readiness_label_reflects_real_check_not_finally_block`; **`test_no_sample_data_rendered_as_real`**;
  `test_action_updates_require_auth_and_csrf`.
- **Initial failing-test expectation:** fail (new dashboard/helpers absent).
- **Mock/fixtures:** a headless DOM (jsdom-equivalent) or Playwright-against-mock for the escaping test.
- **Implementation steps:** render helpers with escaping → readiness from real state → remove sample-data default →
  wire to authenticated API + SSE.
- **Acceptance criteria:** no unescaped interpolation; readiness truthful; no demo-as-real; actions authenticated.
- **Safe offline verification:** `python -m pytest tests/web -v` (+ DOM/mock test).
- **Safety gates:** none new; UI-safety gate.
- **Expected git-diff scope:** `web/*`, `tests/web/*`.
- **Rollback:** **never re-serve the unsafe legacy dashboard over production claimant data.** Redeploy the **last safe
  (escaped/CSP/authenticated) dashboard**, or **stop the UI** if no safe version is available. (Before any production
  claimant data has ever been ingested, the additive dashboard module may simply be removed.)
- **Risks/failure behavior:** rendering defaults to escaped output; unknown/failed loads show an explicit error, not demo data.
- **Subincrement split (correction #7):**
  - **INC-19A** — the hardened render layer: strict output-escaping helpers + **CSP** + truthful-readiness helpers
    (real-check-driven); tests: escaping (breakout attempts), readiness-not-from-finally, no-sample-data-default.
  - **INC-19B** — wire the dashboard to the authenticated API + SSE, remove demo-as-real default, authenticated+CSRF
    action updates; tests: action-auth/CSRF, live-data-only, SSE-consumption.
- **Definition of Done:** XSS/readiness/demo tests green.
- **Approval boundary:** stop before INC-20.

---

## INC-20 — Structured logging + PII redaction + screenshot retention + audit + real health

- **Purpose/outcome:** Replace the whole-file JSON logger with structured, leveled logging that **redacts PII and
  secrets**, gives correlation/job ids, writes the DB **audit trail** (hashes only), retains screenshots with unique
  names + retention, and provides a **real** `/health`+`/ready`.
- **Why here:** observability underpins safe operation and incident response; depends on persistence.
- **Prerequisites:** INC-10.
- **Addresses:** INV-10; F21 (PII in logs), F29 (silent excepts), F32 (screenshot name collisions), F12(readiness in logs).
- **Baseline files modified/retired:** baseline `core/logger.py` is superseded; retired at parity (INC-22).
- **Target modules/files introduced:** `core/logging.py` (structured + redaction filter), `core/screenshots.py` (unique
  names + retention), `persistence/audit.py` (hashes only), real health/ready in `app/api/health.py`. Tests under
  `tests/core/logging/`.
- **DB migration impact:** uses `audit_events`.
- **Dependency/config impact:** **stdlib `logging` + a JSON formatter + a redaction filter** (no new runtime dependency — resolved choice, README §Implementation choices).
- **Feature flags/adapters:** none.
- **Out-of-scope:** external log shipping.
- **Tests-first:** **`test_logs_never_contain_cookies_tokens_or_pii`** (redaction filter over representative records);
  `test_no_silent_except_swallows_error` (errors are logged with context); `test_screenshot_names_unique_no_collision`;
  `test_audit_events_store_hashes_only`; `test_health_ready_reflect_real_dependencies`.
- **Initial failing-test expectation:** fail (modules absent).
- **Mock/fixtures:** in-memory log capture; temp DB.
- **Implementation steps:** redaction filter → structured logger → unique screenshot names + retention → DB audit → real health/ready.
- **Acceptance criteria:** no PII/secret in logs; audit hashes only; health truthful.
- **Safe offline verification:** `python -m pytest tests/core/logging -v`.
- **Safety gates:** none new; observability gate.
- **Expected git-diff scope:** `core/logging.py`, `core/screenshots.py`, `persistence/audit.py`, `app/api/health.py`, tests.
- **Rollback:** **never restore the baseline logger** — it is known to leak PII. Redeploy the **last PII-safe/redacted
  logger**, or **stop the service** if none is available. (The baseline logger is never an operational rollback target.)
- **Risks/failure behavior:** redaction defaults to over-redacting; a logging failure never crashes the request but is surfaced.
- **Definition of Done:** redaction + audit + health tests green.
- **Approval boundary:** stop before INC-21.

---

## INC-21 — Backup/restore + BitLocker/ACL verification + SQLCipher fallback gate

- **Purpose/outcome:** Provide safe backups via SQLite's **online backup API** (never a running-file copy), an
  encrypted+access-controlled backup location, a **restore runbook with a test**, and an at-rest protection **gate**:
  BitLocker + NTFS ACL verification, else **SQLCipher becomes mandatory** before production PII.
- **Why here:** protects data at rest and enables recovery before real data accumulates.
- **Prerequisites:** INC-10.
- **Addresses:** ADR-0005; DATA_MODEL §9/§10; INV-10.
- **Baseline files modified/retired:** none.
- **Target modules/files introduced:** `ops/backup.py` (online backup + verify), `deploy/at_rest.md` (BitLocker/ACL
  checklist + SQLCipher fallback decision gate), `ops/restore.md`. Tests under `tests/ops/backup/`.
- **DB migration impact:** none (operates on the DB).
- **Dependency/config impact:** SQLCipher is a **conditional deployment requirement** (mandatory only if the
  BitLocker + encrypted-backup guarantee cannot be met — a documented deployment gate, `deploy/at_rest.md`), not an
  unresolved implementation choice and not a default dependency.
- **Feature flags/adapters:** the SQLCipher path is a config gate documented in `deploy/at_rest.md`.
- **Out-of-scope:** enterprise backup infrastructure.
- **Tests-first:** **`test_backup_uses_online_api_not_file_copy`**; `test_restore_roundtrip_integrity`;
  `test_at_rest_gate_requires_bitlocker_or_sqlcipher` (a config assertion that production refuses to store PII without one).
- **Initial failing-test expectation:** fail (module absent).
- **Mock/fixtures:** temp DB; a temp backup dir.
- **Implementation steps:** online backup → verify → restore runbook + test → at-rest gate assertion.
- **Acceptance criteria:** consistent backup/restore; at-rest protection enforced by a startup gate.
- **Safe offline verification:** `python -m pytest tests/ops/backup -v`.
- **Safety gates:** contributes to release readiness.
- **Expected git-diff scope:** `ops/*`, `deploy/at_rest.md`, tests.
- **Rollback:** the backup scripts are additive and revertible **before** any production data exists. **While any
  production claimant data remains stored, the at-rest/backup protections (DB location, NTFS ACL, BitLocker/SQLCipher,
  encrypted backups) must NOT be removed** — they may be removed only after that data is securely purged or migrated to
  an equally protected system; otherwise redeploy the last safe version of these controls or stop the affected service.
- **Risks/failure behavior:** a running-file-copy is prevented by design; missing at-rest protection blocks PII storage.
- **Definition of Done:** backup/restore + at-rest-gate tests green.
- **Approval boundary:** stop before INC-22.
