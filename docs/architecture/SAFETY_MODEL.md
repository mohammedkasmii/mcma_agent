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

### ReadCapability — `portal.open_reader(account_id)`
Requires the DB lease + asyncio lock. Deny-by-default; allows **only** confirmed read contracts. Exposes
`search(identifiers) → [candidate]`, `open(candidate)`, `scrape(fields)`, `read_rows()`. **No write method; never
upgradable to a writer.** Dry-run uses only this (INV-1 satisfied structurally).

### VerifiedMissionWriter — `portal.open_verified_writer(account_id, expected_identity)`
Internally: acquire lease+lock → open a reader → `search(expected_identity)` requiring **exactly one** candidate (else
fail closed) → open it → compare **every** supplied identifier (two-tier, §4) → **only on full agreement** construct the
write context and return the writer. Exposes **explicit ops only**: `read_row`, `write_row(rubrique, ht, tva, vetuste)`,
`verify_row`, `trigger_native_recalc()`. **No generic `request()`; no charge-mutuelle field is writable.** Re-verifies
identity before the first write and after any navigation/redraw (TOCTOU).

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

## 4. Mission identity gate (INV-2, B.5)
Two tiers, both required, compared on normalized values:
- **Tier 1 (primary):** exact `InsurerReference` OR exact `IdSinistre`.
- **Tier 2 (independent cross-check):** normalized `RegistrationPlate`.
Rules: search returns **exactly one** candidate (zero/multiple → fail closed); a plate **alone** is insufficient; an
empty/None expected primary identifier or registration → **fail closed** (no match-by-absence, footgun A4); after
opening, **all** supplied identifiers must agree; missing/contradictory → `IdentityMismatch` (fail closed).

## 5. Lease fencing (decision #5, INV write-safety)
The per-account lease carries a `fencing_token`. The writer re-reads and validates the token **immediately before every
portal write**; if the lease expired or was replaced (another `owner_instance_id`/`owner_job_id`), the write is
**aborted** → `WRITE_ABORTED`. This prevents two holders writing after a lease hand-off. Schema: `DATA_MODEL.md` §account_leases.

## 6. Fail-closed mapping, money, charge-mutuelle (INV-6, INV-7, INV-8)
- Any `NeedsReview` line ⇒ the plan is non-writeable; the writer refuses it.
- All money is `Decimal`; **negative line TVA → `NeedsReview(INVALID_TAX_ALLOCATION)`** (no clamp/redistribute).
- **Charge mutuelle is native-only in both modes.** No module writes `MontantChargeSocietaire`/`MontantChargeMutuelle`;
  `RowOp` has no field for them; execution calls only `trigger_native_recalc()`. A safety test asserts these fields
  never appear in any allowlist or plan.

## 7. Session vault + DPAPI (decision #4/#9)
Playwright storage state is a bearer credential and is protected as follows:
- **DPAPI model (explicit, decision #4):** the interactive onboarding tool and the Windows service **either**
  (a) run under the **same dedicated Windows identity** using **DPAPI CurrentUser** scope, **or**
  (b) use **DPAPI LocalMachine** scope combined with **strict NTFS ACLs** granting decrypt access to the **service
  account only**. One of these is chosen at deploy time and documented; the scope is never left ambiguous.
- **Creation:** the login tool produces the storage state and encrypts it with the chosen DPAPI scope, bound to an
  `account_id` (identity from the `accounts` registry, never a filename).
- **Transfer:** the encrypted blob is stored via `persistence` (or a vault dir) referenced by `portal_sessions.storage_ref`.
- **Decryption:** only `portal` decrypts, at open time; **decryption failure or account-binding mismatch → fail closed**
  (no read/write proceeds).
- **Rotation/revocation:** a session can be marked revoked (forces re-login); rotated material replaces the old atomically.
- **Atomic replacement:** write temp + `os.replace` so a session is never half-written.
- **Backup exclusion:** session material is excluded from ordinary backups, logs, screenshots and Git (glob, not the
  exact name). At-rest DB protection is separate (`DATA_MODEL.md`).
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
