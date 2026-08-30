#!/usr/bin/env bash
# INC-01 — run the ENTIRE test suite inside a loopback-only Linux network
# namespace. Must be invoked as root (sudo) WITH EXPLICIT ARGUMENTS — it
# never assumes GITHUB_WORKSPACE, SUDO_USER, or the setup-python PATH
# survives sudo:
#
#   sudo bash ci/run_tests_in_netns.sh <repo_root> <run_as_user> <python_bin>
#
# Guarantees:
#   - unique namespace name (mcma_no_egress_$$), always deleted via trap on
#     success, failure, interruption, or timeout;
#   - repo root, unprivileged user, and python executable are validated
#     before any privileged action;
#   - pytest executes as the original unprivileged UID/GID (setpriv), never
#     as root, with a minimal explicitly-constructed environment;
#   - an overall timeout so a hung Chromium/socket cannot hang the job.
set -euo pipefail

REPO_ROOT="${1:?usage: run_tests_in_netns.sh <repo_root> <run_as_user> <python_bin>}"
RUN_AS_USER="${2:?run_as_user required}"
PYTHON_BIN="${3:?python_bin required}"

OVERALL_TIMEOUT="${MCMA_NETNS_TIMEOUT:-900}"

# --- validation, before touching anything privileged -----------------------
[[ "$(id -u)" -eq 0 ]] || { echo "FATAL: must run as root (sudo)"; exit 9; }
[[ -d "$REPO_ROOT" && -f "$REPO_ROOT/pyproject.toml" && -d "$REPO_ROOT/tests" ]] \
  || { echo "FATAL: '$REPO_ROOT' is not the repository root"; exit 10; }
id -u "$RUN_AS_USER" >/dev/null 2>&1 \
  || { echo "FATAL: user '$RUN_AS_USER' does not exist"; exit 11; }
[[ "$RUN_AS_USER" != "root" ]] \
  || { echo "FATAL: tests must not run as root"; exit 12; }
[[ -x "$PYTHON_BIN" ]] \
  || { echo "FATAL: python executable '$PYTHON_BIN' not found/executable"; exit 13; }

LINT_IMPORTS_BIN="$(dirname "$PYTHON_BIN")/lint-imports"
[[ -x "$LINT_IMPORTS_BIN" ]] \
  || { echo "FATAL: preinstalled lint-imports executable not found"; exit 17; }

RUN_UID="$(id -u "$RUN_AS_USER")"
RUN_GID="$(id -g "$RUN_AS_USER")"
HOME_DIR="$(getent passwd "$RUN_AS_USER" | cut -d: -f6)"
[[ -n "$HOME_DIR" && -d "$HOME_DIR" ]] \
  || { echo "FATAL: cannot resolve home for '$RUN_AS_USER'"; exit 14; }

# --- namespace lifecycle ----------------------------------------------------
NS="mcma_no_egress_$$"
cleanup() { ip netns delete "$NS" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

ip netns add "$NS"
ip -n "$NS" link set lo up

echo "== structural evidence for namespace $NS =="
ip netns exec "$NS" ip -o link
ip netns exec "$NS" ip -o addr
echo "-- IPv4 routes (all tables) --"
ip netns exec "$NS" ip -4 route show table all || true
echo "-- IPv6 routes (all tables) --"
ip netns exec "$NS" ip -6 route show table all || true
if ip netns exec "$NS" ip route get 192.0.2.1 >/dev/null 2>&1; then
  echo "FATAL: sentinel 192.0.2.1 is routable inside the namespace"; exit 15
fi
echo "== sentinel is unroutable; entering namespace as uid=$RUN_UID gid=$RUN_GID =="

# --- run the FULL suite unprivileged inside the namespace -------------------
# env -i: only the values below exist; nothing is inherited implicitly.
timeout --signal=TERM --kill-after=30 "$OVERALL_TIMEOUT" \
  ip netns exec "$NS" \
  setpriv --reuid "$RUN_UID" --regid "$RUN_GID" --init-groups \
  env -i \
    HOME="$HOME_DIR" \
    PATH="/usr/bin:/bin" \
    LANG="C.UTF-8" \
    MCMA_NETNS_NAME="$NS" \
    PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME_DIR/.cache/ms-playwright}" \
    bash -c "
      set -euo pipefail
      [[ \"\$(id -u)\" -ne 0 ]] || { echo 'FATAL: pytest would run as root'; exit 16; }
      cd '$REPO_ROOT'
      '$PYTHON_BIN' -m pytest tests/ -v
      echo 'Running import-linter (lint-imports)'
      '$LINT_IMPORTS_BIN'
    "
