# INC-01 — Test egress lockdown runbook (G0)

## Chosen authoritative mechanism (one concrete implementation)

A **named Linux network namespace** created with `iproute2` on the GitHub
Actions `ubuntu-latest` runner (`.github/workflows/inc01-no-egress.yml` →
`ci/run_tests_in_netns.sh`). A fresh namespace contains **only** the loopback
interface: no non-loopback IPv4/IPv6 interface, no default route, **no direct
route of any kind** (all v4/v6 route tables are loopback-only), while the
loopback mock/echo servers remain fully usable. `pytest`, every subprocess it
spawns, and headless Chromium all execute inside the namespace and inherit it
(namespaces are inherited on fork/exec). Chromium runs unprivileged with its
**normal sandbox** — `--no-sandbox` is never used; if Chromium cannot launch
safely inside the namespace, CI fails and the problem is diagnosed. (The
workflow lifts Ubuntu 24.04's AppArmor restriction on unprivileged user
namespaces on the ephemeral VM so Chromium's own sandbox can operate; that
setting enables the sandbox, it does not weaken it.)

Container `--network none` was considered and rejected for this repo: the
namespace approach needs no image build, keeps the setup-python toolchain,
and produces the same guarantee with less machinery.

## Evidence chain — what actually proves egress denial

Connection failure to the sentinel targets (`192.0.2.1` — RFC 5737
TEST-NET-1; `egress-sentinel.invalid` — RFC 2606) **is not, by itself, proof
of egress denial**: a blackhole fails from anywhere. The authoritative
evidence is all of:

1. **Enforced isolation** — the suite runs inside the namespace the runner
   script creates (unique name `mcma_no_egress_<pid>`, deleted by trap on
   every exit path);
2. **Structural preflight** (`testsupport/egress_guard.py::structural_preflight`)
   confirming, by inspection only (never dialing): `lo` is the **only**
   interface (extra DOWN interfaces rejected); **all** IPv4/IPv6 route tables
   (`table all`, not just main/default) contain only `lo`-bound routes; the
   process is inside the **named** namespace (`MCMA_NETNS_NAME` inode match
   against `/proc/self/ns/net`); the process is non-root with an **all-zero
   effective capability set** (cannot create interfaces, change routes, or
   escape the namespace);
3. **Inheritance** — the subprocess proof spawns a fresh *unguarded* Python,
   and the Chromium proof launches a real headless browser: both inherit the
   namespace;
4. **Their sentinel attempts failing inside that verified environment.**

The real MCMA production hostname is never dialed, resolved, or referenced
as a target by any test.

## Layers (defense in depth)

| Layer | Where | Covers |
|---|---|---|
| Network namespace (authoritative) | CI runner script | Python, subprocesses, Chromium, C extensions |
| Structural preflight | plugin, before any `requires_egress_isolation` test body | verifies the effective environment |
| Python guard (`testsupport/egress_guard.py`) | loaded pre-collection via `pyproject.toml` addopts `-p` + root `conftest.py` | TCP/UDP connect+send, DNS (blocked before the resolver) in-process |
| pytest-socket 0.7.0 | `--disable-socket --allow-hosts=127.0.0.1,::1` | redundant in-process blocking |

The guard is idempotent, captures originals exactly once, and exposes **no**
uninstall/disable/restore function.

## Local development (Windows/macOS)

- **Never** change the host firewall — INC-01 executes no firewall command
  and requires none.
- The three `requires_egress_isolation` tests **fail at setup, before their
  bodies run** (no subprocess dial, no browser launch) on any host that is
  not verified loopback-only. This is fail-closed by design.
- For day-to-day local work, deselect them explicitly and visibly:

  ```
  python -m pytest tests/ -m "not egress_proof"
  ```

  Deselection is acceptable because the dangerous test then does not run at
  all; nothing can make a browser/subprocess proof execute without confirmed
  isolation.
- Always run via `python -m pytest` from the repo root (puts the repo on
  `sys.path` so the guard plugin loads before collection).

## Browser evidence policy (from the browser increments onward)

Beginning with the browser-related increments (INC-06+), **official browser
evidence comes only from the isolated CI runner** — a local browser run is
never acceptance evidence.

## G0 acceptance

G0 is satisfied only when the pushed `inc01-no-egress` workflow is green:
the entire suite — all pre-existing tests, all guard unit tests, and **all
five** proof tests — passing inside the namespace. Until then the status is:
"INC-01 implementation prepared locally; G0 pending CI evidence."
