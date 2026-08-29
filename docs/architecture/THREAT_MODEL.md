# THREAT MODEL

**Baseline:** `0290fe9…` · target design. Threats are drawn from `docs/recovery/KNOWN_FAILURES.md` and mapped to the
mitigations that enforce `docs/recovery/SAFETY_INVARIANTS.md`. Not implemented yet.

---

## 1. Assets
- **Portal authentication sessions** (bearer credentials, per account).
- **Claimant PII** (names, plates, policy numbers, references).
- **Portal write capability** (the ability to change an insurer estimate).
- **Employee-action / audit records** (who did what).

## 2. Actors
- **Office employee** (authenticated, role-limited).
- **Malicious or curious LAN host** (unauthenticated; on the office network).
- **Insider** with some access seeking to exceed it.
- **Confused/lazy operator** (accidental misuse — see sharp-edges).

## 3. Trust boundaries
Browser (employee) ↔ `app` (HTTPS) · `app` ↔ `portal`/SinAuto (Playwright over TLS) · `app` ↔ SQLite (local file) ·
desktop **onboarding tool** ↔ vault/DB (separate process). Each boundary is enumerated with its controls below.

## 4. Threats → mitigations (STRIDE-flavored)
| # | Threat (source finding) | Mitigation | Invariant |
|---|---|---|---|
| T1 | Unauthenticated LAN caller drives the portal / spawns processes (F18) | TLS + server-side auth + RBAC; no unauthenticated mutating endpoint; subnet defense-in-depth (never disables auth) | INV-11 |
| T2 | Wrong-mission write via substring/first-row/sole-candidate (F3/F4/F5) | Two-tier identity gate; exactly-one match; no match-by-absence; TOCTOU re-verify | INV-2 |
| T3 | Preview/dry-run performs live writes (F1/F10) | Capability separation; dry-run has no writer path | INV-1 |
| T4 | Fail-open interceptor reports fake success (F8) | Context-level default-deny; **abort** (never fake-200); handler-exception aborts | INV-3/INV-4 |
| T5 | Final endpoint reachable (Enregistrer/Valider/Clôture/GED) | Permanent, un-disableable blocklist in every capability; agent never clicks final | INV-4/INV-5 |
| T6 | Charge-mutuelle overwritten (F6) | Native-only; `RowOp` has no such field; safety test | INV-8 |
| T7 | Unknown/glass/labour mapping silently defaulted (F13/F14/F15/F33) | Fail-closed mapping; three-origin; glass component×operation; structured-first labour | INV-6 |
| T8 | Negative TVA written (F17) | `INVALID_TAX_ALLOCATION` fail-closed; no clamp/redistribute | INV-7 |
| T9 | Session credential theft from disk (plaintext state, F21/F23) | DPAPI encryption + NTFS ACL + atomic replace + backup/Git/log exclusion; fail-closed on decrypt/binding failure | INV-10 |
| T10 | PII exfiltration via logs/screenshots/outbox/plan snapshot | No PII in logs/outbox/screenshots/plan_snapshot; redaction; access-controlled staging | INV-10 |
| T11 | XSS in dashboard from portal/imported data (F22) | Output encoding / safe rendering (no unescaped `innerHTML`); CSP where feasible | INV-10 |
| T12 | Raw error/text disclosure to clients (F19/F20) | Typed non-sensitive errors; correlation ids; truthful status (no 200-wrapping-failure) | INV-10/INV-11 |
| T13 | Two writers on one account (process race) | DB `account_leases` + fencing token before every write; >1 worker unsupported | write-safety |
| T14 | Stale SSE authorization; missed events on reconnect | Global `event_id` cursor; bounded retention; forced resync; periodic authz revalidation | — |
| T15 | Cross-user DPAPI decrypt failure (silent) | Explicit DPAPI scope (same identity CurrentUser, or LocalMachine+ACL); fail-closed on failure | INV-10 |
| T16 | Data loss / corruption on restart or crash | WAL; atomic outbox; restart reconciliation; online-backup API; tested restore | — |
| T17 | At-rest DB theft | BitLocker + NTFS ACL + encrypted backups + DB outside served dir; SQLCipher fallback if those can't be guaranteed | INV-10 |

## 5. Residual risks (accepted / deferred)
- **Plain-HTTP internal tooling** is disallowed in production (TLS required); a misconfiguration that disables TLS
  causes the service to refuse to serve rather than fall back.
- **Whole-DB encryption (SQLCipher)** is deferred while BitLocker + encrypted backups are guaranteed; it becomes
  mandatory otherwise (`DATA_MODEL.md` §9) — recorded as an open decision.
- **Interactive OTP** inherently requires a human at a desktop session; the onboarding tool is the only interactive
  surface and is scoped to `LoginCapability` (no mission access).
