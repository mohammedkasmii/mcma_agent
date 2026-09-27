#!/usr/bin/env python3
"""MCMA central server -- deployment helper (Python standard library only,
Python >= 3.10, so it runs on the stock Ubuntu 24.04/26.04 host).

Called by mcma-deploy.sh; also importable by tests. The identity of this
single deployment is FIXED: Compose project, container and image repository
are all `mcma-central` (the env file must agree). Docker is only ever asked
about that identity, and every inspection FAILS CLOSED: if Docker cannot
give a positive answer (missing CLI, permission error, timeout, daemon down,
malformed output) the command aborts rather than assuming "nothing there".
Nothing here restarts the Docker daemon or touches any other project,
container, network, volume or image.

Subcommands (all take --env-file):
  init            create the MCMA_DATA_ROOT layout (marker-protected)
  gen-keys        create the two DISTINCT 32-byte keys (never overwrites)
  install-tls     validate and install a provided certificate + private key
  gen-dev-cert    self-signed certificate for the DEVELOPMENT VM only
  show-cert       print the PUBLIC server certificate + SHA-256 fingerprint
  check           validate env, files, permissions, port, subnet, routes
  up              preflight, compose up (no build), wait until healthy
  wait-healthy    wait for the exact MCMA container to report healthy
  rollback TAG    transactional switch to a previously built tag
  verify-image    dpkg audit + real Chromium navigation in the built image
  export-image    docker save + gzip + SHA-256 + image id
  import-image    verify SHA-256, docker load, verify image id
  backup / restore  SQLite snapshot + vault (+ config, optional keys)
  set-tag         record MCMA_IMAGE_TAG in the env file

No secret is ever printed. Key bytes are generated from os.urandom and
written straight to a 0600 file.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import ipaddress
import json
import os
import posixpath
import re
import shutil
import socket
import stat
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

KEY_LENGTH = 32
KEY_FILES = ("session-vault.key", "job-input.key")
TLS_CERT, TLS_KEY = "server.crt", "server.key"

# The ONE identity of this deployment.
PROJECT = "mcma-central"
CONTAINER_NAME = "mcma-central"
IMAGE_REPO = "mcma-central"
NETWORK_NAME = "mcma-central-net"
COMPOSE_FILE = Path(__file__).resolve().parent / "compose.yaml"
DOCKER_TIMEOUT = 30

MARKER = ".mcma-data-root"
MARKER_TEXT = "mcma-central data root v1\n"

REQUIRED_ENV = (
    "MCMA_PROJECT", "MCMA_DATA_ROOT", "MCMA_BIND_ADDRESS", "MCMA_HTTPS_PORT",
    "MCMA_NET_SUBNET", "MCMA_CONTAINER_IP", "MCMA_TLS_SERVER_NAME",
    "MCMA_UID", "MCMA_GID", "MCMA_IMAGE", "MCMA_IMAGE_TAG",
)
_WILDCARDS = {"", "0.0.0.0", "::", "[::]", "*"}
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Paths MCMA_DATA_ROOT may never be, or live inside.
PROTECTED_EXACT = frozenset({
    "/", "/data", "/home", "/root", "/opt", "/srv", "/var", "/var/lib", "/tmp", "/mnt", "/media",
    "/usr", "/usr/local", "/etc", "/boot", "/bin", "/sbin", "/lib", "/lib64", "/dev", "/proc",
    "/sys", "/run", "/snap",
})
PROTECTED_TREES = (
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/boot", "/dev", "/proc",
    "/sys", "/run", "/snap", "/var/lib/docker", "/var/run",
)

CONFIG_TEMPLATE = """\
# MCMA central server -- optional tuning (mounted read-only at /etc/mcma/config).
# Required settings (paths, TLS, keys, bind address) come from the container
# environment; the loader refuses unknown keys and unsafe values. Environment
# variables override this file. NO secrets belong here.
#
# notification_poll_interval_seconds = 300
# notification_category_codes = []
# subnet_allowlist = ["192.168.11.0/24"]   # defence in depth only
"""

# Real Chromium navigation, run inside the image under the production flags.
NAVIGATION_SNIPPET = r"""
import asyncio, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from playwright.async_api import async_playwright

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><head><title>mcma-nav-ok</title></head><body><h1 id=x>42</h1></body></html>"
        self.send_response(200); self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

server = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=server.serve_forever, daemon=True).start()

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("http://127.0.0.1:%d/" % server.server_address[1])
        assert await page.title() == "mcma-nav-ok"
        assert await page.inner_text("#x") == "42"
        assert browser.is_connected()
        await browser.close()
    print("NAVIGATION_OK")

asyncio.run(main())
"""


class DeployError(Exception):
    """One or more problems, each a fixed sentence (never secret material)."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


# --------------------------------------------------------------------- #
# Docker (fail closed)
# --------------------------------------------------------------------- #


def _run(argv: list, timeout: float, what: str) -> str:
    """Runs a command and returns stdout, or raises DeployError. There is no
    'best effort': every failure class aborts the calling command."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise DeployError(f"{argv[0]} is not installed or not on PATH ({what})") from None
    except PermissionError:
        raise DeployError(f"permission denied running {argv[0]} ({what}); run with sudo or as a docker-group user") from None
    except subprocess.TimeoutExpired:
        raise DeployError(f"{argv[0]} did not answer within {timeout:.0f}s ({what})") from None
    except (OSError, subprocess.SubprocessError):
        raise DeployError(f"{argv[0]} could not be run ({what})") from None
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-1:] or [""]
        raise DeployError(f"{argv[0]} failed ({what}, exit {result.returncode}): {detail[0][:200]}")
    return result.stdout


def _docker(*args: str, timeout: float = DOCKER_TIMEOUT) -> str:
    return _run(["docker", *args], timeout, f"docker {args[0]}")


def _compose(env_file: Path, *args: str, timeout: float = 600) -> str:
    return _run(
        ["docker", "compose", "--project-name", PROJECT, "--env-file", str(env_file), "-f", str(COMPOSE_FILE), *args],
        timeout, "docker compose",
    )


def docker_networks() -> list:
    """[(name, id, IPv4 network)] for every Docker network. Any doubt aborts."""
    ids = _docker("network", "ls", "-q").split()
    if not ids:
        raise DeployError("docker reported no networks; refusing to assume the subnet is free")
    raw = _docker("network", "inspect", *ids)
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError
        found = []
        for net in data:
            for cfg in (net.get("IPAM") or {}).get("Config") or []:
                subnet = cfg.get("Subnet")
                if subnet:
                    parsed = ipaddress.ip_network(subnet, strict=False)
                    if parsed.version == 4:
                        found.append((str(net["Name"]), str(net.get("Id", "")), parsed))
        return found
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DeployError("docker network inspect returned unusable output; refusing to continue") from None


def container_state() -> str:
    """'running' | 'stopped' | 'absent' for the EXACT mcma-central container,
    or DeployError when that cannot be established positively."""
    out = _docker("ps", "-a", "--filter", f"name=^{CONTAINER_NAME}$", "--format", "{{.Names}}\t{{.State}}")
    rows = [line.split("\t") for line in out.splitlines() if line.strip()]
    if not rows:
        return "absent"
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][0] != CONTAINER_NAME:
        raise DeployError("docker ps returned an unexpected answer for the MCMA container")
    state = rows[0][1].strip().lower()
    if state in ("exited", "created", "dead"):
        return "stopped"
    if state in ("running", "restarting", "paused", "removing"):
        return "running"
    raise DeployError(f"unrecognised state {state!r} for the MCMA container")


def require_stopped() -> None:
    if container_state() == "running":
        raise DeployError("the MCMA container is running; stop it (mcma-deploy.sh down) first")


def read_proc_routes() -> str:
    try:
        return Path("/proc/net/route").read_text(encoding="utf-8")
    except OSError:
        raise DeployError("cannot read the host routing table (/proc/net/route); refusing to continue") from None


def host_routes(source: Callable[[], str] = read_proc_routes) -> list:
    """[(iface, IPv4 network)] for every non-default IPv4 route."""
    lines = source().splitlines()
    if not lines or not lines[0].startswith("Iface"):
        raise DeployError("unrecognised routing table format; refusing to continue")
    routes = []
    for line in lines[1:]:
        fields = line.split()
        if not fields:
            continue
        try:
            iface = fields[0]
            dest = ipaddress.IPv4Address(int.from_bytes(bytes.fromhex(fields[1]), "little"))
            mask = int.from_bytes(bytes.fromhex(fields[7]), "little")
            if mask == 0:
                continue   # the default route overlaps everything and means nothing here
            routes.append((iface, ipaddress.ip_network(f"{dest}/{bin(mask).count('1')}", strict=False)))
        except (IndexError, ValueError):
            raise DeployError("malformed routing table entry; refusing to continue") from None
    return routes


def subnet_conflicts(env: dict, networks: list, routes: list) -> list:
    """Every overlap of MCMA_NET_SUBNET with an existing Docker network or an
    IPv4 host route. MCMA's OWN network and its bridge route are not conflicts."""
    wanted = ipaddress.ip_network(env["MCMA_NET_SUBNET"])
    problems = []
    own_bridge = None
    for name, net_id, net in networks:
        if name == NETWORK_NAME:
            own_bridge = "br-" + net_id[:12]
            continue
        if wanted.overlaps(net):
            problems.append(f"MCMA_NET_SUBNET {wanted} overlaps Docker network '{name}' ({net})")
    for iface, net in routes:
        if iface == own_bridge:
            continue
        if wanted.overlaps(net):
            problems.append(f"MCMA_NET_SUBNET {wanted} overlaps host route {net} on {iface}")
    return problems


# --------------------------------------------------------------------- #
# env file
# --------------------------------------------------------------------- #


def parse_env(path: Path) -> dict:
    values: dict = {}
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise DeployError(f"{path}:{number}: expected KEY=VALUE")
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.sub(r"\s+#.*$", "", value)          # inline comment on an unquoted value
        values[key.strip()] = value
    return values


def data_root_problems(value: str) -> list:
    """Pure check of the MCMA_DATA_ROOT string against broad/protected paths."""
    if not PurePosixPath(value).is_absolute():
        return ["MCMA_DATA_ROOT must be an absolute path"]
    normalised = posixpath.normpath(value)
    if normalised != value.rstrip("/") and value != "/":
        return ["MCMA_DATA_ROOT must be a clean path (no '..', '.', '//' or trailing components)"]
    if normalised in PROTECTED_EXACT:
        return [f"MCMA_DATA_ROOT {normalised} is the root or a broad system/shared directory; use a dedicated directory such as /data/mcma"]
    for tree in PROTECTED_TREES:
        if normalised == tree or normalised.startswith(tree + "/"):
            return [f"MCMA_DATA_ROOT must not be inside the protected system path {tree}"]
    return []


def validate_env(env: dict) -> list:
    """Pure validation of the env values. Returns a list of problems."""
    problems = []
    for key in REQUIRED_ENV:
        if not env.get(key):
            problems.append(f"{key} is required")
    if problems:
        return problems

    if env["MCMA_PROJECT"] != PROJECT:
        problems.append(f"MCMA_PROJECT must be exactly {PROJECT} (single fixed deployment identity)")
    if env["MCMA_IMAGE"] != IMAGE_REPO:
        problems.append(f"MCMA_IMAGE must be exactly {IMAGE_REPO}; another repository is never tagged or run")
    problems += data_root_problems(env["MCMA_DATA_ROOT"])
    if env.get("MCMA_ALLOW_BUILD", "false") not in ("true", "false"):
        problems.append("MCMA_ALLOW_BUILD must be true or false")

    bind = env["MCMA_BIND_ADDRESS"].strip()
    try:
        bind_ip = ipaddress.ip_address(bind)
        if bind_ip.is_unspecified or bind in _WILDCARDS:
            problems.append("MCMA_BIND_ADDRESS must be a specific address, never a wildcard bind")
    except ValueError:
        problems.append("MCMA_BIND_ADDRESS must be a specific IP address (placeholders must be replaced)")

    try:
        port = int(env["MCMA_HTTPS_PORT"])
        if not 1024 <= port <= 65535:
            raise ValueError
    except ValueError:
        problems.append("MCMA_HTTPS_PORT must be an integer between 1024 and 65535")

    try:
        subnet = ipaddress.ip_network(env["MCMA_NET_SUBNET"], strict=True)
        if subnet.version != 4 or subnet.prefixlen > 29:
            problems.append("MCMA_NET_SUBNET must be an IPv4 subnet of at least 8 addresses (/29 or larger)")
        try:
            container_ip = ipaddress.ip_address(env["MCMA_CONTAINER_IP"])
            first_hosts = list(subnet.hosts())[:1]  # .1 is the bridge gateway
            if container_ip not in subnet:
                problems.append("MCMA_CONTAINER_IP must lie inside MCMA_NET_SUBNET")
            elif container_ip in (subnet.network_address, subnet.broadcast_address) or (
                first_hosts and container_ip == first_hosts[0]
            ):
                problems.append("MCMA_CONTAINER_IP must not be the network, broadcast or gateway address")
        except ValueError:
            problems.append("MCMA_CONTAINER_IP must be an IP address")
    except ValueError:
        problems.append("MCMA_NET_SUBNET must be a valid network in CIDR form")

    for key in ("MCMA_UID", "MCMA_GID"):
        if not env[key].isdigit() or int(env[key]) < 1000:
            problems.append(f"{key} must be a numeric id >= 1000 (never root or a system account)")

    if not _TAG_RE.match(env["MCMA_IMAGE_TAG"]):
        problems.append("MCMA_IMAGE_TAG must be a plain tag (letters, digits, '_', '.', '-')")
    if "X.X" in env["MCMA_TLS_SERVER_NAME"] or not env["MCMA_TLS_SERVER_NAME"].strip():
        problems.append("MCMA_TLS_SERVER_NAME must be the real name/IP in the certificate")
    return problems


# --------------------------------------------------------------------- #
# layout and the ownership marker
# --------------------------------------------------------------------- #

LAYOUT = {
    "db": 0o700,
    "vault": 0o700,
    "keys": 0o700,
    "tls": 0o700,
    "config": 0o750,
    "backups": 0o700,   # root-owned: backups hold the database
}


def _ids(env: dict) -> tuple:
    return int(env["MCMA_UID"]), int(env["MCMA_GID"])


def data_root(env: dict) -> Path:
    return Path(env["MCMA_DATA_ROOT"])


def _chown(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        raise DeployError(
            f"cannot assign ownership of {path} to {uid}:{gid}; run as root (sudo)"
        ) from None


def marker_problem(root: Path) -> Optional[str]:
    """None when `root` is a real directory carrying the MCMA marker."""
    if root.is_symlink():
        return f"{root} is a symlink; MCMA_DATA_ROOT must be a real directory"
    if not root.is_dir():
        return f"MCMA_DATA_ROOT does not exist: {root} (run init)"
    marker = root / MARKER
    try:
        if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_TEXT:
            return f"{root} does not carry the MCMA ownership marker ({MARKER}); it is not an MCMA data root"
    except OSError:
        return f"the MCMA ownership marker in {root} cannot be read"
    return None


def require_owned_root(env: dict) -> Path:
    root = data_root(env)
    problem = marker_problem(root)
    if problem:
        raise DeployError(problem)
    return root


def cmd_init(env: dict) -> list:
    problems = validate_env(env)
    if problems:
        raise DeployError(problems)
    uid, gid = _ids(env)
    root = data_root(env)
    actions = []

    if root.is_symlink():
        raise DeployError(f"{root} is a symlink; MCMA_DATA_ROOT must be a real directory")
    real = os.path.realpath(root)
    if real != str(root) and data_root_problems(real):
        raise DeployError(f"MCMA_DATA_ROOT resolves to a protected path: {real}")

    if not root.exists():
        root.mkdir(parents=True)
        os.chmod(root, 0o755)                     # only a directory WE created is chmod-ed
        _write_marker(root)
        actions.append(f"created {root} and its ownership marker")
    elif not root.is_dir():
        raise DeployError(f"{root} exists and is not a directory")
    elif marker_problem(root) is None:
        actions.append(f"ok      {root} (MCMA marker present)")
    elif any(root.iterdir()):
        raise DeployError(
            f"{root} already exists, is not empty and has no MCMA marker: refusing to touch a "
            "directory that may belong to another application. Choose an empty/new directory."
        )
    else:
        _write_marker(root)                       # adopt an EMPTY directory; permissions untouched
        actions.append(f"adopted empty {root}; wrote its ownership marker")

    for name, mode in LAYOUT.items():
        path = root / name
        if path.is_symlink():
            raise DeployError(f"{path} is a symlink; refusing")
        created = not path.exists()
        path.mkdir(exist_ok=True)
        os.chmod(path, mode)
        if name != "backups":
            _chown(path, uid, gid)
        actions.append(f"{'created' if created else 'ok     '} {path} mode {mode:04o}")
    config_file = root / "config" / "mcma.toml"
    if not config_file.exists():
        config_file.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        os.chmod(config_file, 0o640)
        _chown(config_file, uid, gid)
        actions.append(f"created {config_file}")
    return actions


def _write_marker(root: Path) -> None:
    fd = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, MARKER_TEXT.encode("utf-8"))
    finally:
        os.close(fd)


# --------------------------------------------------------------------- #
# keys and TLS
# --------------------------------------------------------------------- #


def cmd_gen_keys(env: dict) -> list:
    uid, gid = _ids(env)
    keys_dir = require_owned_root(env) / "keys"
    if not keys_dir.is_dir():
        raise DeployError(f"{keys_dir} does not exist; run init first")
    existing = [name for name in KEY_FILES if (keys_dir / name).exists()]
    if existing:
        raise DeployError(
            "refusing to overwrite existing key file(s): " + ", ".join(existing)
            + " -- replacing a key makes existing sessions/job inputs unreadable"
        )
    created = []
    material = []
    for name in KEY_FILES:
        key = os.urandom(KEY_LENGTH)
        material.append(key)
        fd = os.open(keys_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        _chown(keys_dir / name, uid, gid)
        created.append(name)
    if material[0] == material[1]:  # 2^-256; checked anyway
        for name in KEY_FILES:
            (keys_dir / name).unlink()
        raise DeployError("generated keys were identical; nothing written, retry")
    return [f"created {keys_dir / name} (32 random bytes, mode 0600)" for name in created]


def _openssl(*args: str, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["openssl", *args], input=stdin, capture_output=True, timeout=30)
    except FileNotFoundError:
        raise DeployError("the openssl command is required on the host") from None


def certificate_problems(cert: Path, key: Path, server_name: Optional[str] = None) -> list:
    problems = []
    if not cert.is_file():
        return [f"certificate not found: {cert}"]
    if not key.is_file():
        return [f"private key not found: {key}"]
    pub_cert = _openssl("x509", "-in", str(cert), "-noout", "-pubkey")
    pub_key = _openssl("pkey", "-in", str(key), "-pubout")
    if pub_cert.returncode != 0:
        return ["certificate is not a valid PEM X.509 certificate"]
    if pub_key.returncode != 0:
        return ["private key is not a valid PEM key (or is passphrase-protected)"]
    if pub_cert.stdout.strip() != pub_key.stdout.strip():
        problems.append("certificate and private key do not match")
    if _openssl("x509", "-in", str(cert), "-noout", "-checkend", "0").returncode != 0:
        problems.append("certificate has expired")
    if server_name:
        san = _openssl("x509", "-in", str(cert), "-noout", "-ext", "subjectAltName")
        text = san.stdout.decode("utf-8", "replace") if san.returncode == 0 else ""
        if f"DNS:{server_name}" not in text and f"IP Address:{server_name}" not in text:
            problems.append(
                f"certificate subjectAltName does not list MCMA_TLS_SERVER_NAME={server_name} "
                "(browsers and the healthcheck would reject it)"
            )
    return problems


def cmd_install_tls(env: dict, cert_src: Path, key_src: Path) -> list:
    uid, gid = _ids(env)
    tls_dir = require_owned_root(env) / "tls"
    if not tls_dir.is_dir():
        raise DeployError(f"{tls_dir} does not exist; run init first")
    problems = certificate_problems(Path(cert_src), Path(key_src), env.get("MCMA_TLS_SERVER_NAME"))
    if problems:
        raise DeployError(problems)
    for src, name, mode in ((cert_src, TLS_CERT, 0o644), (key_src, TLS_KEY, 0o600)):
        tmp = tls_dir / f".{name}.new"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            os.write(fd, Path(src).read_bytes())
        finally:
            os.close(fd)
        os.chmod(tmp, mode)
        _chown(tmp, uid, gid)
        os.replace(tmp, tls_dir / name)
    return [f"installed {tls_dir / TLS_CERT} (0644) and {tls_dir / TLS_KEY} (0600)"]


def cmd_gen_dev_cert(env: dict) -> list:
    """DEVELOPMENT ONLY. Production uses a certificate issued by the agency's
    internal CA (deploy/tls/README.md)."""
    name = env["MCMA_TLS_SERVER_NAME"]
    try:
        ipaddress.ip_address(name)
        san = f"IP:{name}"
    except ValueError:
        san = f"DNS:{name}"
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = Path(tmp) / "c.crt", Path(tmp) / "k.key"
        result = _openssl(
            "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "365",
            "-subj", f"/CN={name}", "-addext", f"subjectAltName={san}",
        )
        if result.returncode != 0:
            raise DeployError("openssl could not generate the development certificate")
        os.chmod(key, 0o600)
        return cmd_install_tls(env, cert, key)


def cmd_show_cert(env: dict) -> tuple:
    """The PUBLIC certificate (PEM) and its SHA-256 fingerprint. The private
    key is never read. The tls/ directory is owner-only, so this runs as root."""
    cert = require_owned_root(env) / "tls" / TLS_CERT
    if not cert.is_file():
        raise DeployError(f"{cert} does not exist; install a certificate first")
    pem = cert.read_text(encoding="utf-8")
    fingerprint = _openssl("x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256")
    if fingerprint.returncode != 0:
        raise DeployError("the installed certificate is not a valid X.509 certificate")
    return pem, fingerprint.stdout.decode("utf-8", "replace").strip()


# --------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------- #


def _mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def filesystem_problems(env: dict) -> list:
    """Existence, marker, ownership, permissions, key sanity. Ownership/mode
    checks are POSIX only."""
    problems = []
    uid, gid = _ids(env)
    root = data_root(env)
    posix = os.name == "posix"

    root_problem = marker_problem(root)
    if root_problem:
        return [root_problem]
    for name, mode in LAYOUT.items():
        path = root / name
        if path.is_symlink():
            problems.append(f"{path} must not be a symlink")
        elif not path.is_dir():
            problems.append(f"{path} is missing (run init)")
        elif posix:
            if name != "backups" and os.stat(path).st_uid != uid:
                problems.append(f"{path} must be owned by uid {uid}")
            limit = 0o022 if name == "config" else 0o077
            if _mode(path) & limit:
                problems.append(f"{path} has unsafe permissions {_mode(path):04o} (need {mode:04o} or stricter)")

    keys_dir = root / "keys"
    key_bytes = {}
    for name in KEY_FILES:
        path = keys_dir / name
        if not path.is_file():
            problems.append(f"key file missing: {path} (run gen-keys)")
            continue
        data = path.read_bytes()
        if len(data) != KEY_LENGTH:
            problems.append(f"{path} must be exactly {KEY_LENGTH} raw bytes")
        key_bytes[name] = data
        if posix and (_mode(path) & 0o077 or os.stat(path).st_uid != uid):
            problems.append(f"{path} must be mode 0600 and owned by uid {uid}")
    if len(key_bytes) == 2:
        if key_bytes[KEY_FILES[0]] == key_bytes[KEY_FILES[1]]:
            problems.append("the two key files contain identical key material")
        if os.path.samefile(keys_dir / KEY_FILES[0], keys_dir / KEY_FILES[1]):
            problems.append("the two key files are the same file")

    cert, key = root / "tls" / TLS_CERT, root / "tls" / TLS_KEY
    if key.is_file() and posix and (_mode(key) & 0o077 or os.stat(key).st_uid != uid):
        problems.append(f"{key} must be mode 0600 and owned by uid {uid}")
    problems += certificate_problems(cert, key, env.get("MCMA_TLS_SERVER_NAME"))

    if not (root / "config" / "mcma.toml").is_file():
        problems.append("config/mcma.toml is missing (run init)")
    return problems


def port_in_use(address: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((address, port)) == 0


def host_problems(env: dict) -> list:
    """Docker networks + IPv4 routes + port. Every inspection failure raises
    DeployError (fail closed) instead of being treated as 'no conflict'."""
    problems = subnet_conflicts(env, docker_networks(), host_routes())
    if container_state() != "running" and port_in_use(env["MCMA_BIND_ADDRESS"], int(env["MCMA_HTTPS_PORT"])):
        problems.append(
            f"{env['MCMA_BIND_ADDRESS']}:{env['MCMA_HTTPS_PORT']} is already in use by another service"
        )
    return problems


def cmd_check(env: dict, *, host: bool = True) -> list:
    problems = validate_env(env)
    if problems:
        raise DeployError(problems)
    problems = filesystem_problems(env)
    if host:
        problems += host_problems(env)
    if problems:
        raise DeployError(problems)
    return ["all preflight checks passed"]


# --------------------------------------------------------------------- #
# up / health / rollback
# --------------------------------------------------------------------- #


def image_ref(tag: str) -> str:
    return f"{IMAGE_REPO}:{tag}"


def wait_healthy(
    tag: str, *, timeout: float = 180.0, interval: float = 3.0,
    sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
) -> list:
    """Success only when the EXACT container (name, Compose project label and
    image reference) reports healthy."""
    deadline = clock() + timeout
    while True:
        raw = _docker("inspect", CONTAINER_NAME)
        try:
            info = json.loads(raw)[0]
            labels = info["Config"].get("Labels") or {}
            image = info["Config"]["Image"]
            status = (info["State"].get("Health") or {}).get("Status", "none")
            running = info["State"]["Running"]
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise DeployError("docker inspect returned unusable output for the MCMA container") from None
        if labels.get("com.docker.compose.project") != PROJECT:
            raise DeployError("the container named mcma-central is not part of the mcma-central Compose project")
        if image != image_ref(tag):
            raise DeployError(f"the running container uses {image}, expected {image_ref(tag)}")
        if not running:
            raise DeployError("the MCMA container is not running")
        if status == "healthy":
            return [f"healthy ({image_ref(tag)})"]
        if status == "unhealthy":
            raise DeployError("the MCMA container reports unhealthy")
        if clock() >= deadline:
            raise DeployError(f"the MCMA container did not become healthy within {timeout:.0f}s (last: {status})")
        sleep(interval)


def _deploy(env_file: Path, tag: str) -> list:
    _docker("image", "inspect", image_ref(tag))
    _compose(env_file, "up", "-d", "--no-build")
    return wait_healthy(tag)


def cmd_up(env_file: Path) -> list:
    env = parse_env(env_file)
    cmd_check(env)
    lines = _deploy(env_file, env["MCMA_IMAGE_TAG"])
    return lines + ["started and healthy"]


def cmd_rollback(env_file: Path, tag: str) -> list:
    """Switch to a previously built tag. The env tag is restored if preflight,
    Compose or the health wait fails; success is reported only after health
    passes. Data is never rolled back."""
    if not _TAG_RE.match(tag):
        raise DeployError("invalid image tag")
    env = parse_env(env_file)
    previous = env["MCMA_IMAGE_TAG"]
    if tag == previous:
        raise DeployError(f"already on tag {tag}")
    _docker("image", "inspect", image_ref(tag))          # must exist locally
    cmd_set_tag(env_file, tag)
    compose_ran = False
    try:
        cmd_check(parse_env(env_file))
        compose_ran = True
        _compose(env_file, "up", "-d", "--no-build")
        wait_healthy(tag)
    except DeployError as failure:
        notes = [f"rollback to {tag} FAILED: {failure}"]
        try:
            cmd_set_tag(env_file, previous)
        except DeployError as restore_failure:
            # Do NOT claim a restore that did not happen, and do not run Compose:
            # it would read the env file, which still names the failed tag.
            notes += [
                f"could NOT restore the env tag to {previous}: {restore_failure}",
                f"the env file may still say MCMA_IMAGE_TAG={tag}; fix it with: set-tag {previous}",
                "data was not touched",
            ]
            raise DeployError(notes) from None
        notes.append(f"env tag restored to {previous}")
        if compose_ran:
            try:
                _compose(env_file, "up", "-d", "--no-build")
                wait_healthy(previous)
                notes.append(f"previous image {previous} is running and healthy again")
            except DeployError as again:
                notes.append(f"could not confirm the previous image {previous} is healthy: {again}")
        notes.append("data was not touched")
        raise DeployError(notes) from None
    return [f"rolled back {previous} -> {tag}; container healthy", "data was NOT rolled back (use restore for that)"]


# --------------------------------------------------------------------- #
# image build verification and immutable delivery
# --------------------------------------------------------------------- #

_HARDENED_RUN = (
    "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
    "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m", "--shm-size", "512m",
    "--user", "10001:10001", "--network", "none", "--memory", "2g", "--pids-limit", "512",
)


def cmd_verify_image(tag: str) -> list:
    ref = image_ref(tag)
    _docker("image", "inspect", ref)
    audit = _docker("run", "--rm", "--user", "0", "--network", "none", "--entrypoint", "sh", ref,
                    "-c", "dpkg --audit; echo AUDIT_DONE")
    if audit.strip() != "AUDIT_DONE":
        raise DeployError("dpkg --audit reports problems in the image: " + " ".join(audit.split())[:300])
    out = _docker("run", "--rm", *_HARDENED_RUN, "--entrypoint", "python", ref, "-c", NAVIGATION_SNIPPET, timeout=240)
    if "NAVIGATION_OK" not in out:
        raise DeployError("the Chromium navigation test did not complete")
    return [f"{ref}: dpkg --audit clean; real Chromium navigation OK (read-only, no capabilities, no network)"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _image_id(ref: str) -> str:
    return _docker("image", "inspect", "--format", "{{.Id}}", ref).strip()


def cmd_export_image(tag: str, out_dir: Path) -> list:
    ref = image_ref(tag)
    image_id = _image_id(ref)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{IMAGE_REPO}-{tag}.tar.gz"
    if archive.exists():
        raise DeployError(f"{archive} already exists; images are immutable, choose another directory")
    try:
        proc = subprocess.Popen(["docker", "save", ref], stdout=subprocess.PIPE)
    except (FileNotFoundError, PermissionError, OSError):
        raise DeployError("docker could not be run to save the image") from None
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(proc.stdout, gz, 1 << 20)
        if proc.wait() != 0:
            raise DeployError("docker save failed")
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    # newline="\n": the sidecars must be byte-identical on every OS (sha256sum -c).
    for suffix, text in ((".sha256", f"{_sha256(archive)}  {archive.name}\n"), (".image-id", f"{image_id}\n{ref}\n")):
        with open(out_dir / f"{archive.name}{suffix}", "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    return [f"archive   {archive}", f"sha256    {archive.name}.sha256", f"image id  {image_id}  ({ref})",
            "copy all three files to the target; verify + load with: import-image"]


def _read_checksum(archive: Path) -> str:
    sha_file = Path(f"{archive}.sha256")
    try:
        digest, _, name = sha_file.read_text(encoding="utf-8").strip().partition("  ")
    except OSError:
        raise DeployError(f"{sha_file} is missing; refusing to load an unverified archive") from None
    if not _HEX64.match(digest) or name != archive.name:
        raise DeployError(f"{sha_file} is malformed or names a different file")
    return digest


def _archive_repo_tags(archive: Path) -> list:
    """Image names recorded INSIDE the archive, read before anything is loaded."""
    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
        if "manifest.json" in names:
            manifest = json.load(tar.extractfile("manifest.json"))
            tags = [t for entry in manifest for t in (entry.get("RepoTags") or [])]
        elif "index.json" in names:
            index = json.load(tar.extractfile("index.json"))
            tags = [
                (m.get("annotations") or {}).get("io.containerd.image.name")
                or (m.get("annotations") or {}).get("org.opencontainers.image.ref.name") or ""
                for m in index.get("manifests", [])
            ]
        else:
            raise DeployError("the archive is not a docker image archive")
    return [t.removeprefix("docker.io/library/") for t in tags if t]


def cmd_import_image(archive: Path) -> list:
    archive = Path(archive)
    if _sha256(archive) != _read_checksum(archive):
        raise DeployError("SHA-256 mismatch: the archive is corrupt or was altered; nothing was loaded")
    try:
        image_id, ref = Path(f"{archive}.image-id").read_text(encoding="utf-8").split()[:2]
    except (OSError, ValueError):
        raise DeployError(f"{archive}.image-id is missing or malformed; refusing to load") from None
    if not re.match(rf"^{re.escape(IMAGE_REPO)}:[A-Za-z0-9][A-Za-z0-9_.-]*$", ref) or not image_id.startswith("sha256:"):
        raise DeployError("the .image-id file does not describe an mcma-central image")
    try:
        inside = _archive_repo_tags(archive)
    except (OSError, tarfile.TarError, ValueError):
        raise DeployError("the archive cannot be read as a docker image archive") from None
    if inside != [ref]:
        raise DeployError(f"the archive contains {inside or 'no tagged image'}, expected exactly [{ref!r}]; nothing was loaded")

    existing = _docker("image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}", IMAGE_REPO)
    for line in existing.splitlines():
        name, _, existing_id = line.partition("\t")
        if name == ref and existing_id.strip() != image_id:
            raise DeployError(f"{ref} already exists locally with a different image id; tags are immutable")

    try:
        proc = subprocess.Popen(["docker", "load"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (FileNotFoundError, PermissionError, OSError):
        raise DeployError("docker could not be run to load the image") from None
    with gzip.open(archive, "rb") as source:
        try:
            shutil.copyfileobj(source, proc.stdin, 1 << 20)
        except BrokenPipeError:
            pass
    proc.stdin.close()
    proc.stdout.read()
    if proc.wait() != 0:
        raise DeployError("docker load failed")
    loaded = _image_id(ref)
    if loaded != image_id:
        raise DeployError(f"loaded image id {loaded} differs from the recorded {image_id}; do not run it")
    return [f"loaded {ref}", f"image id verified: {loaded}"]


# --------------------------------------------------------------------- #
# backup / restore
# --------------------------------------------------------------------- #

_BACKUP_TREES = ("db", "vault", "config", "keys")


def _fix_db_ownership(db_dir: Path, uid: int, gid: int) -> None:
    """Opening a WAL database as root can leave root-owned -wal/-shm files the
    service user could not use. Hand every file in the db dir back."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    for entry in db_dir.iterdir():
        if entry.is_file():
            os.chown(entry, uid, gid)


def cmd_backup(env: dict, *, include_keys: bool = False, now: Optional[str] = None) -> list:
    root = require_owned_root(env)
    uid, gid = _ids(env)
    db_file = root / "db" / "mcma.sqlite3"
    if not db_file.is_file():
        raise DeployError(f"no database at {db_file}; nothing to back up")
    stamp = now or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir = root / "backups"
    out_dir.mkdir(mode=0o700, exist_ok=True)
    archive = out_dir / f"mcma-backup-{stamp}.tar.gz"
    if archive.exists():
        raise DeployError(f"{archive} already exists")

    with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
        stage = Path(tmp)
        os.chmod(stage, 0o700)
        (stage / "db").mkdir()
        # SQLite online-backup API: a consistent snapshot even while the
        # service runs (WAL), unlike copying the file.
        source = sqlite3.connect(str(db_file))
        try:
            dest = sqlite3.connect(str(stage / "db" / "mcma.sqlite3"))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
        _fix_db_ownership(db_file.parent, uid, gid)
        check = sqlite3.connect(str(stage / "db" / "mcma.sqlite3"))
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DeployError("the database snapshot failed its integrity check; backup aborted")
        finally:
            check.close()

        trees = ["vault", "config"] + (["keys"] if include_keys else [])
        for tree in trees:
            shutil.copytree(root / tree, stage / tree)
        manifest = {
            str(p.relative_to(stage)).replace(os.sep, "/"): _sha256(p)
            for p in sorted(stage.rglob("*")) if p.is_file()
        }
        (stage / "MANIFEST.json").write_text(
            json.dumps({"created": stamp, "includes_keys": include_keys, "sha256": manifest}, indent=1),
            encoding="utf-8",
        )
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
            for entry in sorted(stage.iterdir()):
                tar.add(entry, arcname=entry.name)
    lines = [f"backup written: {archive} (mode 0600)"]
    if not include_keys:
        lines.append("keys were NOT included: back up the two key files separately -- without them the vault cannot be decrypted")
    return lines


def _safe_members(tar: tarfile.TarFile) -> list:
    members = tar.getmembers()
    for member in members:
        name = member.name
        if name.startswith("/") or ".." in Path(name).parts:
            raise DeployError(f"unsafe path in archive: {name}")
        if not (member.isfile() or member.isdir()):
            raise DeployError(f"unexpected entry type in archive: {name}")
        top = Path(name).parts[0] if Path(name).parts else ""
        if name != "MANIFEST.json" and top not in _BACKUP_TREES:
            raise DeployError(f"unexpected top-level entry in archive: {name}")
    return members


def load_manifest(stage: Path) -> dict:
    """Strict manifest validation. Returns {relative path: sha256}. Every
    listed file must exist, every extracted file must be listed."""
    manifest_file = stage / "MANIFEST.json"
    if not manifest_file.is_file():
        raise DeployError("archive has no MANIFEST.json; refusing to restore")
    try:
        document = json.loads(manifest_file.read_text(encoding="utf-8"))
        listed = document["sha256"]
        if not isinstance(listed, dict) or not listed:
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise DeployError("MANIFEST.json is malformed; refusing to restore") from None
    for rel, digest in listed.items():
        parts = PurePosixPath(rel).parts if isinstance(rel, str) else ()
        if (not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel or not parts
                or ".." in parts or "." in parts or posixpath.normpath(rel) != rel
                or parts[0] not in _BACKUP_TREES):
            raise DeployError(f"MANIFEST.json contains an unsafe path: {rel!r}")
        if not isinstance(digest, str) or not _HEX64.match(digest):
            raise DeployError(f"MANIFEST.json has a malformed checksum for {rel}")
        target = stage / rel
        if not target.is_file() or target.is_symlink():
            raise DeployError(f"MANIFEST.json names {rel}, which is missing from the archive")
    if "db/mcma.sqlite3" not in listed:
        raise DeployError("MANIFEST.json does not include db/mcma.sqlite3")
    present = {
        str(p.relative_to(stage)).replace(os.sep, "/") for p in stage.rglob("*") if p.is_file()
    } - {"MANIFEST.json"}
    unlisted = sorted(present - set(listed))
    if unlisted:
        raise DeployError(f"the archive contains files not listed in MANIFEST.json: {unlisted[0]}")
    for rel, digest in listed.items():
        if _sha256(stage / rel) != digest:
            raise DeployError(f"archive integrity check failed for {rel}")
    return listed


def cmd_restore(
    env: dict, archive: Path, *, with_config: bool = False, with_keys: bool = False,
    now: Optional[str] = None, check_running: bool = True,
) -> list:
    root = require_owned_root(env)
    if check_running:
        require_stopped()          # must POSITIVELY establish the MCMA container is not running
    uid, gid = _ids(env)
    stamp = now or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    lines = []
    with tempfile.TemporaryDirectory(dir=root / "backups") as tmp:
        stage = Path(tmp)
        os.chmod(stage, 0o700)
        with tarfile.open(archive, "r:gz") as tar:
            members = _safe_members(tar)
            tar.extractall(stage, members=members, filter="data")
        load_manifest(stage)
        db_new = stage / "db" / "mcma.sqlite3"
        conn = sqlite3.connect(str(db_new))
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DeployError("the archived database failed its integrity check")
        finally:
            conn.close()

        db_dir, vault = root / "db", root / "vault"
        current = db_dir / "mcma.sqlite3"
        if current.exists():
            os.replace(current, db_dir / f"mcma.sqlite3.pre-restore-{stamp}")
            lines.append(f"previous database kept as mcma.sqlite3.pre-restore-{stamp}")
        for suffix in ("-wal", "-shm"):
            (db_dir / f"mcma.sqlite3{suffix}").unlink(missing_ok=True)
        shutil.copy2(db_new, current)
        os.chmod(current, 0o600)
        _chown(current, uid, gid)

        if (stage / "vault").is_dir():
            kept = root / f"vault.pre-restore-{stamp}"
            os.replace(vault, kept)
            shutil.copytree(stage / "vault", vault)
            os.chmod(vault, 0o700)
            _chown(vault, uid, gid)
            for entry in vault.rglob("*"):
                os.chmod(entry, 0o600 if entry.is_file() else 0o700)
                _chown(entry, uid, gid)
            lines.append(f"previous vault kept as {kept.name}")
        for flag, tree in ((with_config, "config"), (with_keys, "keys")):
            if flag and (stage / tree).is_dir():
                for entry in (stage / tree).iterdir():
                    target = root / tree / entry.name
                    shutil.copy2(entry, target)
                    os.chmod(target, 0o600 if tree == "keys" else 0o640)
                    _chown(target, uid, gid)
                lines.append(f"restored {tree}/")
    lines.append("restore complete; run `mcma-deploy.sh check` then `up`")
    return lines


# --------------------------------------------------------------------- #
# env file tag
# --------------------------------------------------------------------- #


def cmd_set_tag(env_file: Path, tag: str) -> list:
    if not _TAG_RE.match(tag):
        raise DeployError("invalid image tag")
    target = os.path.realpath(env_file)            # replace the real file, never a symlink to it
    try:
        text = Path(target).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise DeployError(f"the env file {env_file} cannot be read") from None
    if re.search(r"^MCMA_IMAGE_TAG=.*$", text, flags=re.M):
        text = re.sub(r"^MCMA_IMAGE_TAG=.*$", f"MCMA_IMAGE_TAG={tag}", text, flags=re.M)
    else:
        text += f"\nMCMA_IMAGE_TAG={tag}\n"
    _atomic_write(target, text.encode("utf-8"))
    return [f"MCMA_IMAGE_TAG={tag}"]


def _atomic_write(target: str, data: bytes) -> None:
    """Replaces `target` with `data` so that a failure or interruption at any
    point before the final rename leaves the original byte-for-byte intact:
    unique temp file in the SAME directory (same filesystem), original owner,
    group and mode, complete write, flush + fsync, os.replace, then (POSIX) an
    fsync of the parent directory. Errors become DeployError with a fixed
    message -- never file contents."""
    directory = os.path.dirname(target) or "."
    temp = None
    try:
        original = os.stat(target)
        fd, temp = tempfile.mkstemp(prefix=".mcma-env.", suffix=".tmp", dir=directory)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, stat.S_IMODE(original.st_mode))
                if hasattr(os, "fchown") and (original.st_uid, original.st_gid) != (os.getuid(), os.getgid()):
                    os.fchown(fd, original.st_uid, original.st_gid)   # PermissionError -> abort, never silently re-own
            else:
                os.chmod(temp, stat.S_IMODE(original.st_mode))
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)                                             # data is on disk before the rename
        finally:
            os.close(fd)
        os.replace(temp, target)
        temp = None                                                  # it is now the real file
    except (OSError, ValueError):
        raise DeployError(
            f"the env file {target} could not be updated safely; the original is unchanged"
        ) from None
    finally:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
    if os.name == "posix":
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            raise DeployError(
                f"the env file {target} was replaced but its directory could not be synced; verify it"
            ) from None


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "gen-keys", "gen-dev-cert", "show-cert", "up"):
        sub.add_parser(name)
    tls = sub.add_parser("install-tls")
    tls.add_argument("--cert", required=True, type=Path)
    tls.add_argument("--key", required=True, type=Path)
    check = sub.add_parser("check")
    check.add_argument("--no-host", action="store_true", help="skip Docker-network, route and port checks")
    health = sub.add_parser("wait-healthy")
    health.add_argument("--timeout", type=float, default=180.0)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("tag")
    verify = sub.add_parser("verify-image")
    verify.add_argument("tag")
    export = sub.add_parser("export-image")
    export.add_argument("tag")
    export.add_argument("--out-dir", type=Path, default=Path("."))
    load = sub.add_parser("import-image")
    load.add_argument("archive", type=Path)
    backup = sub.add_parser("backup")
    backup.add_argument("--include-keys", action="store_true")
    restore = sub.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--with-config", action="store_true")
    restore.add_argument("--with-keys", action="store_true")
    tag = sub.add_parser("set-tag")
    tag.add_argument("tag")
    args = parser.parse_args(argv)

    try:
        if args.command == "set-tag":
            lines = cmd_set_tag(args.env_file, args.tag)
        elif args.command == "verify-image":       # image-only commands need no env file
            lines = cmd_verify_image(args.tag)
        elif args.command == "export-image":
            lines = cmd_export_image(args.tag, args.out_dir)
        elif args.command == "import-image":
            lines = cmd_import_image(args.archive)
        else:
            env = parse_env(args.env_file)
            problems = validate_env(env) if args.command not in ("init",) else []
            if problems and args.command not in ("check",):
                raise DeployError(problems)
            if args.command == "init":
                lines = cmd_init(env)
            elif args.command == "gen-keys":
                lines = cmd_gen_keys(env)
            elif args.command == "gen-dev-cert":
                lines = cmd_gen_dev_cert(env)
            elif args.command == "show-cert":
                pem, fingerprint = cmd_show_cert(env)
                print(pem, end="")
                print(fingerprint, file=sys.stderr)
                return 0
            elif args.command == "install-tls":
                lines = cmd_install_tls(env, args.cert, args.key)
            elif args.command == "check":
                lines = cmd_check(env, host=not args.no_host)
            elif args.command == "up":
                lines = cmd_up(args.env_file)
            elif args.command == "wait-healthy":
                lines = wait_healthy(env["MCMA_IMAGE_TAG"], timeout=args.timeout)
            elif args.command == "rollback":
                lines = cmd_rollback(args.env_file, args.tag)
            elif args.command == "backup":
                lines = cmd_backup(env, include_keys=args.include_keys)
            else:
                lines = cmd_restore(env, args.archive, with_config=args.with_config, with_keys=args.with_keys)
    except DeployError as exc:
        for problem in exc.problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
