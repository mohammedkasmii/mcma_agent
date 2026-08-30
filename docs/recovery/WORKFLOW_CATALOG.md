# WORKFLOW CATALOG

**Baseline commit SHA:** `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`

Each workflow lists its trigger, step sequence with `file:line` evidence, side effects, and safety notes. **Live form-filling is prohibited until the safety gates in `SAFETY_INVARIANTS.md` are fixed.**

---

## W1 — One-time login / session save

- **Trigger:** `python auth_setup.py` (or `Se_Connecter_MCMA.bat`, dashboard button, `POST /api/v1/auth/launch-login`).
- **Steps:**
  1. Launch **headed** Chromium (`auth_setup.py:9`).
  2. Navigate to the portal root (`:14`).
  3. Poll once/second up to 300 s for success heuristics (`:24-55`).
  4. Save storage state to `mcma_auth_state.json` (`:62-63`).
  5. Print result; close browser (`:65-73`).
- **Side effects:** writes the session file to CWD.
- **Safety note:** step 4 executes **even on timeout** and prints SUCCESS if the file exceeds 10 bytes (`:50-51,63,65-69`) — an unauthenticated file passes. Fail-open.

## W2 — Notification extraction (dashboard data)

- **Trigger:** `python get_notifications.py [--headless]`, `Extraire_Notifications_MCMA.bat`, or `GET /api/v1/notifications`.
- **Steps:**
  1. Require `mcma_auth_state.json`, else exit/401 (`get_notifications.py:35-40`; `main.py:135-136`).
  2. Launch Chromium with saved state (`get_notifications.py:49-51`; `main.py:139-140`).
  3. Navigate the mission route (canonical `/expertise/frontexpert/`; code uses the case variant `.../expertise/FrontExpert/`); `check_session_validity` else raise (`browser/notifications.py:180-185`).
  4. Refresh navbar alerts; discover categories from `#listeAlertes a[href*="notification/alerte/"]` (`:203`).
  5. Per category: in-page fetch POST to `.../notification/getAlerte/CodeAlerte/{code}` with `length=-1` (`:33-101`); DOM DataTable fallback (`:108-170`).
  6. Write `logs/mcma_notifications.json` (`get_notifications.py:57-62`; `main.py:146-148`).
- **Side effects:** live authenticated reads; overwrites the cache JSON (non-atomic).
- **Safety note:** read-only against the portal. `Extraire_Notifications_MCMA.bat` ignores the exit code and prints success regardless (`:18`).

## W3 — Session keep-alive / health

- **Trigger:** `python session_keeper.py` (daemon) or `--check` (one-shot).
- **Steps:** every N minutes (default 10), launch headless Chromium, probe the dashboard URL, classify logged-in/out, rewrite the auth file on success (`session_keeper.py:151-180,128`).
- **Side effects:** repeated live probes; auth-file rewrite (race with W2/W4, no lock).
- **Safety note:** not scheduled by anything in the repo; infinite silent retry with no escalation.

## W4 — Fill dossier (form-filling) — **PROHIBITED IN LIVE USE AT BASELINE**

- **Trigger:** `python run_dossier.py [--json ...]`, `POST /api/v1/fill-dossier`, or `POST /api/v1/fill-dossier-from-wexia`.
- **Baseline Unsafe Steps (`main.py:178-256` `process_workflow`):**
  1. Load + map input (mapper, or raw payload) → dossier payload.
  2. Launch Chromium with saved state (`main.py:203-206`, `headless=False` hardcoded).
  3. Install network safety policy (`main.py:210`, gated on `TEST_MODE`).
  4. `search_and_open_mission` (`main.py:213`) → search, select, open, "verify" (identity check is absent — see `KNOWN_FAILURES.md`).
  5. `fill_main_form` (`main.py:216`).
  6. Detect mode via live DOM (`main.py:219-231`): `fill_garage_conventionne` (conventionné) or `fill_mode_normal` (normal). **Both write row-level data to the portal.**
  7. `page.pause()` for human review (`main.py:244`) — occurs **after** row writes.
- **Side effects:** **row-level writes** (`updateDevisDet`, `createRapportDefDet`) that are **not** network-blocked. Final saves (`Enregistrer`/`Valider`/`Clôture`/GED) are not clicked and are blocked.
- **Target Behavior:** The target architecture uses explicit `ExecutablePlanData` driving two typed execution workflows (`add_normal_row` / `edit_conventionne_row`), and requires mandatory financial verification before stopping at `READY_FOR_HUMAN_REVIEW`. Refer to `docs/architecture/PORTAL_ROW_WORKFLOWS.md`.

## W5 — Employee action tracking (dashboard)

- **Trigger:** employee interacts with `static/` dashboard served at `/`.
- **Steps:** load actions + cached notifications (`app.js:206,219`); cycle status TODO→IN_PROGRESS→DONE→WAITING (`app.js:508-516`); edit notes; persist to `localStorage` + `POST /api/v1/notification-actions` (`app.js:529-535` → `logs/notification_actions.json`).
- **Side effects:** local file + browser storage writes only; nothing pushed to the portal.
- **Safety note:** last-write-wins across employees (no versioning); "WAITING/Relancé" is local-only, not a portal relance.

## W6 — Employee 1-click startup (Windows)

- **Trigger:** double-click a `.bat`/`.url`.
- **Steps:** `DEMARRER_MCMA.bat`/`Lancer_MCMA_Dashboard.bat` verify Python, print URLs, run `python main.py`; `Autoriser_Reseau_Local.bat` adds a firewall rule (TCP 8000, `profile=any`); `Ouvrir_MCMA_Employe.bat`/`.url` open `http://192.168.1.17:8000`.
- **Safety note:** hardcoded LAN IP drifts on DHCP change; firewall rule opens the port on all profiles including Public.
