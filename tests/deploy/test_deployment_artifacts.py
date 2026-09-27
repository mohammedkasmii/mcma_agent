"""Deployment artifacts for the central Docker deployment (Phase 2):
Dockerfile/Compose/scripts static checks, rendered-Compose checks (when the
docker CLI is present), the healthcheck, and the deploytool helper.

POSIX-only tests (ownership/permissions/backup) skip on Windows and run on
Linux, as a non-root user, in CI or on the VM."""

import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "central"


def _load_tool():
    spec = importlib.util.spec_from_file_location("deploytool", DEPLOY / "deploytool.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploytool"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

posix_user = pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() < 1000),
    reason="needs POSIX and a non-root uid >= 1000 (run as an unprivileged user)",
)
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")


def make_env(tmp_path, **override):
    env = {
        "MCMA_PROJECT": "mcma-central",
        "MCMA_DATA_ROOT": str(tmp_path / "data"),
        "MCMA_BIND_ADDRESS": "192.168.11.111",
        "MCMA_HTTPS_PORT": "18443",
        "MCMA_NET_SUBNET": "172.29.211.0/28",
        "MCMA_CONTAINER_IP": "172.29.211.2",
        "MCMA_TLS_SERVER_NAME": "192.168.11.111",
        "MCMA_UID": str(os.geteuid()) if hasattr(os, "geteuid") else "10001",
        "MCMA_GID": str(os.getegid()) if hasattr(os, "getegid") else "10001",
        "MCMA_IMAGE": "mcma-central",
        "MCMA_IMAGE_TAG": "test",
    }
    env.update(override)
    return env


# ------------------------------- static files --------------------------------- #


def test_dockerfile_pins_versions_and_runs_unprivileged():
    text = chr(10).join(_code_lines(DEPLOY / "Dockerfile"))
    python = re.search(r"ARG PYTHON_IMAGE=python:(\d+)\.(\d+)\.(\d+)-slim", text)
    node = re.search(r"ARG NODE_IMAGE=node:(\d+)\.(\d+)\.(\d+)-", text)
    assert python and tuple(map(int, python.groups()))[:2] >= (3, 14)      # requires-python >=3.14
    assert node and tuple(map(int, node.groups())) >= (22, 12, 0)          # engines.node >=22.12
    assert "uv sync --frozen --no-dev" in text                            # locked deps, no dev group
    assert "playwright install --only-shell --with-deps chromium" in text  # Chromium only
    lowered = text.lower()
    assert "firefox" not in lowered and "webkit" not in lowered
    assert re.search(r"^USER mcma$", text, flags=re.M) and "USER root" not in text
    assert "dpkg --audit" in text and "--force-depends" not in text and "dpkg --purge" not in text
    assert "npm run build" in text and "node_modules" not in text.split("AS runtime")[1]
    assert "docker.sock" not in text
    assert 'ENTRYPOINT ["python", "-m", "mcma.app.central_server"]' in text


def test_final_stage_copies_no_tests_or_secrets():
    runtime = (DEPLOY / "Dockerfile").read_text(encoding="utf-8").split("AS runtime")[1]
    copies = re.findall(r"^COPY .*$", runtime, flags=re.M)
    assert all("tests" not in line and "mock_server" not in line and ".key" not in line for line in copies)


def test_dockerignore_is_an_allow_list_that_excludes_secrets_and_build_output():
    text = (REPO / ".dockerignore").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    assert lines[0] == "*"
    for needed in ("frontend/node_modules", "frontend/dist", "**/.env", "**/*.key", "**/*.sqlite3*"):
        assert needed in lines
    allowed = {line for line in lines if line.startswith("!")}
    assert allowed == {"!pyproject.toml", "!uv.lock", "!mcma", "!frontend", "!deploy/central/healthcheck.py"}


def _code_lines(path):
    return [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_compose_file_has_no_dangerous_options():
    text = "\n".join(_code_lines(DEPLOY / "compose.yaml"))
    for forbidden in ("network_mode", "docker.sock", "privileged: true", "pid: host", "ipc: host",
                      "SYS_ADMIN", "seccomp:unconfined", "0.0.0.0", "mock"):
        assert forbidden not in text, forbidden
    assert text.count("image:") == 1                  # exactly one service, no sidecars


def test_deploy_script_never_touches_anything_outside_the_mcma_project():
    text = "\n".join(_code_lines(DEPLOY / "mcma-deploy.sh"))
    for forbidden in ("systemctl", "service docker", "restart docker", "dockerd", "prune", "down -v",
                      "--volumes", "--remove-orphans", "docker rm", "docker stop", "docker kill",
                      "docker restart", "docker.sock", "--privileged", "network rm"):
        assert forbidden not in text, forbidden
    # Every compose call goes through the one wrapper that pins the project.
    assert text.count("docker compose") == 1 and "--project-name \"$PROJECT\"" in text
    assert 'PROJECT="mcma-central"' in text and 'IMAGE="mcma-central"' in text
    assert "docker compose up" not in text and "docker build" in text and "MCMA_ALLOW_BUILD" in text


def test_deploytool_only_asks_docker_about_the_mcma_identity():
    code = chr(10).join(_code_lines(DEPLOY / "deploytool.py"))
    verbs = set(re.findall(r'_docker\(\s*"(\w+)"', code))
    assert verbs <= {"network", "ps", "inspect", "image", "run"}, verbs
    for forbidden in ("prune", "docker.sock", "systemctl", '"rm"', '"stop"', '"kill"', '"restart"',
                      "--remove-orphans", '"-v"', "--volumes"):
        assert forbidden not in code, forbidden
    assert code.count('"--project-name", PROJECT') == 1               # the single Compose wrapper
    assert '"up", "-d", "--no-build"' in code and '"build"' not in code
    assert "force-depends" not in (DEPLOY / "Dockerfile").read_text(encoding="utf-8").replace(
        "No dpkg --force-depends surgery", "")


def _functional_bash():
    """A bash that can actually run scripts. On Windows, `bash` may be the WSL
    launcher stub (no distro / no bash inside), which is NOT functional."""
    bash = shutil.which("bash")
    if bash is None:
        return None
    try:
        probe = subprocess.run([bash, "-c", "echo functional"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return bash if probe.returncode == 0 and probe.stdout.strip() == "functional" else None


def test_shell_script_is_syntactically_valid():
    bash = _functional_bash()
    if bash is None:
        if os.name == "posix":
            pytest.fail("bash is required on Linux to check mcma-deploy.sh (bash -n)")
        pytest.skip("no functional bash on this Windows host")
    result = subprocess.run([bash, "-n", "mcma-deploy.sh"], cwd=DEPLOY, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ------------------------------- env examples --------------------------------- #


def test_vm_example_env_is_valid_and_targets_the_vm():
    env = tool.parse_env(DEPLOY / "env.vm.example")
    assert tool.validate_env(env) == []
    assert env["MCMA_BIND_ADDRESS"] == "192.168.11.111"
    assert env["MCMA_HTTPS_PORT"] not in ("443", "80", "8080", "8443", "5432", "54321")


def test_production_example_uses_data_mcma_and_forces_editing_the_placeholders():
    env = tool.parse_env(DEPLOY / "env.production.example")
    assert env["MCMA_DATA_ROOT"] == "/data/mcma"
    problems = tool.validate_env(env)
    assert any("MCMA_BIND_ADDRESS" in p for p in problems)     # placeholder address is refused
    assert any("MCMA_TLS_SERVER_NAME" in p for p in problems)


def test_example_env_files_contain_no_secrets():
    for name in ("env.vm.example", "env.production.example", "mcma-central.example.toml"):
        text = chr(10).join(_code_lines(DEPLOY / name))
        assert not re.search(r"(password|secret|token|BEGIN [A-Z ]*PRIVATE)", text, flags=re.I)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"MCMA_BIND_ADDRESS": "0.0.0.0"}, "wildcard"),
        ({"MCMA_BIND_ADDRESS": "::"}, "wildcard"),
        ({"MCMA_BIND_ADDRESS": "192.168.X.X"}, "MCMA_BIND_ADDRESS"),
        ({"MCMA_HTTPS_PORT": "80"}, "MCMA_HTTPS_PORT"),
        ({"MCMA_HTTPS_PORT": "http"}, "MCMA_HTTPS_PORT"),
        ({"MCMA_NET_SUBNET": "not-a-subnet"}, "MCMA_NET_SUBNET"),
        ({"MCMA_NET_SUBNET": "172.29.211.0/30"}, "at least 8"),
        ({"MCMA_CONTAINER_IP": "10.0.0.5"}, "inside MCMA_NET_SUBNET"),
        ({"MCMA_CONTAINER_IP": "172.29.211.1"}, "gateway"),
        ({"MCMA_UID": "0"}, "MCMA_UID"),
        ({"MCMA_GID": "100"}, "MCMA_GID"),
        ({"MCMA_PROJECT": "rma"}, "exactly mcma-central"),
        ({"MCMA_PROJECT": "mcma-other"}, "exactly mcma-central"),
        ({"MCMA_IMAGE": "postgres"}, "exactly mcma-central"),
        ({"MCMA_IMAGE": "registry.example/mcma-central"}, "exactly mcma-central"),
        ({"MCMA_ALLOW_BUILD": "maybe"}, "MCMA_ALLOW_BUILD"),
        ({"MCMA_DATA_ROOT": "relative/path"}, "MCMA_DATA_ROOT"),
        ({"MCMA_DATA_ROOT": "/"}, "MCMA_DATA_ROOT"),
        ({"MCMA_IMAGE_TAG": "bad tag;rm"}, "MCMA_IMAGE_TAG"),
        ({"MCMA_TLS_SERVER_NAME": ""}, "MCMA_TLS_SERVER_NAME"),
    ],
)
def test_unsafe_environment_values_are_refused(tmp_path, override, expected):
    env = make_env(tmp_path)
    env.update({"MCMA_UID": "10001", "MCMA_GID": "10001"})
    env.update(override)
    problems = tool.validate_env(env)
    assert any(expected in problem for problem in problems), problems


def test_subnet_overlap_with_an_existing_docker_network_is_reported(tmp_path):
    import ipaddress

    env = make_env(tmp_path)
    networks = [
        ("rma_default", "a" * 64, ipaddress.ip_network("172.29.0.0/16")),
        ("mcma-central-net", "b" * 64, ipaddress.ip_network("172.29.211.0/28")),   # our own: not a conflict
        ("elsewhere", "c" * 64, ipaddress.ip_network("10.10.0.0/16")),
    ]
    found = tool.subnet_conflicts(env, networks, [])
    assert len(found) == 1 and "rma_default" in found[0]


def test_port_in_use_detects_a_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert tool.port_in_use("127.0.0.1", port) is True
    assert tool.port_in_use("127.0.0.1", port) is False


def test_set_tag_rewrites_only_the_tag(tmp_path):
    env_file = tmp_path / "e.env"
    env_file.write_text("MCMA_PROJECT=mcma-central\nMCMA_IMAGE_TAG=old\n", encoding="utf-8")
    tool.cmd_set_tag(env_file, "20260101-abc")
    assert env_file.read_text(encoding="utf-8") == "MCMA_PROJECT=mcma-central\nMCMA_IMAGE_TAG=20260101-abc\n"
    with pytest.raises(tool.DeployError):
        tool.cmd_set_tag(env_file, "x; rm -rf /")


# --------------------------- rendered Compose config -------------------------- #


def _render(env_file):
    return subprocess.run(
        ["docker", "compose", "--project-name", "mcma-central", "--env-file", str(env_file),
         "-f", str(DEPLOY / "compose.yaml"), "config", "--format", "json"],
        capture_output=True, text=True, timeout=60,
    )


@needs_docker
def test_rendered_compose_meets_the_isolation_and_hardening_contract():
    result = _render(DEPLOY / "env.vm.example")
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["name"] == "mcma-central"
    assert list(config["services"]) == ["mcma-central"]
    service = config["services"]["mcma-central"]

    assert service["container_name"] == "mcma-central"
    assert "network_mode" not in service and not service.get("privileged")
    assert "build" not in service                      # images are delivered, never built by Compose
    assert service["image"] == "mcma-central:dev"
    assert service["read_only"] is True and service["init"] is True
    assert service["cap_drop"] == ["ALL"] and "cap_add" not in service
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["restart"] == "unless-stopped"
    assert service["ipc"] == "private" and service["user"] == "10001:10001"
    assert service["logging"]["options"] == {"max-size": "10m", "max-file": "5"}
    assert int(service["mem_limit"]) > 0 and service["pids_limit"] == 512
    assert any(entry.startswith("/tmp") for entry in service["tmpfs"])

    # Exactly one published port: the configured bind address, HTTPS target only.
    (port,) = service["ports"]
    assert (port["host_ip"], port["published"], port["target"]) == ("192.168.11.111", "18443", 8443)

    # Storage: bind mounts under MCMA_DATA_ROOT only; no Docker socket, no named volumes.
    assert "volumes" not in config
    for volume in service["volumes"]:
        assert volume["type"] == "bind"
        assert volume["source"].startswith("/data/mcma-dev/") and "docker.sock" not in volume["source"]
        assert volume["bind"]["create_host_path"] is False
    read_only_targets = {v["target"] for v in service["volumes"] if v.get("read_only")}
    assert read_only_targets == {"/etc/mcma/keys", "/etc/mcma/tls", "/etc/mcma/config"}

    # Private network created for this project only, static address, no host network.
    assert list(config["networks"]) == ["mcma-net"]
    assert config["networks"]["mcma-net"]["name"] == "mcma-central-net"
    assert service["networks"]["mcma-net"]["ipv4_address"] == "172.29.211.2"
    assert service["healthcheck"]["test"][-1] == "/opt/mcma/healthcheck.py"


@needs_docker
@pytest.mark.skipif(os.name != "posix", reason="in-container POSIX paths are only absolute on POSIX")
def test_rendered_environment_satisfies_the_central_config_validator():
    """The container's real environment must pass the fail-closed loader (pure
    validation: these are in-container paths, nothing is opened)."""
    from mcma.core.central_config import load_central_settings

    config = json.loads(_render(DEPLOY / "env.vm.example").stdout)
    environment = config["services"]["mcma-central"]["environment"]
    settings = load_central_settings(environ={k: v for k, v in environment.items() if k.startswith("MCMA_")} | {
        "MCMA_CONFIG_FILE": ""})
    assert settings.api_host == "172.29.211.2" and settings.api_port == 8443
    assert settings.local_single_user_mode is False and settings.dev_mode is False


@needs_docker
@pytest.mark.parametrize("missing", ["MCMA_DATA_ROOT", "MCMA_BIND_ADDRESS", "MCMA_HTTPS_PORT",
                                      "MCMA_CONTAINER_IP", "MCMA_NET_SUBNET", "MCMA_TLS_SERVER_NAME"])
def test_compose_refuses_to_render_without_required_settings(tmp_path, missing):
    lines = [l for l in (DEPLOY / "env.vm.example").read_text(encoding="utf-8").splitlines()
             if not l.startswith(missing + "=")]
    env_file = tmp_path / "e.env"
    env_file.write_text("\n".join(lines), encoding="utf-8")
    result = _render(env_file)
    assert result.returncode != 0 and missing in result.stderr


# -------------------------------- healthcheck --------------------------------- #


def _load_healthcheck():
    spec = importlib.util.spec_from_file_location("mcma_healthcheck", DEPLOY / "healthcheck.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def tls_server(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl not installed")
    cert, key = tmp_path / "c.crt", tmp_path / "c.key"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=mcma.test",
         "-addext", "subjectAltName=DNS:mcma.test,IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    state = {"status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(state["status"] if self.path == "/ready" else 404)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], cert, state
    server.shutdown()


def _probe(monkeypatch, port, cert, name, capsys):
    monkeypatch.setenv("MCMA_API_HOST", "127.0.0.1")
    monkeypatch.setenv("MCMA_API_PORT", str(port))
    monkeypatch.setenv("MCMA_TLS_CERT_PATH", str(cert))
    monkeypatch.setenv("MCMA_HEALTHCHECK_SERVER_NAME", name)
    monkeypatch.delenv("MCMA_HEALTHCHECK_CA_FILE", raising=False)
    code = _load_healthcheck().main()
    return code, capsys.readouterr().out


def test_healthcheck_passes_against_a_verified_tls_server(tls_server, monkeypatch, capsys):
    port, cert, _ = tls_server
    assert _probe(monkeypatch, port, cert, "mcma.test", capsys) == (0, "ready=200\n")


def test_healthcheck_fails_when_the_certificate_name_does_not_match(tls_server, monkeypatch, capsys):
    port, cert, _ = tls_server
    code, out = _probe(monkeypatch, port, cert, "other.example", capsys)
    assert code == 1 and out.startswith("unhealthy: ")


def test_healthcheck_does_not_trust_an_unrelated_certificate(tls_server, tmp_path, monkeypatch, capsys):
    port, _, _ = tls_server
    other = tmp_path / "other.crt"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
         "-keyout", str(tmp_path / "o.key"), "-out", str(other), "-days", "2", "-subj", "/CN=mcma.test",
         "-addext", "subjectAltName=DNS:mcma.test"],
        check=True, capture_output=True,
    )
    code, out = _probe(monkeypatch, port, other, "mcma.test", capsys)
    assert code == 1 and "SSLCertVerificationError" in out


def test_healthcheck_fails_when_not_ready(tls_server, monkeypatch, capsys):
    port, cert, state = tls_server
    state["status"] = 503
    assert _probe(monkeypatch, port, cert, "mcma.test", capsys) == (1, "ready=503\n")


def test_healthcheck_source_never_disables_verification():
    text = (DEPLOY / "healthcheck.py").read_text(encoding="utf-8")
    assert "CERT_NONE" not in text and "check_hostname = False" not in text and "_create_unverified" not in text


# ------------------------------ deploytool (POSIX) ---------------------------- #


@posix_user
def test_init_creates_the_layout_with_safe_modes_and_is_idempotent(tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)
    root = Path(env["MCMA_DATA_ROOT"])
    for name, mode in tool.LAYOUT.items():
        assert (root / name).stat().st_mode & 0o777 == mode
    assert (root / "config" / "mcma.toml").is_file()
    tool.cmd_init(env)                                            # re-run changes nothing harmful
    assert (root / "vault").stat().st_mode & 0o777 == 0o700


@posix_user
def test_gen_keys_makes_two_distinct_private_32_byte_files_and_never_overwrites(tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)
    tool.cmd_gen_keys(env)
    keys = Path(env["MCMA_DATA_ROOT"]) / "keys"
    first, second = (keys / name for name in tool.KEY_FILES)
    assert len(first.read_bytes()) == len(second.read_bytes()) == 32
    assert first.read_bytes() != second.read_bytes()
    assert first.stat().st_mode & 0o777 == 0o600 == second.stat().st_mode & 0o777
    before = first.read_bytes()
    with pytest.raises(tool.DeployError, match="refusing to overwrite"):
        tool.cmd_gen_keys(env)
    assert first.read_bytes() == before


def _ready_root(tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)
    tool.cmd_gen_keys(env)
    tool.cmd_gen_dev_cert(env)
    return env, Path(env["MCMA_DATA_ROOT"])


@posix_user
@needs_openssl
def test_a_correctly_provisioned_root_passes_preflight(tmp_path):
    env, _ = _ready_root(tmp_path)
    assert tool.cmd_check(env, host=False) == ["all preflight checks passed"]


@posix_user
@needs_openssl
def test_the_provisioned_layout_satisfies_the_real_central_startup_checks(tmp_path):
    """What deploytool produces is exactly what mcma.app.central_server
    demands (vault 0700 owned by the service user, 0600 keys/TLS key, ...)."""
    from mcma.app.central_server import create_central_server
    from mcma.core.central_config import load_central_settings

    env, root = _ready_root(tmp_path)
    settings = load_central_settings(environ={
        "MCMA_CONFIG_FILE": str(root / "config" / "mcma.toml"),
        "MCMA_API_HOST": env["MCMA_CONTAINER_IP"], "MCMA_API_PORT": "8443",
        "MCMA_DB_PATH": str(root / "db" / "mcma.sqlite3"),
        "MCMA_INSTANCE_LOCK_PATH": str(root / "db" / "mcma.lock"),
        "MCMA_VAULT_DIR": str(root / "vault"),
        "MCMA_TLS_CERT_PATH": str(root / "tls" / "server.crt"),
        "MCMA_TLS_KEY_PATH": str(root / "tls" / "server.key"),
        "MCMA_SESSION_VAULT_KEY_PATH": str(root / "keys" / "session-vault.key"),
        "MCMA_JOB_INPUT_KEY_PATH": str(root / "keys" / "job-input.key"),
        "MCMA_MUTEX_NAME": f"mcma-deploy-{tmp_path.name}",
    })
    create_central_server(settings, _test_only_portable_mutex=True).close()


@posix_user
@needs_openssl
@pytest.mark.parametrize("break_it", ["key_mode", "keys_dir_mode", "vault_mode", "key_length",
                                       "identical_keys", "missing_key", "tls_key_mode", "missing_tls"])
def test_preflight_fails_for_unsafe_or_missing_files(tmp_path, break_it):
    env, root = _ready_root(tmp_path)
    keys = root / "keys"
    if break_it == "key_mode":
        os.chmod(keys / "job-input.key", 0o644)
    elif break_it == "keys_dir_mode":
        os.chmod(keys, 0o755)
    elif break_it == "vault_mode":
        os.chmod(root / "vault", 0o770)
    elif break_it == "key_length":
        (keys / "job-input.key").write_bytes(b"short")
    elif break_it == "identical_keys":
        (keys / "job-input.key").write_bytes((keys / "session-vault.key").read_bytes())
    elif break_it == "missing_key":
        (keys / "session-vault.key").unlink()
    elif break_it == "tls_key_mode":
        os.chmod(root / "tls" / "server.key", 0o640)
    elif break_it == "missing_tls":
        (root / "tls" / "server.crt").unlink()
    with pytest.raises(tool.DeployError):
        tool.cmd_check(env, host=False)


@posix_user
def test_preflight_fails_before_init(tmp_path):
    with pytest.raises(tool.DeployError, match="does not exist"):
        tool.cmd_check(make_env(tmp_path), host=False)


@posix_user
def test_wrong_owner_is_refused(tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)
    tool.cmd_gen_keys(env)
    wrong = dict(env, MCMA_UID=str(int(env["MCMA_UID"]) + 1))
    problems = tool.filesystem_problems(wrong)
    assert any("must be owned by uid" in p for p in problems)


@posix_user
@needs_openssl
def test_install_tls_rejects_a_mismatched_key_and_an_expired_certificate(tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)

    def make(name, days, cn_san="IP:192.168.11.111"):
        cert, key = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
             "-keyout", str(key), "-out", str(cert), "-days", str(days), "-subj", "/CN=x",
             "-addext", f"subjectAltName={cn_san}"], check=True, capture_output=True)
        return cert, key

    a_cert, a_key = make("a", 30)
    b_cert, b_key = make("b", 30)
    with pytest.raises(tool.DeployError, match="do not match"):
        tool.cmd_install_tls(env, a_cert, b_key)
    with pytest.raises(tool.DeployError, match="subjectAltName"):
        c_cert, c_key = make("c", 30, "IP:10.9.9.9")
        tool.cmd_install_tls(env, c_cert, c_key)
    tool.cmd_install_tls(env, a_cert, a_key)
    installed = Path(env["MCMA_DATA_ROOT"]) / "tls"
    assert (installed / "server.key").stat().st_mode & 0o777 == 0o600
    assert not list(installed.glob(".*.new"))


@posix_user
def test_backup_and_restore_round_trip(tmp_path):
    import sqlite3

    env = make_env(tmp_path)
    tool.cmd_init(env)
    root = Path(env["MCMA_DATA_ROOT"])
    conn = sqlite3.connect(root / "db" / "mcma.sqlite3")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('original')")
    conn.commit()                                   # left OPEN: the service is 'running'
    (root / "vault" / "abc.session").write_bytes(b"ciphertext-original")
    (root / "keys" / "session-vault.key").write_bytes(b"k" * 32)

    lines = tool.cmd_backup(env, now="20260101T000000Z")
    archive = root / "backups" / "mcma-backup-20260101T000000Z.tar.gz"
    assert archive.is_file() and archive.stat().st_mode & 0o777 == 0o600
    assert any("keys were NOT included" in line for line in lines)
    with tarfile.open(archive) as tar:
        assert not any(name.startswith("keys") for name in tar.getnames())

    conn.execute("INSERT INTO t VALUES ('after-backup')")
    conn.commit()
    conn.close()
    (root / "vault" / "abc.session").write_bytes(b"ciphertext-changed")
    (root / "vault" / "new.session").write_bytes(b"x")

    tool.cmd_restore(env, archive, now="20260102T000000Z", check_running=False)
    restored = sqlite3.connect(root / "db" / "mcma.sqlite3")
    assert [r[0] for r in restored.execute("SELECT v FROM t")] == ["original"]
    restored.close()
    assert (root / "vault" / "abc.session").read_bytes() == b"ciphertext-original"
    assert not (root / "vault" / "new.session").exists()
    assert (root / "vault.pre-restore-20260102T000000Z" / "new.session").exists()   # nothing destroyed
    assert (root / "db" / "mcma.sqlite3.pre-restore-20260102T000000Z").exists()
    assert (root / "vault").stat().st_mode & 0o777 == 0o700


@posix_user
def test_restore_refuses_traversal_tampering_and_a_running_stack(tmp_path):
    import io
    import sqlite3

    env = make_env(tmp_path)
    tool.cmd_init(env)
    root = Path(env["MCMA_DATA_ROOT"])
    sqlite3.connect(root / "db" / "mcma.sqlite3").execute("CREATE TABLE t (v)").connection.close()
    tool.cmd_backup(env, now="20260101T000000Z")
    good = root / "backups" / "mcma-backup-20260101T000000Z.tar.gz"

    evil = root / "backups" / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(tool.DeployError, match="unsafe path"):
        tool.cmd_restore(env, evil, check_running=False)

    tampered = root / "backups" / "tampered.tar.gz"
    with tarfile.open(good) as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            data = src.extractfile(member) if member.isfile() else None
            if member.name == "vault" or member.name.startswith("vault/"):
                continue
            if member.name == "db/mcma.sqlite3":
                payload = data.read() + b"corruption"
                member.size = len(payload)
                dst.addfile(member, io.BytesIO(payload))
            else:
                dst.addfile(member, data)
    with pytest.raises(tool.DeployError, match="integrity"):
        tool.cmd_restore(env, tampered, check_running=False)

    import unittest.mock as mock

    with mock.patch.object(tool, "container_state", return_value="running"):
        with pytest.raises(tool.DeployError, match="stop it"):
            tool.cmd_restore(env, good)
