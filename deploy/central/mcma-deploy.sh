#!/usr/bin/env bash
# MCMA central server -- deployment driver (Ubuntu host).
#
# One fixed identity: Compose project, container and image repository are all
# "mcma-central". This script acts on nothing else. It never restarts the
# Docker daemon, never prunes anything, never uses `down -v` or
# `--remove-orphans`, never removes/stops/kills a container it did not create,
# and never mounts the Docker socket.
#
# usage: mcma-deploy.sh --env-file FILE <command> [args]
#
#  first-time setup (sudo)
#   init                      create the data root (refuses unmarked non-empty dirs)
#   gen-keys                  create the two distinct 32-byte keys
#   install-tls CERT KEY      validate + install a provided certificate/key
#   gen-dev-cert              self-signed cert, DEVELOPMENT VM ONLY
#   show-cert                 print the PUBLIC certificate (stdout) + fingerprint (stderr)
#   check                     preflight: env, files, permissions, port, subnets, routes
#
#  build on the VM only (MCMA_ALLOW_BUILD=true)
#   build [TAG]               build, verify (dpkg audit + Chromium navigation), record tag
#   export-image TAG [DIR]    docker save + gzip + SHA-256 + image id
#
#  deploy (both hosts)
#   import-image ARCHIVE      verify SHA-256, docker load, verify image id
#   set-tag TAG               point the env file at a loaded image tag
#   up                        preflight, start (never builds), wait until healthy
#   health                    wait until the exact container reports healthy
#   status | logs [N] | down | images
#   rollback TAG              transactional: restores the previous tag on failure
#
#  data
#   backup [--include-keys] | restore ARCHIVE [--with-config] [--with-keys]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PROJECT="mcma-central"
IMAGE="mcma-central"

if [[ "${1:-}" != "--env-file" || -z "${2:-}" ]]; then
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
  exit 2
fi
ENV_FILE="$(readlink -f "$2")"; shift 2
[[ -f "$ENV_FILE" ]] || { echo "env file not found: $ENV_FILE" >&2; exit 2; }
CMD="${1:-}"; [[ $# -gt 0 ]] && shift

tool() { python3 "$HERE/deploytool.py" --env-file "$ENV_FILE" "$@"; }
get() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//' | tr -d "\"'"; }
[[ "$(get MCMA_PROJECT)" == "$PROJECT" && "$(get MCMA_IMAGE)" == "$IMAGE" ]] \
  || { echo "MCMA_PROJECT and MCMA_IMAGE must both be exactly mcma-central" >&2; exit 2; }

compose() { docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$HERE/compose.yaml" "$@"; }

case "$CMD" in
  init|gen-keys|gen-dev-cert|show-cert|check|up|backup)  tool "$CMD" "$@" ;;
  install-tls)  [[ $# -eq 2 ]] || { echo "usage: install-tls CERT KEY" >&2; exit 2; }
                tool install-tls --cert "$1" --key "$2" ;;
  build)
    [[ "$(get MCMA_ALLOW_BUILD)" == "true" ]] \
      || { echo "build is disabled here (MCMA_ALLOW_BUILD is not true). Build on the VM and use import-image." >&2; exit 1; }
    TAG="${1:-$(date -u +%Y%m%d-%H%M%S)-$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo nogit)}"
    tool check --no-host
    docker build -f "$HERE/Dockerfile" -t "$IMAGE:$TAG" \
      --build-arg "MCMA_UID=$(get MCMA_UID)" --build-arg "MCMA_GID=$(get MCMA_GID)" "$REPO"
    tool verify-image "$TAG"          # a tag is recorded only for an image that passed
    tool set-tag "$TAG"
    echo "built and verified $IMAGE:$TAG (recorded in $ENV_FILE)"
    echo "next: up   |   to ship: export-image $TAG" ;;
  export-image) [[ $# -ge 1 ]] || { echo "usage: export-image TAG [DIR]" >&2; exit 2; }
                tool export-image "$1" --out-dir "${2:-.}" ;;
  import-image) [[ $# -eq 1 ]] || { echo "usage: import-image ARCHIVE" >&2; exit 2; }
                tool import-image "$1" ;;
  set-tag)      [[ $# -eq 1 ]] || { echo "usage: set-tag TAG" >&2; exit 2; }
                tool set-tag "$1" ;;
  health)       tool wait-healthy ;;
  status)       compose ps ;;
  logs)         compose logs --no-color --tail "${1:-200}" ${LOGS_FOLLOW:+--follow} ;;
  down)         compose down ;;
  restore)      [[ $# -ge 1 ]] || { echo "usage: restore ARCHIVE [--with-config] [--with-keys]" >&2; exit 2; }
                tool restore "$@" ;;
  images)       docker images "$IMAGE" --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}\t{{.Size}}' ;;
  rollback)     [[ $# -eq 1 ]] || { echo "usage: rollback TAG" >&2; exit 2; }
                tool rollback "$1" ;;
  *) echo "unknown command: $CMD" >&2; exit 2 ;;
esac
