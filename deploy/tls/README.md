# TLS deployment — internal CA, distribution, renewal, failure handling

INC-18 / ADR-0008. The service (`mcma.app.serve`) refuses to start without a
valid certificate and private key — there is **no plaintext HTTP listener**,
not even a redirect. This document is the operational runbook; the code-level
guarantee lives in `mcma/app/serve.py` and its tests (`tests/app/serve/`).

## 1. Internal CA

The agency's single Windows machine (pilot scope) is both the CA and the
server. Use an internal, self-issued CA rather than a public CA — this
service is never internet-reachable.

1. Generate the CA root (once, kept offline/backed up):
   ```
   openssl genrsa -out mcma-ca.key 4096
   openssl req -x509 -new -key mcma-ca.key -sha256 -days 3650 \
     -out mcma-ca.crt -subj "/CN=MCMA Internal CA"
   ```
2. Issue the server certificate (renewed per §3):
   ```
   openssl genrsa -out server.key 2048
   openssl req -new -key server.key -out server.csr \
     -subj "/CN=<server-hostname-or-LAN-IP>"
   openssl x509 -req -in server.csr -CA mcma-ca.crt -CAkey mcma-ca.key \
     -CAcreateserial -out server.crt -days 397 -sha256
   ```
   397 days is the current practical CA/Browser Forum ceiling for
   publicly-trusted certs; an internal CA is not bound by it, but staying
   under it keeps the renewal cadence predictable and keeps client software
   that enforces the limit happy if this cert is ever inspected by such a
   client.
3. Point `mcma.core.config.Settings.tls_cert_path` / `tls_key_path` at
   `server.crt` / `server.key`. Never commit either to the repository —
   both live outside version control (e.g. `var/tls/`, itself outside any
   served directory per DATA_MODEL.md §9).

## 2. Root distribution to office machines

Each employee machine that will connect to the dashboard needs `mcma-ca.crt`
installed as a **trusted root** so the browser does not warn on every visit:

- **GPO (preferred, multi-machine):** import `mcma-ca.crt` into
  `Computer Configuration > Policies > Windows Settings > Security Settings >
  Public Key Policies > Trusted Root Certification Authorities`.
- **Manual (single-machine pilot):** `certutil -addstore -f "Root" mcma-ca.crt`
  (run as Administrator), or via `certmgr.msc` → Trusted Root Certification
  Authorities → Import.

Never distribute `mcma-ca.key` — only the `.crt` (public certificate) is
installed on client machines.

## 3. Renewal with overlap

Renew the server certificate **before** it expires, with an overlap window
so there is never a gap:

1. At ~75% of the current cert's validity period, issue a NEW server cert
   (§1 step 2) with a fresh key.
2. Deploy the new cert/key pair to `var/tls/` alongside the old one.
3. Update `tls_cert_path`/`tls_key_path` to the new files and restart the
   service (a graceful restart during a maintenance window — this is a
   single-worker service, so there is a brief connection gap, not a
   rolling deploy).
4. Verify the new cert is being served (`test_valid_cert_and_key_succeed`-
   style check, or simply confirm no browser warning) before deleting the
   old cert/key pair.
5. The CA root itself (10-year validity) is renewed on its own, much
   longer cycle — track its expiry separately and re-run §2 on renewal.

## 4. Failure handling — the service refuses to serve

If the cert/key is missing, unreadable, corrupt, or does not match, the
service **does not start** (`mcma.app.serve.TlsConfigurationError`, raised
by `build_ssl_context`/`build_uvicorn_ssl_kwargs` before any listener opens).
This is deliberate fail-closed behavior — there is no plaintext fallback to
"still serve something." Recovery is always: fix or replace the cert/key
files, then restart the service.

## 5. Dev-mode loopback TLS

A developer machine may use a locally-generated self-signed cert bound to
`127.0.0.1` only (`tests/app/serve/serve_test_support.py` generates exactly
this kind of cert for tests, via the local `openssl` CLI — no external
cert-service is ever contacted). Production MUST use the internal-CA-issued
cert from §1; there is no code path that lets a dev cert accidentally serve
a LAN-bound production listener — the cert/key files are what differ, not
the code path.
