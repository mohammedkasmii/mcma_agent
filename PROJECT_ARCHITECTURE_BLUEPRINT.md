# 🏛️ PROJECT ARCHITECTURE SPECIFICATION & SYSTEM DESIGN BLUEPRINT

**Project:** MCMA / MAMDA Auto Insurance RPA & Operations Hub
**Target Environment:** Single On-Premise Agency Server (Wexia ERP Ecosystem)
**Topology:** Single Office LAN (`http://192.168.1.X:8000`)
**Version:** 5.1 — Execution Baseline (open questions resolved)
**Date:** August 2026
**Supersedes:** v5.0, v4.0, v3.0 (see git history)

---

## 0. How to Read This Document

Every subsection carries a build-status marker. This document describes a **target state**, and
roughly half of it does not exist yet. The markers say which half.

| Marker | Meaning |
|:---|:---|
| ✅ **BUILT** | Exists in the codebase today, verified, and exercised by tests or daily use |
| 🟡 **PARTIAL** | Exists in some form but does not meet the specification below |
| ⬜ **PLANNED** | Does not exist. Specification only. |

### What changed from v4.0

v4.0 grounded the design in the agency's operating reality. This revision fixes six defects found in
review — one of which was a direct self-contradiction — and downgrades two optimistic status claims.

| § | Correction |
|:---|:---|
| **§11** | **`garageModifierValDevis` moved to always-blocked.** v4.0 placed it in the mode-gated tier, where `DRAFT_WRITE` would have permitted it. It is the final *Valider Devis* action. v4.0 therefore blocked and allowed the same irreversible operation under two different names. Deletion and GED endpoints moved to Tier 1 as well; Tier 2 is now a **per-job allowlist**, not a mode-wide permission |
| **§6 / §12** | **Session 0 conflict resolved.** v4.0 installed the app as a Windows service *and* opened a visible OTP browser on the desktop. Services run in Session 0 and cannot do that. Now specified as a Task Scheduler logon task |
| **§7.4** | **`changed_version` columns added.** v4.0's `GET /state?since=N` was unimplementable — a single global counter cannot identify *which* rows changed |
| **§7.1 / §8** | **`poll_run_categories` added; poll outcomes are per category.** An account-level `SUCCESS` masked a single failed category, whose claims would then be archived. Same defect class this document criticised in v3.0, one level down |
| **§11.5** | **`page.pause()` removed from the target design.** It requires the Playwright Inspector, blocks indefinitely, and holds the account lock. Replaced by a readiness report and a `REVIEW_REQUIRED` handoff |
| **§4.1** | **The httpx transport is now a decision pending a spike**, not a settled one. In-page `fetch()` inherits cookies, `Referer`, and same-origin implicitly; standalone httpx may not |
| **§7.1** | **`automation_jobs` table added** (Phase 2) so queued work survives a restart |
| **§15** | Mode Normal and Mode Conventionné downgraded ✅ → 🟡: read-back verification is computed but never acted upon in either engine |

---

## 1. Executive Summary

The **MCMA / MAMDA Operations & Automation Hub** is an RPA engine and operations dashboard that
monitors incoming claim notifications across four portal accounts, tracks which employee is handling
which claim, and (Phase 2) executes automated expertise report filings on the Moroccan insurance
portal `sinauto.mamda-mcma.ma`.

It runs on **one on-premise PC** in the main agency office, alongside the agency's **Wexia ERP**
instance. Four to six employees connect from their own browsers over the office LAN.

The system's defining constraint is not technical. It is that **the portal is only usable during
office hours, every account needs its own SMS OTP login, and the people who run it are not
technical.** Every decision below is downstream of those three facts.

---

## 2. Operating Context

This section is normative. It is the reason the rest of the document looks the way it does.

| Fact | Consequence for the architecture |
|:---|:---|
| The portal refuses authentication after **18:00** — with no error page, banner, or any machine-readable signal | The system **cannot detect** closure. It must run on a configured clock instead (§5) |
| Employees end their shift at **18:00** | Nothing needs to run overnight. No 24/7 session daemon. A session that dies at 18:05 is simply tomorrow's problem |
| Each of the 4 accounts requires **its own login + SMS OTP** | No unattended credential vault. Authentication is a supervised human ritual (§6) |
| **Anyone at the agency can perform any account's login** — credentials are shared | The portal provides **zero employee identity**. Attribution must be local (§9.2) |
| **4–6 employees**, one room, one LAN | Rules out SSE, rules out React, rules out per-user authentication. All three are over-engineering at this scale |
| Employees are **non-technical**; the server is a Windows desktop PC | The system must survive being ignored: no terminal window to keep open, no `npm run build`, automatic restart (§12) |
| A **visible browser** is required for OTP login | The application cannot run as a Session 0 Windows service (§12) |
| Code reaches the agency by **manual transfer** from a private GitHub repo | The repo must never be made public (§13). Transfer is offline |

---

## 3. Multi-Account Scope

Four portal account profiles on the shared `sinauto.mamda-mcma.ma` application:

| Account ID | Entity | Portfolio | Base URL |
|:---|:---:|:---:|:---|
| `mcma_oujda` | MCMA | Oujda | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` |
| `mamda_oujda` | MAMDA | Oujda | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` |
| `mcma_nador` | MCMA | Nador | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` |
| `mamda_nador` | MAMDA | Nador | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` |

> **Domain reality:** MAMDA and MCMA share the exact same web application and DOM structure. The
> four-way split is purely a **login credential and portfolio routing** distinction — not a
> code-path distinction. There must be exactly one extractor, one mapper, and one filler,
> parameterised by `account_id`.

---

## 4. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│                          AGENCY OFFICE LAN  (4–6 employees)                        │
│      Employee PC 1              Employee PC 2              Employee Mobile         │
│      http://192.168.1.X:8000    http://192.168.1.X:8000    http://192.168.1.X:8000 │
└──────────────▲───────────────────────────▲─────────────────────────▲───────────────┘
               │                           │                         │
               └───────────────────────────┼─────────────────────────┘
                                           │  REST + 15s poll of /api/v1/state?since=
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│   SINGLE ON-PREMISE AGENCY PC — one FastAPI process, Task Scheduler logon task     │
│                    (interactive desktop session — NOT a Session 0 service)         │
│                                                                                    │
│  ┌────────────────────┐  ┌──────────────────────┐  ┌───────────────────────────┐   │
│  │  Static Dashboard  │  │  Scheduled Poller    │  │  Auth & Filling Agent     │   │
│  │  HTML/CSS/vanilla  │  │  07:45–18:00 only    │  │  (Playwright / Chromium)  │   │
│  │  served at /       │  │  httpx + cookies*    │  │  - OTP login (visible)    │   │
│  │  no build step     │  │  per-account lock    │  │  - Phase 2 form filling   │   │
│  └─────────┬──────────┘  └──────────┬───────────┘  └────────────┬──────────────┘   │
│            │                        │                           │                  │
│            └────────────────────────┼───────────────────────────┘                  │
│                                     ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│  │                      SQLite (WAL) — mcma.db + nightly backup                 │  │
│  │  accounts │ portal_sessions │ claims │ employee_actions                      │  │
│  │  poll_runs │ poll_run_categories │ automation_jobs │ audit_events            │  │
│  └──────────────────────────────────────┬───────────────────────────────────────┘  │
└─────────────────────────────────────────┼──────────────────────────────────────────┘
                                          │
              ┌───────────────────────────┴────────────────────────────┐
              │ httpx + session cookie*        Playwright (login/fill) │
              ▼                                                        ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│              REMOTE MAMDA / MCMA PORTAL  (sinauto.mamda-mcma.ma)                   │
│              Server-rendered PHP · form-urlencoded XHR · cookie session · OTP      │
│              AVAILABLE ONLY DURING OFFICE HOURS                                    │
└────────────────────────────────────────────────────────────────────────────────────┘

* pending the transport spike in §4.1
```

**The two-transport rule.** Polling uses `httpx` with the account's session cookie — no browser.
Playwright is reserved for the two jobs that genuinely need a real browser: **OTP login**, and
**Phase 2 form filling** (where the page's own JavaScript performs the financial calculations).
Four idle Chromium instances would otherwise cost roughly 1.5 GB of RAM on the agency PC for no
benefit.

### 4.1 The transport is a decision pending a spike

⬜ **PLANNED — do this before building the poller**

`browser/notifications.py:33` proves the portal exposes usable AJAX endpoints, because an **in-page**
`fetch()` against `getAlerte/CodeAlerte/{code}` returns full JSON. It does **not** prove that
standalone httpx will work, because an in-page fetch implicitly inherits things a bare client does
not: the cookie jar, `Referer`, `Origin`, same-origin credentials, and any token the surrounding page
carries.

**Spike (one day, before any poller code):** for each of the four accounts and every alert category,
compare

```
A)  Playwright  page.evaluate(fetch)          ← known good
B)  httpx       with cookies exported from A
```

on **status code, response schema, and full record count**. B must equal A exactly. If it does not,
identify what is missing (CSRF token, `Referer`, a hidden page token, a required header) and either
supply it or fall back to driving the fetch inside a single shared Playwright page per account.

**Cookie coherence.** If httpx proceeds, the portal will hand it refreshed cookies. Those must be
written back into the account's encrypted Playwright storage state after every successful poll,
under the same per-account lock. Otherwise httpx and Playwright drift into two divergent views of
one session, and the browser path fails at exactly the moment an employee needs it.

---

## 5. Operating Window — Scheduled, Not Detected

⬜ **PLANNED**

**Decision:** The system does not attempt to detect that the portal has closed. It runs on a
configured clock.

**Rationale.** After 18:00 the portal simply refuses authentication. It emits no banner, no error
code, and no distinguishable response. A failed login at 18:05 is indistinguishable from a wrong
password, a dead session, or a network fault. Any detection heuristic would therefore be guessing —
and would guess wrong on precisely the days it matters, such as a genuine session death at 16:30. A
clock is deterministic, auditable, and correct.

```python
# core/config.py
TIMEZONE              = "Africa/Casablanca"   # see the Ramadan note below — this is not cosmetic
POLL_WINDOW_START     = "07:45"
POLL_WINDOW_END       = "18:00"
POLL_DAYS             = {MON, TUE, WED, THU, FRI, SAT}   # confirm Saturday with the agency
POLL_INTERVAL_MINUTES = 5
SESSION_WARNING_TIME  = "17:00"
```

> **Timezone is a correctness requirement, not tidiness.** Morocco observes UTC+1 year-round *except*
> during Ramadan, when the clock drops to UTC+0 and returns afterwards. A window computed from naïve
> local time will silently shift by an hour once a year, and the shift lands during the busiest
> period of the year. Resolve all window arithmetic through a real `Africa/Casablanca` zone (Python
> `zoneinfo`), never through fixed offsets or naïve `datetime.now()`.

**Behaviour outside the window:** the poller does not run, does not authenticate, writes no claim
rows, and changes no lifecycle state. `session_keeper` does not ping. The dashboard renders a calm
banner — *« Portail MAMDA/MCMA fermé — reprise demain à 07:45 »* — rather than an error.

**Start-of-shift validation (07:45).** The first run of the day validates all four sessions before
anyone arrives, so the account cards are already green-or-grey when the first employee sits down.
Discovering at 14:00 that an account has been dead since yesterday is the failure mode this exists
to prevent.

**End-of-shift warning (17:00).** If any account's session is unhealthy, the dashboard raises a
visible warning while somebody with the credentials and the phone is still in the building. After
18:00 the only remedy is tomorrow morning.

**Operating hours are configuration, not code.** They are editable from a settings page; agency
schedules change.

---

## 6. Session & OTP Model — The Morning Ritual

⬜ **PLANNED** (🟡 `auth_setup.py` and `main.py:69` are the single-account seed of this)

**Decision:** Authentication is a supervised human ritual performed once per account per day, not an
unattended daemon.

v3.0 called for a "Multi-Account Vault & Login Manager." That framing is wrong: with a mandatory SMS
OTP per account, no daemon can ever log in by itself. Chasing 24/7 sessions means building machinery
whose sole purpose is to postpone an unavoidable human step — and which fails silently at 02:00 when
nobody is watching. Since the portal is unusable overnight anyway, the honest design is a **daily
login**.

**The ritual.**

1. **~08:00.** An employee opens the dashboard. Four account cards are shown, each 🟢 healthy or
   ⚪ needs-login.
2. For each ⚪ card they click **« Reconnecter »**. A Chromium window opens **on the server PC's
   interactive desktop** at the portal login page.
3. They enter the shared credentials and the SMS OTP. On dashboard detection, the storage state is
   captured and the card turns 🟢.
4. The poller picks the account up on its next 5-minute tick.

Four OTPs a morning is an acceptable, visible, self-correcting human cost. A background daemon that
silently stops working is not.

> **This requirement drives §12.** Step 2 renders a real browser window on a real desktop. That is
> impossible from a Session 0 Windows service, which is why the application is deployed as a logon
> task rather than a service.

**Specification of the login endpoint** (replacing the unauthenticated `main.py:69`):

- `POST /api/v1/accounts/{account_id}/login` — takes an `account_id`, is rate-limited to one
  in-flight login per account, holds that account's lock for the duration, and refuses with a clear
  French message outside the operating window (*« Portail indisponible jusqu'à demain matin »*) so
  that nobody concludes the system is broken.
- On success it sets `portal_sessions.health_status = HEALTHY` and writes an `audit_events` row.

**Storage of session state.** Each account's Playwright storage state lives in
`sessions/{account_id}.json`, encrypted with **Windows DPAPI** (`CryptProtectData`, machine scope,
so the scheduled task's account can read it). The directory is `.gitignore`d and NTFS-restricted.

> **Be honest about what this protects.** DPAPI defends against a copied disk or a stray backup. It
> does **not** defend against someone with access to that Windows account — for them it is
> obfuscation. The real controls here are NTFS permissions and physical access to the office. This
> blueprint states that plainly rather than implying cryptographic safety it does not have.

---

## 7. Data Layer — SQLite in WAL Mode

⬜ **PLANNED** (today: flat JSON files)

**Decision:** One embedded SQLite database, `data/mcma.db`, in WAL mode
(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;`).

**Rationale — this is urgent, not cosmetic.** `main.py:88-110` currently performs an unguarded
read-modify-write of `logs/notification_actions.json`. Two employees clicking a status pill in the
same second **silently lose one write, today**. `static/app.js:295` compounds it by mirroring state
into `localStorage`, so every browser holds a divergent copy that the merge at `app.js:206`
overwrites on the next refresh. Colleagues already cannot reliably see each other's work.

### 7.1 Schema

```sql
CREATE TABLE accounts (
    account_id    TEXT PRIMARY KEY,
    entity        TEXT NOT NULL CHECK (entity IN ('MCMA','MAMDA')),
    portfolio     TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    base_url      TEXT NOT NULL,
    is_enabled    INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE portal_sessions (
    account_id              TEXT PRIMARY KEY REFERENCES accounts(account_id),
    health_status           TEXT NOT NULL DEFAULT 'NEVER_AUTHENTICATED'
                                 CHECK (health_status IN
                                 ('HEALTHY','EXPIRED','NEVER_AUTHENTICATED','UNKNOWN')),
    auth_state_path         TEXT,
    last_validated_at       TEXT,
    last_successful_poll_at TEXT,     -- see §7.3: this is what makes the UI honest
    last_error              TEXT,
    changed_version         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE claims (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id                TEXT NOT NULL REFERENCES accounts(account_id),
    category_code             TEXT NOT NULL,
    category_name             TEXT NOT NULL,
    reference                 TEXT NOT NULL,
    id_sinistre               TEXT,
    date_survenance           TEXT,          -- ISO 8601, normalised on ingest
    date_survenance_raw       TEXT,          -- exactly as the portal returned it
    societaire                TEXT,
    police                    TEXT,
    matricule                 TEXT,
    nature                    TEXT,
    portal_status             TEXT,          -- DÉCLARÉ / EN COURS / ...
    portal_presence           TEXT NOT NULL DEFAULT 'ACTIVE'
                                   CHECK (portal_presence IN
                                   ('ACTIVE','MISSING_PENDING_CONFIRMATION','RESOLVED_ON_PORTAL')),
    consecutive_missing_polls INTEGER NOT NULL DEFAULT 0,
    first_seen_at             TEXT NOT NULL,
    last_seen_at              TEXT NOT NULL,
    changed_version           INTEGER NOT NULL DEFAULT 0,
    UNIQUE (account_id, category_code, reference)
);
CREATE INDEX ix_claims_version  ON claims(changed_version);
CREATE INDEX ix_claims_presence ON claims(account_id, portal_presence);

CREATE TABLE employee_actions (
    claim_id        INTEGER PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
    employee_status TEXT NOT NULL DEFAULT 'TODO'
                         CHECK (employee_status IN ('TODO','IN_PROGRESS','DONE','WAITING')),
    note            TEXT NOT NULL DEFAULT '',
    updated_by      TEXT,
    updated_at      TEXT NOT NULL,
    changed_version INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_actions_version ON employee_actions(changed_version);

-- One row per account per poll tick
CREATE TABLE poll_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  TEXT NOT NULL REFERENCES accounts(account_id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN
                     ('SUCCESS','PARTIAL','AUTH_FAILED','UNREACHABLE','SKIPPED_WINDOW_CLOSED')),
    error       TEXT
);

-- One row per alert CATEGORY within that tick. See §8.2 — this is what makes archiving safe.
CREATE TABLE poll_run_categories (
    poll_run_id   INTEGER NOT NULL REFERENCES poll_runs(id) ON DELETE CASCADE,
    category_code TEXT    NOT NULL,
    outcome       TEXT    NOT NULL CHECK (outcome IN ('SUCCESS','FAILED','EMPTY')),
    alerts_seen   INTEGER,
    error         TEXT,
    PRIMARY KEY (poll_run_id, category_code)
);

-- Phase 2. Durable so queued work survives a restart.
CREATE TABLE automation_jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     TEXT NOT NULL REFERENCES accounts(account_id),
    claim_id       INTEGER REFERENCES claims(id),
    workflow       TEXT NOT NULL CHECK (workflow IN ('MODE_NORMAL','MODE_CONVENTIONNE')),
    execution_mode TEXT NOT NULL CHECK (execution_mode IN ('PLAN','PREVIEW','DRAFT_WRITE')),
    status         TEXT NOT NULL DEFAULT 'QUEUED'
                        CHECK (status IN ('QUEUED','RUNNING','REVIEW_REQUIRED','FAILED','CANCELLED')),
    allowed_writes TEXT NOT NULL DEFAULT '[]',   -- JSON array; see §11.2
    requested_by   TEXT,
    payload_json   TEXT,
    result_json    TEXT,                         -- the readiness report; see §11.5
    error_code     TEXT,
    created_at     TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT
);

CREATE TABLE audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor      TEXT NOT NULL,          -- employee name, or 'worker'
    account_id TEXT,
    claim_id   INTEGER,
    job_id     INTEGER,
    details    TEXT                    -- JSON
);

CREATE TABLE app_state (               -- holds the monotonic 'state_version' counter
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

### 7.2 Two schema decisions worth arguing about

**`claims` is keyed on `(account_id, category_code, reference)`, not on `reference` alone.**
v3.0 keyed `employee_actions` on `reference` with no account — two accounts surfacing the same claim
reference would have silently overwritten each other's notes. Including `category_code` additionally
means the work item is the **alert occurrence**, not the physical claim: if the same claim later
reappears under *RELANCES REÇUES*, it becomes a new row with its own status. That matches how
employees count their work ("j'ai 12 alertes") and keeps the archive honest. The trade-off is that
notes do not follow a claim across categories.

> **This remains open — see §16 Q2.** A richer model (separate `claims` and `work_items`, with notes
> at both levels) would support both behaviours, at the cost of roughly doubling the schema and
> forcing employees to learn which of two note fields they are typing into. **Nobody has yet measured
> how often the same reference actually appears in two categories.** Measure that over one week of
> real polls before paying for the richer model.

**`employee_actions` references `claims.id`, not a text reference.** Work status attaches to a row
that provably exists, with cascade delete, rather than to a free-floating string.

### 7.3 `last_successful_poll_at` earns its place

A dashboard showing zero alerts must be able to distinguish *"there is nothing new"* from *"we have
not been able to look since Tuesday."* Those render identically and mean opposite things. Every
account card displays its last successful poll time, and degrades visibly once that time is older
than a couple of intervals. This is what makes the screen trustworthy.

### 7.4 `changed_version` — making the delta API implementable

v4.0 specified `GET /api/v1/state?since=417` returning "only rows changed since version 417", while
storing a single global counter in `app_state`. **That cannot work**: a global counter records that
*something* changed, never *what*.

**Rule:** every business write, in the same transaction:

1. increments `app_state['state_version']`, and
2. stamps that new value into the touched row's `changed_version`.

The delta query is then a plain indexed scan:

```sql
SELECT * FROM claims WHERE changed_version > :since;
```

A separate `state_changes` audit table was considered and rejected: it adds a second write path to
every mutation, and this system has no need to replay change history — only to answer "what is new
since my last poll."

---

## 8. Dual Lifecycle State Machine

⬜ **PLANNED**

**Decision:** Portal presence and employee work status are strictly separate axes and never
overwrite each other.

**Portal presence** — owned by the poller, never by a human:

| State | Meaning |
|:---|:---|
| 🟢 `ACTIVE` | Seen in the account's alert queue on the most recent successful poll of its category |
| 🟡 `MISSING_PENDING_CONFIRMATION` | Absent on 1–2 consecutive **successful category** polls |
| ⚪ `RESOLVED_ON_PORTAL` | Absent on 3+ consecutive **successful category** polls → archived locally |

**Employee work status** — owned by humans, never by the poller:
⚪ `TODO` · 🔵 `IN_PROGRESS` · 🟢 `DONE` · 🟡 `WAITING`

**Benefit:** when MCMA removes an alert from its queue, the claim is archived locally **without
losing employee notes, status, or history**.

### 8.1 The transition rule

> `consecutive_missing_polls` increments **only** when the claim's own `category_code` was polled
> with `poll_run_categories.outcome = 'SUCCESS'` — meaning that category authenticated, responded,
> and returned a parseable list. A failed, unreachable, unauthenticated, skipped, or out-of-window
> poll increments nothing and changes no lifecycle state.

**Why this clause exists.** v3.0 described the counter as guarding against "temporary network or
session drops" and relied on three polls being enough to ride them out. Three polls at a five-minute
interval covers fifteen minutes. It does not cover the fourteen-hour nightly closure. Under the v3.0
rule the poller would fail repeatedly after 18:00 and, three ticks later, **archive the entire active
queue as `RESOLVED_ON_PORTAL`** — employees would arrive to an empty dashboard every single morning.

The operating window of §5 already prevents the nightly case by not polling at all. This clause is
the second, independent guard, and it also covers mid-day outages, expired sessions, and portal
downtime. Both are required: the window is a schedule, this is an invariant.

### 8.2 Why the rule is scoped to the category, not the account

🟡 **This is a live bug in the current extractor, not only a specification gap.**

An account exposes several alert categories. `browser/notifications.py:169` returns `[]` when a
category fails both of its retry attempts, and `fetch_all_notifications` then records that category
with `count: 0` and **no error anywhere in the result**. A failed category and a genuinely empty
category are byte-identical in the output.

If poll outcome were tracked per *account*, a run where seven categories succeeded and one failed
would still be recorded `SUCCESS`. Every claim in the failed category would be counted missing, and
three ticks later the whole category would be archived as resolved — the exact defect this document
criticises v3.0 for, one level further down.

**Required, in both the schema and the extractor:**

1. `_fetch_category_rows` must return a discriminated result — `(SUCCESS, rows)`, `(EMPTY, [])`, or
   `(FAILED, error)` — never a bare list. An empty list must stop being ambiguous.
2. Each category's outcome is written to `poll_run_categories`.
3. `poll_runs.outcome` becomes `PARTIAL` when any category failed. `PARTIAL` is a legitimate,
   non-alarming state — it simply means some categories are not eligible for archiving this tick.
4. Lifecycle reconciliation runs **per category**, over categories whose outcome is `SUCCESS` or
   `EMPTY` only.

---

## 9. Frontend & State Synchronisation

✅ **BUILT** (`static/index.html`, `static/app.js`, `static/style.css`) — needs extension, not rewrite

**Decision:** Keep the existing hand-written HTML/CSS/vanilla-JS dashboard, served directly by
FastAPI via `app.mount("/", StaticFiles(directory="static", html=True))`. **No React. No Vite. No
build step.**

**Rationale — reversing v3.0.** v3.0's stated justification ("avoids running a separate Node.js
server") argues against Next.js SSR; it does not argue *for* rewriting a working 650-line dashboard.
The rewrite's real cost is that `npm run build` would have to run on a Windows office PC where
nobody can run Node — forcing either a committed `dist/` folder or a CI pipeline, in order to deliver
a table with filters, a modal, and toasts. Adding account tabs and live refresh to the existing
`renderTable()` is an afternoon of work.

### 9.1 State synchronisation: polling, not SSE

**Decision:** The dashboard polls `GET /api/v1/state?since=<version>` every **15 seconds**.

**Rationale — reversing v3.0.** SSE is the right tool at scale; at 4–6 clients it is not. Six clients
at 15-second intervals is 24 requests per minute against local SQLite — nothing. SSE buys roughly
two seconds of latency in exchange for connection-lifecycle management, reconnect handling, and
proxy-buffering surprises. Not a good trade at this size.

```jsonc
// GET /api/v1/state?since=417
{
  "version": 423,                       // monotonic; client sends it back next time
  "window":   { "open": true, "closes_at": "18:00" },
  "accounts": [
    { "account_id": "mcma_oujda", "health_status": "HEALTHY",
      "last_successful_poll_at": "2026-08-29T14:32:11",
      "last_poll_outcome": "SUCCESS", "active_claims": 12 }
  ],
  "claims":   [ /* rows WHERE changed_version > 417 — see §7.4 */ ],
  "archived": [ /* claim ids moved to RESOLVED_ON_PORTAL since version 417 */ ]
}
```

The response carries a monotonic `version`, so the contract is **SSE-ready**: if the agency ever
grows past this scale, the transport can be swapped without touching the frontend's data model.

### 9.2 Identity, attribution, and network exposure

⬜ **PLANNED**

Portal credentials are shared and any employee may log in as any account, so **the portal supplies no
employee identity**. v3.0's `updated_by` and `audit_events.user_or_worker` columns therefore had
nothing to populate them — and an audit log you cannot attribute is not an audit log.

**Required:**

- **Restrict the firewall rule to the office subnet.** `Autoriser_Reseau_Local.bat` currently opens
  port 8000 to `profile=any`, which includes guest Wi-Fi. It must be scoped
  (`remoteip=192.168.1.0/24`, private profile only).
- **Attribution.** On first visit the dashboard asks *« Qui êtes-vous ? »* and stores the chosen name
  in `localStorage`, sending it with every write to populate `updated_by` and `audit_events.actor`.
- **CSRF protection on all write endpoints** — mandatory from the moment any cookie is introduced,
  including the optional shared password below. Without it, any page an employee visits can drive
  this dashboard from inside the LAN.
- **Optional:** one shared dashboard password, checked once and cookied.

> **On per-employee PINs — see §16 Q3.** Review raised that a name picker is not trustworthy
> attribution, since anyone can select a colleague's name. That is true. It is not adopted here
> because the threat model does not support it: these four to six colleagues already share the
> portal credentials for all four accounts, so any of them can log into the real portal as any
> account and cause far more damage than mis-attributing a note. A PIN adds a login flow, a reset
> procedure, and hashed storage to defend the smaller of two risks while the larger one is
> unaddressed *by the agency's chosen operating model*. Deferred, not rejected — revisit if the
> agency ever stops sharing portal credentials.

---

## 10. Concurrency & Execution

🟡 **PARTIAL** — Playwright orchestration exists; the scheduler, locks, and job table do not

- One FastAPI process. One background scheduler task. One `asyncio.Lock()` **per `account_id`**.
- The lock guarantees that the poller, an OTP login, and a filling job never drive the same account's
  session concurrently.
- **Automation never runs inside an HTTP request.** Today `main.py:126` launches a full Chromium
  synchronously in the request path — five employees clicking « Actualiser » spawns five browsers on
  the agency PC. Employee actions insert an `automation_jobs` row and return immediately; the
  dashboard learns the result on its next 15-second poll.
- **Jobs are durable.** An in-memory `asyncio.Queue` loses queued work on restart, and Windows
  restarts. Because there is exactly one process, `asyncio.Lock` remains sufficient for mutual
  exclusion — the `automation_jobs` table exists for **recovery and visibility**, not for locking.
  On startup, any job left `RUNNING` is marked `FAILED` with `error_code = INTERRUPTED`; it is never
  silently resumed, because a half-completed portal write must be inspected by a human.
- Poll cadence is 5 minutes per account, staggered, in-window only. Four accounts × 12 polls/hour ×
  10 hours ≈ 480 requests/day — a defensible load against the portal.

---

## 11. Safety Policy — Two Tiers, Permanently

🟡 **PARTIAL** — `browser/safety_interceptor.py` exists but does not implement this

v3.0 declared default-deny "a permanent core system invariant." The implementation is one boolean:

```python
# core/config.py:20
TEST_MODE: bool = True
# browser/safety_interceptor.py:29
if not enabled:
    return          # ← nothing is blocked. Including validerDevis.
```

Flipping that flag for Phase 2 makes every irreversible endpoint reachable. **A permanent invariant
cannot share a switch with a development mode.**

### 11.0 Disclosed gap — row-level writes were never intercepted

> 🔴 **`TEST_MODE` has never blocked row-level writes in either engine.** This is not a
> specification defect; it was in effect for every run to date. Fixed on
> `feat/disable-form-filling-agent`.

`core/config.py:12` documented `TEST_MODE` as blocking *"all mutating POST endpoints."* The
interceptor list did not match that claim. Verified against the network capture, the generated
client, and `mock_server.py`:

| Endpoint | Was blocked? | Exists on the portal? | Assessment |
|:---|:---:|:---:|:---|
| `createDevisDet` | ✅ yes | ❌ **nowhere** — not in the capture, not in `mock_server.py`, not in the generated client | **Phantom.** Guarded a name that does not exist |
| `createRapportDefDet` | ❌ **no** | ✅ real — `REPORT.md:29`, `generated_client.py:551`, `mock_server.py:745` | **Accidental gap.** Mode Normal row creation, unguarded |
| `updateDevisDet` | ❌ no | ✅ real | **Deliberate by design** — `mode_conventionne.py` awaits and validates this response; only `garageModifierValDevis` was treated as the thing to block |

**Mode Normal (accidental).** `browser/mode_normal.py` clicks the column-7 checkmark on each
rubrique row, which is exactly what fires `POST .../createRapportDefDet`. The interceptor guarded a
name that does not exist while the real endpoint passed through untouched. Nobody intended this.

**Mode Conventionné (deliberate, but now out of policy).** Leaving `updateDevisDet` open was a
considered choice — row edits are re-editable, and only final validation is irreversible. That was
defensible under v3.0. It is **not** compatible with §11.2, where `PREVIEW` means *zero write
requests leave the machine* and row writes are permitted only inside a `DRAFT_WRITE` job's
allowlist.

**Consequence.** Under `TEST_MODE = True`, both engines wrote **real rows into real missions** on the
live portal. The blast radius is bounded: `expertEnregistrerMission`, `garageModifierValDevis`,
`validerDevis`, and the closure endpoints *were* correctly blocked, so no mission was ever saved,
validated, or closed. The on-screen message *"Zero final submissions were made"* was accurate as
written; the `config.py` docstring claiming all mutating endpoints were blocked was not.

**Actions:**

1. ✅ Add `createRapportDefDet`, `updateDevisDet`, `deleteRapportDefDet` to interception; remove the
   phantom `createDevisDet`. A phantom pattern in the list manufactures false confidence.
2. ✅ Blocked responses now fail closed — HTTP 403 with `__mcma_blocked` (§11.3) instead of
   HTTP 200 `{"state":"success"}`.
3. ⬜ **Audit the affected missions.** Runs recorded in `logs/workflow_*.json` and `logs/gc_*.json`
   may have left orphan rubrique rows that a human must review and remove on the portal.
4. ⬜ **When re-enabling Conventionné:** `_edit_single_row_dynamic` awaits a real `updateDevisDet`
   response and will now receive the 403 sentinel in `PREVIEW`. It must treat that as a blocked
   write and report `SIMULATED`, not as a failure and not as a success (§11.3, §11.6).
5. Governing precedent for §11.2: an allowlist may only ever contain endpoints **observed in a
   network capture**, never endpoints inferred from a sibling's name.

### 11.1 Tier 1 — ALWAYS BLOCKED (no configuration, mode, or job can re-enable these)

```
**/validerDevis
**/garageModifierValDevis          ← see the correction note below
**/cloturerMission                 **/expertCloturerMission
**/enregistrerMission              **/expertEnregistrerMission
**/cloturerTraitement
**/deleteDevisDet                  **/deleteRapportDefDet
**/ajouterDocument                 **/deleteDocument
```

Enforced unconditionally, on every page, in every mode, in every environment. `FINAL_VALIDATION` is
not an execution mode the agent possesses; it is a human act performed by an expert in their own
browser.

> **Correction to v4.0.** v4.0 placed `garageModifierValDevis` in the mode-gated tier, where
> `DRAFT_WRITE` would have permitted it. That was wrong.
> `GARAGE_CONVENTIONNE_ANALYSIS.md:78` records it as *"triggered directly by `ValiderDevis()` upon
> clicking `#DEVISDET_Btn`"*; its payload carries `Check_VALIDEVIS: "O"`; and on success the portal
> hides the submit button and permanently locks `#blocDevisValide`. It **is** the final *Valider
> Devis* action under a second name — so v4.0 blocked it as `validerDevis` in Tier 1 and allowed it
> as `garageModifierValDevis` in Tier 2, in the same document.
>
> **Rule going forward: classify by irreversible effect, never by endpoint name.** Deletion
> (`delete*`) and GED document writes (`ajouterDocument`, `deleteDocument`) are likewise permanent
> and belong here regardless of mode.

### 11.2 Tier 2 — per-job allowlist, not a mode-wide permission

`DRAFT_WRITE` is **not** a blanket key to every non-Tier-1 endpoint. Each job declares exactly which
write endpoints its run may call, stored in `automation_jobs.allowed_writes`:

```python
@dataclass(frozen=True)
class JobPolicy:
    mode:           Literal["PLAN", "PREVIEW", "DRAFT_WRITE"]
    allowed_writes: frozenset[str]     # always empty unless mode == DRAFT_WRITE
```

| Workflow | `allowed_writes` in `DRAFT_WRITE` |
|:---|:---|
| Mode Conventionné | `updateDevisDet` **only** — in-place row edits on `#DevisDetTableVal` |
| Mode Normal | `createRapportDefDet` **only** — row creation on `#tableRapportDet` |

Both endpoints are **confirmed against the network capture and `mock_server.py`**, not inferred.
Full paths:

```
POST /SinAuto_MCMA/expertise/gestionExpert/updateDevisDet          → Mode Conventionné
POST /SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet     → Mode Normal
```

Interception order, evaluated per request:

```
1. Tier 1 pattern match          → BLOCK (always, no exceptions)
2. mode != DRAFT_WRITE           → BLOCK any mutating endpoint
3. url not in job.allowed_writes → BLOCK
4. otherwise                     → ALLOW
```

A Conventionné job therefore cannot reach a Normal endpoint even while in `DRAFT_WRITE`, and vice
versa. Modes remain: `PLAN` (read and compare only), `PREVIEW` (populate DOM fields, zero write
requests leave the machine), `DRAFT_WRITE` (the allowlist above).

### 11.3 Blocked calls must fail loudly, never silently succeed

`safety_interceptor.py:35` currently fulfils blocked requests with
`{"state":"success","message":"[SIMULATED] Blocked by safety mode"}` — **HTTP 200 with a success
body**. The workflow's read-back verification then reports success for a write that never happened.
Harmless while everything is blocked; actively dangerous the moment `DRAFT_WRITE` exists and some
writes are real.

**Specification:**

1. Blocked calls are fulfilled with **HTTP 403** and body `{"__mcma_blocked": true, "endpoint": ...}`.
2. Read-back verification **fails closed** on that sentinel.
3. Every blocked call writes an `audit_events` row.
4. A run containing any blocked mutation is reported as `SIMULATED` — **never** as `success`.

### 11.4 Selectors are not endpoints

v3.0 listed `#DEVISDET_Btn` and `#Enregistrer` under "Blocked Endpoints" alongside `cloturerMission`.
The first two are DOM element IDs, guarded by never clicking them; the third is a URL, guarded by
network interception. They are enforced by entirely different mechanisms and must be documented in
separate lists — conflating them is how one comes to believe a click-guard is a network guard.

### 11.5 Human handoff — replacing `page.pause()`

⬜ **PLANNED** — 🟡 today, `main.py:236` and `mission_navigator.py:130` both call `page.pause()`

`page.pause()` requires the Playwright Inspector, blocks the workflow indefinitely, and **holds the
account lock the entire time**. On a machine running the app as a scheduled task, nobody can resume
it, and the account stays locked until the process is killed. It is a development tool, not a
production review workflow.

**Target flow for every `DRAFT_WRITE` job:**

```
execute allowed writes
  → verify every saved value by read-back (fail closed — see §11.6)
  → capture screenshots
  → generate a before/after readiness report
  → write it to automation_jobs.result_json
  → set status = REVIEW_REQUIRED
  → close the browser
  → release the account lock
  → employee reviews the report in the dashboard and performs final validation manually,
    in their own browser
```

The readiness report records, per rubrique: the intended value, the value read back from the portal,
whether they match, the HTTP status of each write, and any blocked call. An expert should be able to
approve or reject from the report alone, without a live browser.

### 11.6 Read-back verification must gate the result

🟡 **This is a live defect in both engines.**

Both controllers compute a verification and then ignore it:

```python
# mode_normal.py — computes has_locked_row, logs it if true, then:
success_count += 1        # unconditional

# mode_conventionne.py::_edit_single_row_dynamic — computes readback, logs it if found, then:
return True               # unconditional
```

The `expect_response("updateDevisDet")` wait is additionally wrapped in a `try/except` that logs at
`INFO` and continues. **A save that never happened is reported as success in both engines today.**

**Required:** read-back failure, a non-200 write response, and a `__mcma_blocked` sentinel must each
fail the row, fail the job, and appear in the readiness report. Verification that cannot fail is
decoration.

---

## 12. Operations

⬜ **PLANNED** — this section did not exist in v3.0, and it is where the system will actually fail

### 12.1 Process supervision — a logon task, not a service

Today the system is a `.bat` window that must not be closed (`DEMARRER_MCMA.bat`). One accidental
Ctrl+C or reboot and the whole agency loses the dashboard, silently and without notice.

**Constraint:** §6 requires opening a **visible Chromium window** on the desktop for OTP login. A
Windows service runs in **Session 0**, which is isolated from every interactive desktop — a headed
browser launched from there is invisible to the user. **v4.0 specified NSSM and a visible OTP
browser simultaneously; those are mutually incompatible.**

| Option | Verdict |
|:---|:---|
| **A. Task Scheduler, "run only when user is logged on", triggered at logon, restart on failure; the PC auto-logs into a dedicated agency Windows account** | ✅ **Adopted for v1.** Simplest thing that satisfies both constraints |
| B. FastAPI + poller as a Session 0 service, plus a small interactive desktop helper that owns Playwright and OTP | Cleaner separation; correct long-term shape. Defer until A proves limiting |
| C. Keep the PC permanently logged in and launch at login | Equivalent to A but without the restart policy. Not preferred |

Under Option A: no terminal window (`pythonw`, or a hidden-window task), automatic restart on
failure, automatic start at logon, and the desktop session stays open so the OTP browser can render.
Configure the PC not to lock the session, or ensure the login browser is launched only when a user is
present.

### 12.2 Backup, migration, and visibility

**Backup.** One PC, one `.db` file. A nightly `VACUUM INTO 'backups/mcma-YYYYMMDD.db'` at 18:15
(after the window closes), keeping 14 days, plus a copy to a second machine or NAS — a permanently
connected USB drive is the least reliable of the options and should be a last resort.

**Migration from JSON.** Employees have real notes in `logs/notification_actions.json` today. The
cutover must import them in the same change that introduces SQLite — matching on `reference` and
attaching to the correct `claim_id`, with unmatched entries reported rather than dropped.

**Time and dates.** Portal dates arrive as `DD/MM/YYYY HH:MM` strings. Store them normalised as ISO
in `date_survenance`, keep the original in `date_survenance_raw` for traceability, and resolve every
window computation through `Africa/Casablanca` (§5).

**Failure visibility.** Any account whose `last_successful_poll_at` is stale, whose session is
`EXPIRED`, or whose last poll was `PARTIAL`, must be visible **on the dashboard itself**. A log file
nobody opens is not monitoring.

---

## 13. Code Distribution & Data Hygiene

⬜ **PLANNED — action required before any deployment**

> ⚠️ **Do not make the repository public in order to transfer code to the agency.**

`static/app.js:6-150` is committed and contains what appear to be **real sociétaire names, policy
numbers, plates, and `id_sinistre` values** hardcoded as `SAMPLE_NOTIFICATIONS`. The `.gitignore`
carefully excludes `input_dossier/` and `logs/`, and this walks straight past it. Because the data is
in **git history** (commit `c6828fc` and earlier), deleting it now and then flipping repository
visibility would still expose it.

**Required before deployment:**

1. Replace `SAMPLE_NOTIFICATIONS` with obviously fictional fixtures, in the style of
   `json_dossier_example.md` (`ALAOUI Mohamed` / `12345-A-7`), which is correctly synthetic.
2. Scrub history if the repository will ever be made public.
3. Transfer the code **without** publishing the repository:
   - `git bundle create mcma.bundle --all` → USB → `git clone mcma.bundle` (full history, offline); or
   - add the agency machine as a collaborator / read-only deploy key on the **private** repo; or
   - a plain zip of the working tree — history is not needed on a machine that only runs the code.

---

## 14. Code Structure

🟡 **PARTIAL**

`core/constants.py:12` and `mapper/wexia_mapper.py:23` both define `RUBRIQUE_CATALOG`, and duplicate
`normalize_text` / `to_decimal` / `quantize_money`. Adding a rubric to one leaves the other silently
disagreeing — a live correctness risk in the financial mapper. `mapper/wexia_mapper.py` must import
from `core/`, leaving exactly one definition of the catalog.

Target layering (one direction of dependency, top to bottom):

```
core/      config, constants, utils, logger        — no I/O, imports nothing below
db/        schema, migrations, repositories        — the only module that touches SQLite
portal/    httpx client, auth, extractors          — the only module that talks to MCMA
browser/   Playwright: login, form filling, safety — used only where a real browser is required
mapper/    Wexia JSON → MCMA payload contract      — pure, deterministic, fully unit-tested
api/       FastAPI routes, scheduler, state endpoint
static/    dashboard (no build step)
```

---

## 15. Roadmap

Marked with what actually exists. Note that **Phase 2 is more built than Phase 1** — the automation
engine came first; the operations hub is the newer effort.

```
PHASE 0 — Prerequisite spikes and hygiene
├── 0. Close the Mode Normal interception gap + audit (§11.0)  🔴 BLOCKING ⬜
├── 1. httpx-vs-Playwright transport spike (§4.1)                       ⬜
└── 2. Remove real PII from static/app.js and history (§13)             ⬜

PHASE 1 — Multi-Account Notification & Action Hub  (CURRENT FOCUS)
├── 1. SQLite schema + WAL + changed_version + JSON migration           ⬜
├── 2. Multi-account model, per-account login button, session health    ⬜  (🟡 single-account seed)
├── 3. Scheduled in-window poller + category-scoped state machine (§8)  🟡  (extractor ✅, but see §8.2)
├── 4. Dashboard: account tabs, 15s delta polling, attribution, CSRF    🟡  (dashboard ✅)
└── 5. Task Scheduler deployment, nightly backup, health surfacing      ⬜

PHASE 2 — Automated Expertise Form Filling Agent
├── 1. Wexia ERP JSON import & deterministic mapper                     ✅  (12 unit tests)
├── 2. Mode Normal engine (#tableRapportDet)                            🟡  (see note)
├── 3. Mode Conventionné engine (#DevisDetTableVal)                     🟡  (see note)
├── 4. Two-tier safety policy + per-job allowlist + fail-closed (§11)   🟡
├── 5. Durable automation_jobs queue                                    ⬜
└── 6. Readiness report & human handoff (§11.5)                         ⬜
```

> 🔴 **Blocking Phase 0 item, ahead of everything above:** add `createRapportDefDet` to interception,
> remove the phantom `createDevisDet`, and audit the missions already touched by Mode Normal runs
> (§11.0). No further Mode Normal execution — in any mode, against the live portal — until this
> lands.

> **Why items 2 and 3 are 🟡, not ✅.** Both engines execute correctly on the happy path, and
> Conventionné's all-or-nothing matcher does guarantee unique row assignment (`used_indices` in
> `match_all_rubriques`, covered by `test_gc_unique_row_assignment`). But **read-back verification is
> computed and then discarded in both** (§11.6), so a failed save reports success. Separately, all 17
> unit tests are pure-function — **zero exercise the Playwright path**. These become ✅ only after
> read-back gates the result, offline captured-HTML integration tests exist, and one controlled
> onsite canary run has passed.

**Sequencing note.** Phase 1 items are ordered so that each is independently useful: the database
fixes the lost-write bug on day one, before any poller exists.

---

## 16. Resolved Decisions & Remaining Questions

### 16.1 Resolved

**R1 — Mode Normal endpoint (was Q6). CLOSED.** Confirmed against the network capture,
`mock_server.py:745`, and the generated client: Mode Normal calls
`POST /SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet`. `createDevisDet` does not exist on
the portal. §11.2 is finalised; §11.0 records the resulting safety gap and its remediation.

**R2 — `claims` vs `work_items` (was Q2). DEFERRED TO MEASUREMENT.** The single-table model in §7.2
ships as-is. Splitting would roughly double the schema and force employees to learn which of two note
fields they are editing, for a benefit whose size nobody has measured.

*Scheduled action:* run the category-scoped extractor (§8.2) for **one full week** in the agency and
count how often one `reference` appears under two or more categories — for example *MISSIONS
(FACTURES REÇUES)* versus *RELANCES REÇUES (EXPERT)*. Rare → keep the single table permanently.
Frequent → pay for the split before employees accumulate notes that would need migrating. This
measurement is only possible once §8.2 lands, since today a failed category and an empty category
are indistinguishable in the output.

**R3 — Per-employee PINs (was Q3). DEFERRED ON THREAT-MODEL GROUNDS.** The 4–6 employees already
share the live portal credentials for all four accounts; any of them can log into the real insurer
system as any account and cause far greater impact than mis-attributing an internal note. PINs,
resets, and hashed storage would defend the smaller risk while the larger one remains unaddressed by
the agency's chosen operating model. Revisit if portal credentials ever stop being shared.

**Three controls adopted in place of PINs** — all mandatory, all specified in §9.2:

1. **Subnet-restricted firewall.** `Autoriser_Reseau_Local.bat` scoped to
   `remoteip=192.168.1.0/24`, private profile only. Guest Wi-Fi locked out. (Today it opens
   `profile=any`.)
2. **Mandatory CSRF protection** on every write endpoint, preventing drive-by requests from any
   other page an employee has open.
3. **Attribution** via name selection in `localStorage`, sent with every mutation to populate
   `updated_by` and `audit_events.actor`.

### 16.2 Still open

1. **Does the agency work Saturdays?** `POLL_DAYS` needs confirming. Hours are editable in settings
   either way (§5).
2. **Where does the nightly backup copy go?** A second PC or NAS is preferred over a permanently
   connected USB drive.
3. **What is the Phase 2 trigger?** Recommended: explicit, from the dashboard — the employee selects
   the claim, supplies the Wexia JSON, and requests `PLAN` or `DRAFT_WRITE`. Defer any watched-folder
   automation until claim-to-file matching is proven.
4. **Which missions need auditing for orphan rubrique rows** written by Mode Normal under the §11.0
   gap? Requires cross-referencing `logs/workflow_*.json` run records against the portal.
