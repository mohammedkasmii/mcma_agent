# Central server and workstation runners — architecture and deployment (Phase 1)

Status: **Phase 1 only.** This document describes what the central-server
composition (`mcma.app.central_server`) does today and what is deliberately
not built yet. **Copying the application to Ubuntu is not sufficient for
production** — see [§9 Out of scope](#9-what-remains-out-of-scope-for-phase-1)
and [§8 Session re-authentication](#8-notification-session-re-authentication).
Nothing here declares the live form-filling agent production-ready; INC-00 and
release gate G5 are unchanged.

## 1. Target topology

```
                      ┌──────────────── Ubuntu agency server (Phase 1) ───────────────┐
 employee browser ───▶│ reverse proxy (TLS) ─▶ mcma.app.central_server (one process)    │
                      │   API + built frontend · employee auth · central SQLite         │
                      │   shared notes / audit · 4 server-side notification sessions    │
                      │   headless notification browser + poller                        │
                      └─────────────────────────────────────────────────────────────────┘
                                   ▲  (Phase 2/3: registration, heartbeat, job claim)
                                   │
   ┌──────────── every employee workstation (Windows) — Phase 2/3 ────────────┐
   │ runner: own MCMA Oujda session · own MCMA Nador session                   │
   │ visible local Edge · existing planning + form-filling safety logic        │
   │ human review happens in that local Edge window                            │
   └───────────────────────────────────────────────────────────────────────────┘
```

## 2. Central server responsibilities (Phase 1)

* Serve the API and the built frontend over HTTPS (never plaintext).
* Employee authentication with the existing sessions, CSRF and per-account
  access checks. `local_single_user_mode` is rejected.
* Own the central SQLite database (forward-only migrations at startup),
  shared notes and audit history.
* Provision the four canonical portal accounts.
* Poll notifications for **all four** sessions (MCMA Oujda, MCMA Nador,
  MAMDA Oujda, MAMDA Nador) with **one headless** browser, and serve the manual
  "Actualiser" refresh through that same browser.
* Report health/readiness (`/health`, `/ready`).

**Agent creation is disabled in central Phase 1.** `POST /jobs/dry-runs` and
`POST /jobs/{id}/executions` return HTTP 503 with the stable code
`RUNNER_CONTROL_PLANE_UNAVAILABLE` (checked after authentication, CSRF and
permission, and *before* the body is read), so no Wexia input or job row is
ever stored — there is no runner to execute it. Job history/plan reads,
notifications, claims, employee actions and authentication are unaffected.
Phase 2 enables creation only after runner registration and dispatch exist
(the API takes an `agent_execution_available` flag; local mode passes `true`).

It never: processes jobs, launches a visible browser, builds a
`RunnerConfig`/`ActiveReviewRegistry`, targets `127.0.0.1:8080`, starts or
depends on `mock_server`, or runs an interactive login. The composition root
does not import or reference any of these, and
`tests/central/test_central_server.py` pins that.

## 3. Workstation runner responsibilities (planned, Phase 2/3 — not built)

Each Windows workstation will run its own runner with its **own** MCMA Oujda
and MCMA Nador sessions in a visible local Edge browser, executing the existing
deterministic planning and form-filling logic, with human review in that
window. The server will hold a workstation registry and dispatcher. None of
this exists yet: no registration, heartbeat, claim API, transport, local Edge
profiles, or dossier-level locks.

## 4. Session ownership

| Sessions | Owner | Purpose |
|---|---|---|
| MCMA Oujda, MCMA Nador, MAMDA Oujda, MAMDA Nador (4) | **server** | notification polling only |
| MCMA Oujda, MCMA Nador form-filling sessions | **workstation-local** (Phase 2/3) | form filling |

**MAMDA is notification-only**, permanently. Form filling applies to MCMA
Oujda and MCMA Nador only. **No mock portal exists in the production
topology**; the mock is a local/test artefact of the Windows pilot.

## 5. Runtime modes

| | `LOCAL_WINDOWS` (`python -m mcma.app.main`) | `CENTRAL_SERVER` (`python -m mcma.app.central_server`) |
|---|---|---|
| Settings | `local_settings()` (unchanged) | `load_central_settings()` — explicit file/env, fail-closed |
| Auth | local single-user on loopback | employee sessions + CSRF only |
| Browsers | visible shared browser **and** headless notification browser | headless notification browser only |
| Job processing | dry-run + execute polling | **none** |
| Notifications | `NotificationService` on the runner connection | the same `NotificationService` |
| Portal login | visible browser on the employee's machine | **not offered** (§8) |
| Bootstrap/onboarding sub-apps | mounted (loopback-checked) | **not mounted at all** |
| Storage | DPAPI (job inputs CURRENT_USER, sessions LOCAL_MACHINE) | AES-256-GCM key files |
| Single instance | Windows named mutex | `flock` on `instance_lock_path` |
| Startup reconcile of jobs | yes | no (jobs will belong to runners) |
| Agent creation (`POST /jobs/...`) | available | **503 `RUNNER_CONTROL_PLANE_UNAVAILABLE`** |

The notification polling logic lives once, in
`mcma/notifications/service.py`; both compositions use it. The helpers they
share (`build_app`, encryptor/backend selection, TLS config, session observer)
live in `mcma/app/composition.py`. `mcma.app.central_server` imports that module
and **never** `mcma.app.main`: importing it in a fresh interpreter loads none of
`mcma.execution.runner`, `mcma.portal.writer`, `mcma.portal.pilot_contracts` or
`ActiveReviewRegistry` (`tests/central/test_central_import_isolation.py`).

## 6. Configuration and secrets

Configuration is a TOML file named by `MCMA_CONFIG_FILE`, with `MCMA_<FIELD>`
environment overrides (see `deploy/central/mcma-central.example.toml`). There
are **no defaults** for the required settings, unknown keys are errors, and the
server refuses to start (listing every problem) when:

* `local_single_user_mode`, `allow_test_plaintext_job_inputs`,
  `allow_test_only_session_vault` or `dev_mode` is on;
* `allowed_host` is a loopback/mock target, or `headless_browser` is false;
* a required path is missing or relative;
* the database, vault, key or lock paths resolve inside a served directory
  (`frontend/dist`, `static`, `mcma/web`, plus `public_static_dirs`);
* the two key files are the same file — compared after resolving symlinks and
  `..`; hard links are detected at startup, and **identical key material in two
  different files is rejected** after loading;
* `tls_key_path` (the TLS *private* key — the public certificate is exempt) is
  inside a served directory;
* `api_host` is a wildcard bind, or no TLS certificate/key is configured
  (HTTPS is the only listener, direct or behind a proxy — ADR-0008).

Configuration holds **paths** to secrets, never secrets.

**Key files** (two, distinct — session vault and job inputs):

* exactly **32 raw bytes**: `install -m 600 /dev/null K && head -c 32 /dev/urandom > K`
* owned by the service user, mode `0600` or stricter — group/other access,
  wrong owner or a non-regular file is refused at startup;
* never created by the server: a missing key stops startup (a silently
  generated key would orphan every stored session);
* back them up separately from the database; losing a key makes the data it
  protects unrecoverable, and there is no rotation procedure yet.

Key files are **loaded once per process**, at startup: the validated keys back
the one session backend and the one job-input encryptor that the notification
service, manual refresh and the API all share; nothing re-reads a key file per
request. The TLS private key must also be owned by the service user with mode
`0600` or stricter (POSIX) — a `root:ssl-cert 0640` key is refused, so install a
service-owned copy or use a proxy that terminates TLS in front of an
internally-issued service key.

Ciphertext is a versioned envelope (`MCMA`, version `1`, random 96-bit nonce,
AES-256-GCM). The account id (sessions) or the purpose label is bound as
authenticated data, so a blob moved to another account, or opened with the
other key, fails. Wrong key, tampering and truncation are one indistinguishable
error; an unknown version is reported separately. There is no plaintext
fallback anywhere.

## 7. Safe Ubuntu layout

| Path | Purpose | Mode |
|---|---|---|
| `/opt/mcma/app` | code + built `frontend/dist` (read-only to the service user) | 0755 root |
| `/var/lib/mcma/` | database directory (`mcma.sqlite3`, `mcma.lock`) | 0700 `mcma` |
| `/var/lib/mcma/vault/` | encrypted session blobs | 0700 `mcma` |
| `/etc/mcma/` | `mcma.toml`, key files, TLS key | 0750 root:mcma dir; keys 0600 `mcma` |

Never under `/opt/mcma/app/frontend/dist`, `static` or `mcma/web`. Run as a
dedicated unprivileged user, e.g. a systemd unit with `User=mcma`,
`EnvironmentFile=` **not** used for key material,
`ExecStart=/opt/mcma/app/.venv/bin/python -m mcma.app.central_server`,
`Environment=MCMA_CONFIG_FILE=/etc/mcma/mcma.toml`,
`NoNewPrivileges=yes`, `ProtectSystem=strict`,
`ReadWritePaths=/var/lib/mcma`. Headless Chromium must be installed for that
user (`playwright install chromium` plus its OS libraries).

**Vault permissions are enforced at startup**, before the database opens or
anything is served (POSIX): `vault_dir` must already exist, be a real directory
(a symlink is refused), be owned by the service user and have no group/other
bits (`0700` or stricter). The check is made on an open descriptor
(`O_NOFOLLOW | O_DIRECTORY` + `fstat`), so it cannot be raced by swapping the
path. The server never creates the directory for you.

Single process, single worker: the `flock` lock refuses a second instance.

## 8. Notification session re-authentication

The server has no display. **A headless Ubuntu server cannot, and must not try
to, silently open a login/OTP window.** Consequences, by design:

* the central app does not offer interactive portal login;
* an expired portal session shows as needing reconnection, and refresh reports
  `RECONNECT_REQUIRED`;
* Windows DPAPI sessions are **not** migrated — DPAPI blobs are not portable and
  no import is attempted. The same holds for **retained job inputs**: dossier
  inputs encrypted with DPAPI CURRENT_USER on a Windows install cannot be read
  on Ubuntu (the central server uses a different key and format), so history
  from a pilot database is not carried over by copying the file.

Getting the four sessions onto the server therefore needs an **intentional
onboarding/import procedure that does not exist yet** (for example a
lease-guarded operator tool that stores a session captured on a workstation via
`mcma.portal.vault.store_session` with the Linux backend, or an operator-only
authenticated flow). Until it exists, the server starts and serves, but every
account reports "not connected" and polls nothing. Decide the procedure before
any real rollout.

## 9. What must not be reverse-proxied

* `/bootstrap-app/*` and `/onboarding-app/*` — not mounted by the central
  server, but **block them at the proxy anyway** (defence in depth). Their
  loopback check trusts the peer address; behind a proxy on the same host every
  request looks like `127.0.0.1`, which is exactly why they are not mounted.
* `/docs`, `/openapi.json`, `/redoc` — FastAPI defaults; block or restrict.
* `/health` and `/ready` — expose to the monitoring network only; they contain
  no secrets or paths, only enumerated component states.
* Forward `X-Forwarded-*` only from the proxy; the app does not trust client
  address headers for any authorisation decision.

## 10. Startup, shutdown, health

Startup (each step fails closed; nothing is served after a failure):
validate configuration → validate TLS certificate/key → verify the filesystem
(vault directory, TLS key, key-file aliases) → take the instance lock →
load both keys once and reject identical material → open database + forward-only migrations → provision the four
accounts → build the app → serve. The notification service starts **in the
background inside the ASGI lifespan**.

Shutdown: mark shutting down → cancel the poll task → close the headless
browser → close both database connections → release the lock.

**Runtime browser loss is detected and recovered.** A Chromium that launched
and later died is noticed by its own connection state (`is_connected()`,
checked every tick and every health read): the service reports `degraded`
immediately, drops the handle, closes the stale context, and relaunches after a
short retry delay (30 s, independent of the poll interval and of
`notifications_enabled`) — then returns to `ready` and polls with the
replacement. `BrowserSupervisor` never hands out a known-dead browser; manual
refresh meanwhile gets HTTP 503 `NOTIFICATION_BROWSER_UNAVAILABLE` (retryable,
never reported as a portal failure). Ordinary account/session polling failures
with a still-connected browser do **not** degrade the service.

Notification-browser failure **does not stop startup.** The server serves
employees (authentication, notes, audit stay correct), reports
`notifications: degraded`, and the service retries the browser launch every
poll interval. Rationale: taking the whole application out of rotation for a
Chromium problem is worse than serving it and saying so.

| Endpoint | Meaning |
|---|---|
| `/health` | `{"status", "db", "notifications", "shutting_down"}`; `status` ∈ `ok`, `starting`, `degraded`, `shutting_down` |
| `/ready` | 200 when the database answers and the server is not shutting down (also while notifications are starting/degraded); 503 otherwise |

`notifications` ∈ `starting`, `ready`, `degraded`, `stopping`, `stopped`.
Alert on `degraded`. No exception text, path or session data is ever included.

## 11. Dependency and database changes

* New pinned dependency `cryptography==50.0.1` (locked in `uv.lock`).
* No schema change; no migration added.

## 12. What remains out of scope for Phase 1

Enabling Agent creation (§2 — needs runner registration and dispatch) ·
Frontend login screen (the API login exists; no UI was built) · first-admin
creation on the central server (the loopback bootstrap app is intentionally not
mounted, so an offline admin-provisioning tool is needed before first use) ·
session onboarding/import (§8) · key rotation · runner registration, heartbeat,
job-claim API and remote transport · local Edge profiles · dossier-level locks ·
runner status/pairing UI · Windows installer/startup task · live SinAuto write
contracts (G5 stays closed) · noVNC/remote browser streaming · MAMDA form
filling · systemd unit / proxy configuration files as shipped artefacts.

---

# Docker deployment (Phase 2 foundation)

> **This is a deployment foundation, not a production go-live.** After this
> phase the following are still **not complete**:
>
> * **Employee UI login** — the API login exists, but no login screen was built;
>   the employee frontend cannot sign in yet.
> * **Offline first-admin provisioning** — there is no way to create the first
>   user on the central server (the loopback bootstrap app is deliberately not
>   mounted), so nobody can authenticate.
> * **Notification-session onboarding** — the four portal sessions cannot be
>   loaded onto the server yet; every account will report "not connected".
> * **Workstation runner control plane** — Agent creation stays HTTP 503
>   `RUNNER_CONTROL_PLANE_UNAVAILABLE`; no live form filling, no mock portal, no
>   central interactive portal login, no DPAPI migration.

Everything is in `deploy/central/`:

| File | Purpose |
|---|---|
| `Dockerfile` | multi-stage image (Node 22.23.3 builds `frontend/dist`; Python 3.14.7 + `uv sync --frozen --no-dev`; **Chromium headless shell only**); runs as user `mcma` (uid/gid 10001) |
| `compose.yaml` | one service, project `mcma-central`; hardened, isolated |
| `env.vm.example`, `env.production.example` | non-secret settings for the dev VM / the agency server |
| `mcma-deploy.sh` | the only entry point: init, keys, TLS, check, build, up, health, logs, down, backup, restore, rollback |
| `deploytool.py` | stdlib-only helper behind the script (also unit-tested) |
| `healthcheck.py` | in-container HTTPS `/ready` probe **with** certificate verification |
| `../../.dockerignore` | allow-list build context (no keys, DBs, `node_modules`, `.git`) |

## Design decisions

* **Isolation.** Project/container/network are all `mcma-central*`; the script
  refuses a project name not starting with `mcma` and pins `--project-name` on
  every Compose call. Storage is bind mounts under `MCMA_DATA_ROOT` (no named
  volumes, `create_host_path: false` so Docker never creates root-owned
  directories). The script never restarts Docker and never uses prune, `down -v`,
  `--remove-orphans`, `rm`/`stop`/`kill` on anything, or the Docker socket.
* **Network.** Private bridge `mcma-central-net` (configurable subnet) with a
  **static container address**. The app refuses wildcard binds, so it binds that
  address (`api_host = MCMA_CONTAINER_IP`); Docker publishes it to **one**
  `MCMA_BIND_ADDRESS:MCMA_HTTPS_PORT` (never `0.0.0.0`). No host networking; no
  SQLite/control port exists. TLS is the only listener — a bad certificate stops
  the process, there is no HTTP fallback (verified: plain HTTP to the published
  port gets no answer).
* **Hardening.** `read_only` rootfs, `tmpfs` `/tmp` (Chromium scratch; `HOME=/tmp`),
  `cap_drop: ALL`, `no-new-privileges`, `privileged: false`, `init`, private IPC
  with a 512 MB `/dev/shm` for Chromium, `restart: unless-stopped`, memory/CPU/PID
  limits, `json-file` log rotation (10 MB x 5). Keys, TLS and config mount
  **read-only**. Playwright launches Chromium in its default mode (no
  user-namespace sandbox), which is what lets it run without extra capabilities.
* **Healthcheck.** `python /opt/mcma/healthcheck.py` performs `GET /ready` over
  HTTPS, verifying the certificate against `MCMA_HEALTHCHECK_CA_FILE` (default:
  the server certificate) and the name `MCMA_TLS_SERVER_NAME`, which must be in
  the certificate's subjectAltName. Verification is never disabled. `/ready` is
  200 while notifications are starting/degraded (§10) — watch `/health` for that.
* **Image size.** about 1.2 GB on disk (Chromium shell 265 MB, its OS libraries, the
  locked venv 181 MB). Build tooling and `node_modules` are not in the final stage;
  `pymupdf` (unused under `mcma/`) and the CJK/emoji fonts are removed through apt.
  There is **no** `dpkg --force-depends` trimming: the package database is
  consistent, which `build` proves with `dpkg --audit` (must print nothing) plus a real
  headless-Chromium page navigation under the production flags (read-only rootfs,
  no capabilities, no network). Keep few tags: each rebuild adds a layer set.
* **Ownership marker and fail-closed inspection.** `init` writes `.mcma-data-root`
  and every later command requires it; Docker/route inspection failures abort
  instead of meaning "no conflict" (see the sections below).

## Host layout under `MCMA_DATA_ROOT`

| Path | Owner / mode | Mounted at | Contents |
|---|---|---|---|
| `db/` | 10001, 0700 | `/var/lib/mcma/data` (rw) | `mcma.sqlite3` (+WAL), `mcma.lock` |
| `vault/` | 10001, 0700 | `/var/lib/mcma/vault` (rw) | encrypted session blobs |
| `keys/` | 10001, 0700; files 0600 | `/etc/mcma/keys` (ro) | `session-vault.key`, `job-input.key` (32 raw bytes each, distinct) |
| `tls/` | 10001, 0700 | `/etc/mcma/tls` (ro) | `server.crt` 0644, `server.key` 0600 |
| `config/` | 10001, 0750 | `/etc/mcma/config` (ro) | `mcma.toml` (optional tuning only) |
| `backups/` | root, 0700 | (not mounted) | `mcma-backup-*.tar.gz` (0600) |

The TLS key is owned by uid 10001 because the application itself refuses a TLS
key that is not owned by its user or is group/other-readable.

## Development VM (Ubuntu 26.04, 192.168.11.111) — exact steps

Prerequisites: Docker + Compose plugin, `python3`, `openssl`, `git`, `sudo`.

```bash
git clone <repo> /opt/mcma-src && cd /opt/mcma-src
git checkout codex/central-server-workstation-runners
cp deploy/central/env.vm.example ~/mcma-vm.env     # review: port 18443, subnet 172.29.211.0/28
D="sudo ./deploy/central/mcma-deploy.sh --env-file $HOME/mcma-vm.env"

$D init                    # /data/mcma-dev: marker + layout (refuses an unmarked non-empty directory)
$D gen-keys                # two distinct 32-byte keys (refuses to overwrite)
$D gen-dev-cert            # DEV ONLY: self-signed, SAN IP:192.168.11.111
# (or provided files:  $D install-tls /path/server.crt /path/server.key)
$D check                   # env, permissions, key sanity, cert/key match + SAN, port free,
                           # subnet vs EVERY Docker network and IPv4 host route
$D build                   # build -> dpkg --audit + real Chromium navigation -> records the tag
$D up                      # preflight, compose up (never builds), waits until HEALTHY
```

`up` prints success only after the exact `mcma-central` container (Compose
project label and image reference checked) reports `healthy`. `$D health`
repeats that wait at any time.

### Trusting the development certificate from another computer

The certificate on the VM is self-signed, and `/data/mcma-dev/tls/` is
owner-only, so a client machine cannot (and must not) read it from that path.
Fetch the **public** certificate through the script, and verify it out-of-band:

```bash
# on the VM (prints the SHA-256 fingerprint to the terminal)
$D show-cert > /dev/null
# on the client machine: fetch it over SSH (the private key is never read or sent)
ssh <user>@192.168.11.111 'sudo /opt/mcma-src/deploy/central/mcma-deploy.sh --env-file /home/<user>/mcma-vm.env show-cert' > mcma-vm.crt
openssl x509 -in mcma-vm.crt -noout -fingerprint -sha256   # must equal the fingerprint shown on the VM
```

Only after the two fingerprints match, use it as the trust anchor:

```bash
curl --cacert ./mcma-vm.crt https://192.168.11.111:18443/health
# {"status":"ok","db":true,"notifications":"ready","shutting_down":false}
curl --cacert ./mcma-vm.crt https://192.168.11.111:18443/ready                      # 200
curl -sS -m 5 http://192.168.11.111:18443/health || echo "plain HTTP refused (expected)"
curl --cacert ./mcma-vm.crt -X POST https://192.168.11.111:18443/jobs/dry-runs      # 401 (no login)
```

For a browser on a Windows PC, import `mcma-vm.crt` into *Trusted Root
Certification Authorities* for that test PC only (`certutil -addstore -f Root
mcma-vm.crt`, elevated) and remove it afterwards. **Never** use this self-signed
certificate or a `-k`/insecure flag in production: production uses the agency's
internal-CA certificate and root distribution in `deploy/tls/README.md`.

`notifications: "ready"` means the headless Chromium inside the read-only
container launched. Expected state right now: HTTP 200 on `/health` and `/ready`,
the UI shell loads at `/`, **nobody can log in** (no admin provisioning), and no
account is connected (no session onboarding).

Operate: `$D status`, `LOGS_FOLLOW=1 $D logs 200`, `$D down` (stops and removes only
the `mcma-central` container and its network; data is untouched), `$D images`.

## Immutable image delivery (VM builds and tests, production only loads)

The agency server has a nearly full root filesystem and runs unrelated
applications, so **production never builds** (`MCMA_ALLOW_BUILD=false` in its env
file; `build` refuses). The exact image tested on the VM is what runs there.

```bash
# --- on the VM: build + verify, then export the exact tagged image ---------
$D build                                   # prints the tag, e.g. 20260927-101500-ab12cd3
$D export-image 20260927-101500-ab12cd3 /srv/mcma-release
#   mcma-central-<tag>.tar.gz              docker save | gzip (deterministic gzip header)
#   mcma-central-<tag>.tar.gz.sha256       "<sha256>  <file>"
#   mcma-central-<tag>.tar.gz.image-id     the local image id + reference

# --- copy the three files to production (scp/rsync/USB) ----------------------
# --- on production: verify, load, verify again -------------------------------
D="sudo ./deploy/central/mcma-deploy.sh --env-file /data/mcma/config/mcma.env"
$D import-image /path/mcma-central-<tag>.tar.gz
#   1. recomputes SHA-256 and compares with the .sha256 file  -> abort on mismatch, nothing loaded
#   2. reads the image names INSIDE the archive; anything other than exactly
#      mcma-central:<tag> aborts BEFORE `docker load`
#   3. refuses to replace an existing tag whose image id differs (tags are immutable)
#   4. docker load, then compares the loaded image id with the recorded one
$D set-tag <tag>
$D up                                      # preflight, start, wait until healthy
```

`import-image` proves the archive is the one exported (checksum) and that Docker
now holds the same image (id). It does not authenticate *who* produced it: send
the `.sha256` over a channel you trust independently of the archive.

## Backup, restore, rollback

```bash
$D backup                    # consistent SQLite snapshot (online-backup API, safe while running)
                             # + vault + config -> backups/mcma-backup-<UTC>.tar.gz (0600)
$D backup --include-keys     # also the two keys: store such an archive like a secret
$D down
$D restore /data/mcma-dev/backups/mcma-backup-<UTC>.tar.gz [--with-config] [--with-keys]
$D check && $D up
```

`restore` first **positively establishes** that the exact `mcma-central`
container is not running (a Docker failure, permission error, timeout or an
ambiguous answer aborts it). It then validates the archive: no path traversal,
only known entries, a strict `MANIFEST.json` (well-formed, safe relative paths,
every listed file present, **no file that is not listed**, `db/mcma.sqlite3`
required, SHA-256 of each file), and a SQLite integrity check. It **keeps** the
replaced database (`db/mcma.sqlite3.pre-restore-<UTC>`) and vault
(`vault.pre-restore-<UTC>/`) instead of deleting them. Keys are not in the
default archive: back them up separately — without them the vault and job inputs
are unreadable, and they are never regenerated.

Rollback to a previously loaded/built image: `$D images`, then `$D rollback <tag>`.
It is transactional: the previous `MCMA_IMAGE_TAG` is remembered; if preflight,
Compose or the health wait fails, the env tag is restored, the previous image is
brought back and verified healthy where possible, and the command exits non-zero
saying exactly what happened. Success is printed only after the replacement
container is healthy. **Data is never rolled back automatically** — use `restore`.

## Production (Ubuntu 24.04, `/data/mcma`, shared Docker host)

Same procedure with `env.production.example` copied to a root-owned, 0640 file,
**except that nothing is built there** (see *Immutable image delivery*). Before the
first `up`:

* `init` refuses `/`, broad system/shared paths (`/data`, `/opt`, `/home`, `/etc`, …),
  a symlinked `MCMA_DATA_ROOT`, and any existing non-empty directory that lacks the
  `.mcma-data-root` marker — so a mistyped path cannot chmod/chown another
  application's directory. It never changes the mode/owner of a directory it did
  not create (an *empty* existing directory is adopted; only its contents are set up);
* replace `MCMA_BIND_ADDRESS` and `MCMA_TLS_SERVER_NAME` (the example placeholders
  are refused by `check`) and choose a **free** port — `check` fails if the address
  is already listening;
* pick an `MCMA_NET_SUBNET` that overlaps no existing Docker network **and** no IPv4
  host route — `check` reads both (never modifying either) and fails on any overlap,
  and **also fails if Docker or the routing table cannot be read** (it never assumes
  "nothing there"). The RMA/Wexia/Supabase networks are only *read*;
* use the internal-CA certificate (`deploy/tls/README.md`) via `install-tls`, with
  the server name/IP in its subjectAltName; **do not** use `gen-dev-cert`;
* the image is about 1.2 GB: confirm free space under Docker's data directory first,
  keep one previous tag for rollback, and remove older ones deliberately with
  `docker rmi mcma-central:<tag>` — nothing here prunes anything;
* Docker is never restarted by any of these commands. The project, container and
  image repository are fixed to `mcma-central`; the env file must say so and no
  other image is ever tagged, run or loaded.

## Renewing the TLS certificate

`install-tls NEWCERT NEWKEY` validates and swaps the files atomically; then run
`$D down && $D up` in a maintenance window (single worker, brief gap), per
`deploy/tls/README.md`. A `restart` command is deliberately not provided.
