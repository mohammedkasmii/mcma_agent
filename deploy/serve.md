# Serving the application — single Windows service, one worker

INC-18 / ADR-0008. This is a single-writer, single-instance application
(INC-11's OS mutex is the authoritative guarantee) — it is deployed as
exactly ONE Windows service/process, never load-balanced across workers.

## Process model

- **One Uvicorn worker.** `mcma.app.serve.serve(app, config)` calls
  `uvicorn.run(...)` directly (no `--workers N`, no process manager that
  would spawn more than one). Multiple workers would each try to hold
  INC-11's single-instance mutex and account leases independently, which
  the mutex is specifically designed to prevent — a second worker fails to
  acquire it and must not silently proceed.
- **The OS mutex is checked at process startup**, before the HTTP listener
  opens (`mcma.core.mutex.create_single_instance_mutex`) — a second
  instance (accidental double-launch, or a previous instance that failed
  to exit cleanly) refuses to start rather than racing the first.

## Bind address and subnet

- `mcma.core.config.Settings.api_host`/`api_port` control the bind address;
  for LAN deployment this is a specific interface/IP, never a blanket
  `0.0.0.0` firewall rule "for any profile" (the baseline's known failure,
  `docs/recovery/KNOWN_FAILURES.md` F18).
- `subnet_allowlist` (e.g. `("192.168.1.0/24",)`) is **defense-in-depth
  only** (`mcma.app.serve.SubnetAllowlistMiddleware`) — it is empty by
  default, and when configured it can only ADD a network-level rejection on
  top of authentication; it never substitutes for authentication and is
  never sufficient on its own (`test_subnet_filter_absent_does_not_disable_auth`,
  `test_subnet_allowlist_never_bypasses_the_underlying_apps_own_auth`).
- Windows Firewall should still be configured to allow the chosen port only
  on the appropriate network profile (Private/Domain, not Public) as a
  second, OS-level layer — this is an operational step, not something the
  application enforces.

## TLS

See `deploy/tls/README.md` for certificate issuance, distribution, renewal,
and failure handling. The service will not start without a valid cert/key
(`mcma.app.serve.TlsConfigurationError`) — there is no HTTP fallback.

## Startup sequence (single process)

1. Acquire the OS single-instance mutex (fail closed if already held).
2. `mcma.persistence.db.open_database(...)` — connect + run forward-only
   migrations.
3. `mcma.execution.reconcile.reconcile_on_restart(...)` — deterministic
   restart reconciliation (WORKFLOW_STATE_MODEL.md §7) before serving any
   request.
4. Build the authenticated API app (`mcma.app.api.app.create_api_app`).
5. `mcma.app.serve.serve(app, tls_config)` — validates the cert/key
   (fail closed) and starts the single Uvicorn worker over HTTPS only.

## Windows service registration

For the pilot (single employee machine), running the process under a
Windows service wrapper (e.g. NSSM, or `sc.exe create` against a small
wrapper executable) ensures it restarts on machine reboot and survives an
interactive-session logout. This is an operational choice made at
deployment time, not something this repository's code depends on — the
process above is identical whether launched interactively or as a service.
