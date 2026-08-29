# SAFETY MODEL

**Baseline:** `0290fe9…` · target design. This document defines how the target enforces
`docs/recovery/SAFETY_INVARIANTS.md` (INV-1..INV-11). Applies decisions #4 (contract-based interception), #5 (lease
fencing), #4/#9 (session vault + DPAPI). Nothing here is implemented yet; it is the Phase 4 target.

---

## 1. Capabilities (only `portal` constructs them)

Three narrow capabilities, each backed by its own `BrowserContext` with a reviewed route policy (§3). **No caller ever
receives a general write handle.**

### LoginCapability — `portal.open_login_session(account_id)`
Desktop onboarding tool only (headed, decision #6). Route policy allows **only** confirmed auth/session contracts
(login, OTP submit, session validate); **denies all mission-row endpoints and all final endpoints**. Exposes
`perform_manual_login()` → writes an encrypted, account-bound session (§7). No mission access.

### ReadCapability — `portal.open_reader(lease_handle)`
Receives a `LeaseHandle` (acquired by `execution` via `persistence`, correction #5); `portal` does not acquire the lock
itself. Deny-by-default; allows **only** confirmed read contracts. Exposes `search(identifiers) → [candidate]`,
`open(candidate)`, `scrape(fields)`, `read_rows()`. **No write method; never upgradable to a writer.** Dry-run uses only
this (INV-1 satisfied structurally).

### VerifiedMissionWriter — `portal.open_verified_writer(lease_handle, expected_identity)`
**Lease ownership (correction #5):** `execution` acquires the account lease **through `persistence`** and passes the
resulting `LeaseHandle` in. `portal` **does not acquire (or reacquire) the lock** and **does not import
sqlite/persistence** — this eliminates the earlier deadlock where the writer acquired the lease and then opened a
separate reader that acquired it again (a non-reentrant lock).

Internally, using **one BrowserContext** (the same context the writer will use — no second reader context):
1. `search(expected_identity)` requiring **exactly one** candidate (else fail closed);
2. open that candidate **in this context**;
3. **fully re-verify** identity (two-tier, §4) against the opened mission **in this same context**;
4. **only on full agreement** attach the write route policy to this context and return the writer.
Exposes **explicit ops only**: `read_row`, `write_row(rubrique, ht, tva, vetuste)`, `verify_row`,
`trigger_native_recalc()`. **No generic `request()`; no charge-mutuelle field is writable.** Identity is re-verified
before the first write and after any navigation/redraw (TOCTOU). Dry-run does **not** call this — it uses a
`ReadCapability` opened under the same `LeaseHandle`, with no write route ever attached.

## 2. Dry-run is write-incapable by construction (INV-1)
A DRY_RUN job is handed a `ReadCapability` and there is **no code path** from it to a writer. "Dry-run" is not a boolean
that guards a click — the write surface does not exist for the job.

## 3. Network interception — contract-based default-deny (decision #4, INV-3)
Interception is installed at the **BrowserContext** level (`context.route("**/*", …)`), not per-page, so popups, new
tabs and iframes are covered (fixes F9). A request is allowed **only** if it matches a reviewed **contract tuple**:
`(host, route, method, expected-payload-shape, capability, operation-type)`.

- **GET is not automatically safe** — a GET that is not a reviewed read contract is denied (a GET can mutate).
- **Unknown request → fail closed (abort).** If the route handler itself raises, the request is **aborted**, never
  allowed to fall through (footgun A3).
- **`service_workers="block"`** on every context so a service worker cannot bypass interception.
- **WebSockets** are blocked by default; any needed WS is an explicit reviewed contract.
- **External domains** (any host other than the portal host) are blocked during automation.
- **Write mode** allows only confirmed **row-op** contracts (the workflow's `allowed_row_ops`).
- **Permanent final-endpoint block (INV-4):** a hardcoded blocklist (`garageModifierValDevis`, `validerDevis`,
  `expertEnregistrerMission`, `enregistrerMission`, `cloturerMission`, `expertCloturerMission`, `cloturerTraitement`,
  `ajouterDocument`, `deleteDocument`, …) is enforced in **every** capability, cannot be disabled by any flag/mode, and
  **aborts** (never fulfills a fake `200` — fixes fail-open F8). `SAFETY_INVARIANTS.md` INV-4 is thereby raised from
  "not a permanent guarantee" toward a permanent, context-scoped, fail-closed guarantee.
- **Write-enable gate (footgun A5):** enabling any live write requires (a) **confirmed row-op contract records** for
  that workflow **and** (b) **passing safety tests** — not a single boolean (avoids repeating the `TEST_MODE` cliff).

## 4. Mission identity gate (INV-2, B.5, correction #4)
Two tiers, both required, compared on normalized values:
- **Tier 1 (primary):** exact `InsurerReference` **and/or** exact `IdSinistre` — at least one must be supplied.
- **Tier 2 (mandatory cross-check):** normalized `RegistrationPlate` — **required, not optional** (`ExpectedIdentity`,
  `DOMAIN_MODEL.md` §6). A job/plan whose input lacks a registration plate is non-executable (fail closed).
Rules: search returns **exactly one** candidate (zero/multiple → fail closed); a plate **alone** is insufficient (a
primary identifier is also required); an empty/None expected primary identifier **or** a missing registration →
**fail closed** (no match-by-absence, footgun A4); after opening, **all** supplied identifiers must agree;
missing/contradictory → `IdentityMismatch` (fail closed).

## 4a. Rubrique-row selection contract (INV-6 write-safety, correction #7 / F16)
When a row operation targets a portal rubrique row, selection is by **exact `IdRubrique`** and must match **exactly one**
row. **Prohibited:** label substring matching, first-row selection, bidirectional substring matching, and any positional
fallback. **Zero or multiple** matching rows → **fail closed** (`WRITE_ABORTED`, no write). This replaces the current
label-text/first-row/bidirectional-substring matcher (`docs/recovery/KNOWN_FAILURES.md` F16). Reviewed row-op contracts
(§3) carry the `IdRubrique` as the row key; the writer verifies the opened row's id equals the intended id before writing
and again on read-back.

## 5. Lease ownership, fencing & single-writer (decision #5, correction #5)
- **Ownership:** `execution` acquires the lease **through `persistence`** and holds a `LeaseHandle`, passed to `portal`.
  `portal` never acquires/reacquires the lock and never imports sqlite/persistence (no self-deadlock).
- **Heartbeat-loss response:** the writer validates the handle/`fencing_token` **immediately before every portal write**
  and while writing; on lost heartbeat or replaced ownership (`owner_instance_id`/`owner_job_id` changed) it
  **immediately aborts routing, closes the write BrowserContext, and blocks any further requests** → `WRITE_ABORTED`.
- **Fencing caveat (do not overstate):** the fencing token is an **internal** guard — **SinAuto does not validate any
  fencing token**, so it cannot make the portal reject a stale write. The authoritative single-writer guarantee is an
  **OS single-instance mutex**: **only one service process runs, and only that single service process may hold row-write
  capability.** The interactive login tool never holds row-write capability. Schema: `DATA_MODEL.md` §5.

## 6. Fail-closed mapping, money, charge-mutuelle (INV-6, INV-7, INV-8)
- Any `NeedsReview` line ⇒ the plan is non-writeable; the writer refuses it.
- All money is `Decimal`; **negative line TVA → `NeedsReview(INVALID_TAX_ALLOCATION)`** (no clamp/redistribute).
- **Charge mutuelle is native-only in both modes.** No module writes `MontantChargeSocietaire`/`MontantChargeMutuelle`;
  `RowOp` has no field for them; execution calls only `trigger_native_recalc()`. A safety test asserts these fields
  never appear in any allowlist or plan.

## 7. Session vault + DPAPI (decision #4/#9, correction #6 — one model, no alternatives)
Playwright storage state is a bearer credential. The **single chosen model** is:

> **DPAPI LocalMachine + service-account-only NTFS ACL.** The session ciphertext is DPAPI-`LocalMachine` encrypted and
> stored in a vault directory whose NTFS ACL grants access to the **service account only**. There is no CurrentUser
> alternative.

- **Onboarding handoff (correction #6):** the desktop onboarding tool **must not write into the vault directory** and
  **must never write plaintext session state to disk**. After the human OTP login (headed, `LoginCapability`), the tool
  performs an **authenticated, single-use, account-bound local handoff** of the freshly captured session to the service
  (e.g., a loopback-only, one-time-token, `account_id`-scoped call). **The service** validates the account/session
  evidence, **encrypts** (DPAPI LocalMachine) and **atomically stores** it. The tool holds the session only in memory and
  discards it after handoff.
- **Creation of identity binding:** the session is bound to an `account_id` from the `accounts` registry (never a filename).
- **Decryption:** only the **service** (`portal`) decrypts, at open time; **decryption failure or account-binding
  mismatch → fail closed** (no read/write proceeds).
- **Rotation/revocation:** a session can be marked revoked (forces re-login); rotated material replaces the old atomically.
- **Atomic replacement:** write temp + `os.replace` so a session is never half-written; plaintext never touches disk.
- **Backup exclusion:** session material is excluded from ordinary backups, logs, screenshots and Git (glob, not the
  exact name). At-rest DB protection is separate (`DATA_MODEL.md` §9).
- **Write jobs require positive identity** (§4); "where evidence permits" is acceptable only for read/notification context.

## 8. Invariant coverage
| Invariant | Enforced by |
|---|---|
| INV-1 dry-run write-incapable | §1–§2 (no writer path for DRY_RUN) |
| INV-2 mission identity | §4 gate + TOCTOU (`WORKFLOW_STATE_MODEL.md` §5) |
| INV-3 default-deny, fail-closed interception | §3 (context-level, contract-based, handler-abort) |
| INV-4 final endpoints permanently blocked | §3 permanent blocklist (abort) |
| INV-5 human final validation mandatory | `WORKFLOW_STATE_MODEL.md` §6 |
| INV-6 three-origin, fail-closed mapping | §6 + `DOMAIN_MODEL.md` |
| INV-7 Decimal, no negative TVA | §6 |
| INV-8 charge-mutuelle native-only | §6 |
| INV-9 relance not mutated | no relance write contract exists (read-only) |
| INV-10 secrets not exposed | §7 vault + `DATA_MODEL.md` at-rest + redaction (`TEST_STRATEGY`/`THREAT_MODEL`) |
| INV-11 API authn / no LAN session exposure | `API_CONTRACTS.md` (TLS, auth, RBAC, server-derived audit) |
