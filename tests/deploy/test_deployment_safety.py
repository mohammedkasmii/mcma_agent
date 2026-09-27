"""Phase 2 review fixes for deploytool: shared-server data-root safety,
fail-closed Docker/route inspection, single identity, transactional rollback,
immutable image delivery and strict restore-manifest validation."""

import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "central"


def _load_tool():
    spec = importlib.util.spec_from_file_location("deploytool_safety", DEPLOY / "deploytool.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploytool_safety"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

posix_user = pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() < 1000),
    reason="needs POSIX and a non-root uid >= 1000 (run as an unprivileged user)",
)
needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")


def make_env(tmp_path, **override):
    env = {
        "MCMA_PROJECT": "mcma-central", "MCMA_DATA_ROOT": str(tmp_path / "data"),
        "MCMA_BIND_ADDRESS": "192.168.11.111", "MCMA_HTTPS_PORT": "18443",
        "MCMA_NET_SUBNET": "172.29.211.0/28", "MCMA_CONTAINER_IP": "172.29.211.2",
        "MCMA_TLS_SERVER_NAME": "192.168.11.111",
        "MCMA_UID": str(os.geteuid()) if hasattr(os, "geteuid") else "10001",
        "MCMA_GID": str(os.getegid()) if hasattr(os, "getegid") else "10001",
        "MCMA_IMAGE": "mcma-central", "MCMA_IMAGE_TAG": "test",
    }
    env.update(override)
    return env


# ------------------------------ 1. data root safety ---------------------------- #


@pytest.mark.parametrize("path", [
    "/", "/data", "/home", "/root", "/opt", "/srv", "/var", "/var/lib", "/tmp", "/mnt", "/usr", "/etc",
    "/etc/mcma", "/usr/local/mcma", "/boot/x", "/proc/1", "/var/lib/docker/volumes/x", "/run/user",
    "/data/../etc", "/data//mcma", "/data/./mcma", "relative/mcma",
])
def test_broad_or_protected_data_roots_are_refused(path):
    assert tool.data_root_problems(path), path


@pytest.mark.parametrize("path", ["/data/mcma", "/data/mcma-dev", "/srv/mcma", "/opt/mcma-data"])
def test_dedicated_data_roots_are_accepted(path):
    assert tool.data_root_problems(path) == []


@posix_user
def test_init_refuses_an_existing_application_directory_without_the_marker(tmp_path):
    """A mistaken MCMA_DATA_ROOT pointing at somebody else's app directory."""
    app_dir = tmp_path / "data"
    (app_dir / "config").mkdir(parents=True)
    (app_dir / "config" / "app.yaml").write_text("someone-elses: config\n")
    (app_dir / "db").mkdir()
    os.chmod(app_dir, 0o755)
    os.chmod(app_dir / "db", 0o755)
    before = {p: p.stat().st_mode for p in [app_dir, app_dir / "db", app_dir / "config"]}

    with pytest.raises(tool.DeployError, match="no MCMA marker"):
        tool.cmd_init(make_env(tmp_path))

    assert {p: p.stat().st_mode for p in before} == before            # no chmod
    assert (app_dir / "config" / "app.yaml").read_text() == "someone-elses: config\n"
    assert not (app_dir / tool.MARKER).exists()                       # no marker written
    assert not (app_dir / "keys").exists() and not (app_dir / "config" / "mcma.toml").exists()


@posix_user
def test_init_creates_the_marker_and_later_runs_recognise_it(tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)
    root = Path(env["MCMA_DATA_ROOT"])
    assert (root / tool.MARKER).read_text() == tool.MARKER_TEXT
    tool.cmd_init(env)                                                # idempotent
    assert tool.marker_problem(root) is None


@posix_user
def test_an_empty_existing_directory_is_adopted_without_changing_its_mode(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    os.chmod(root, 0o711)
    tool.cmd_init(make_env(tmp_path))
    assert (root / tool.MARKER).is_file()
    assert root.stat().st_mode & 0o777 == 0o711


@posix_user
def test_a_symlinked_data_root_is_refused(tmp_path):
    real = tmp_path / "real-app"
    real.mkdir()
    (real / "precious.txt").write_text("x")
    (tmp_path / "data").symlink_to(real, target_is_directory=True)
    with pytest.raises(tool.DeployError, match="symlink"):
        tool.cmd_init(make_env(tmp_path))
    assert sorted(p.name for p in real.iterdir()) == ["precious.txt"]     # untouched


@posix_user
def test_a_symlinked_final_component_is_refused_even_when_marked(tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)
    moved = tmp_path / "moved"
    (tmp_path / "data").rename(moved)
    (tmp_path / "data").symlink_to(moved, target_is_directory=True)
    with pytest.raises(tool.DeployError, match="symlink"):
        tool.cmd_init(env)
    assert any("symlink" in p for p in tool.filesystem_problems(env))


@posix_user
def test_every_command_needing_the_root_requires_the_marker(tmp_path):
    env = make_env(tmp_path)
    Path(env["MCMA_DATA_ROOT"]).mkdir()
    (Path(env["MCMA_DATA_ROOT"]) / "keys").mkdir()
    for call in (lambda: tool.cmd_gen_keys(env), lambda: tool.cmd_backup(env),
                 lambda: tool.cmd_show_cert(env), lambda: tool.cmd_install_tls(env, Path("c"), Path("k"))):
        with pytest.raises(tool.DeployError, match="marker"):
            call()
    assert not list((Path(env["MCMA_DATA_ROOT"]) / "keys").iterdir())


# ---------------------- 2. Docker inspection fails closed ---------------------- #


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(["docker"], returncode, stdout, stderr)


def _patch_run(monkeypatch, behaviour):
    monkeypatch.setattr(tool.subprocess, "run", behaviour)


FAILURES = {
    "missing-cli": FileNotFoundError(),
    "permission-denied": PermissionError(),
    "timeout": subprocess.TimeoutExpired("docker", 30),
    "os-error": OSError("boom"),
}


@pytest.mark.parametrize("name", FAILURES)
def test_docker_exceptions_abort(monkeypatch, name):
    def run(*args, **kwargs):
        raise FAILURES[name]

    _patch_run(monkeypatch, run)
    for call in (tool.docker_networks, tool.container_state, tool.require_stopped):
        with pytest.raises(tool.DeployError):
            call()


def test_daemon_unavailable_and_permission_errors_abort(monkeypatch):
    _patch_run(monkeypatch, lambda *a, **k: _completed(returncode=1, stderr="Cannot connect to the Docker daemon"))
    for call in (tool.docker_networks, tool.container_state):
        with pytest.raises(tool.DeployError, match="Cannot connect"):
            call()
    _patch_run(monkeypatch, lambda *a, **k: _completed(returncode=1, stderr="permission denied while trying to connect"))
    with pytest.raises(tool.DeployError, match="permission denied"):
        tool.container_state()


def test_network_listing_and_inspection_failures_abort(monkeypatch):
    def scripted(outputs):
        calls = iter(outputs)
        return lambda *a, **k: next(calls)

    _patch_run(monkeypatch, scripted([_completed("")]))                     # empty listing
    with pytest.raises(tool.DeployError, match="no networks"):
        tool.docker_networks()
    _patch_run(monkeypatch, scripted([_completed("id1\n"), _completed("{not json")]))
    with pytest.raises(tool.DeployError, match="unusable"):
        tool.docker_networks()
    _patch_run(monkeypatch, scripted([_completed("id1\n"), _completed('{"a": 1}')]))   # not a list
    with pytest.raises(tool.DeployError, match="unusable"):
        tool.docker_networks()
    _patch_run(monkeypatch, scripted([_completed("id1\n"), _completed('[{"IPAM": {"Config": [{"Subnet": "junk"}]}, "Name": "n"}]')]))
    with pytest.raises(tool.DeployError, match="unusable"):
        tool.docker_networks()
    _patch_run(monkeypatch, scripted([_completed("id1\n"), _completed("", returncode=1, stderr="inspect failed")]))
    with pytest.raises(tool.DeployError):
        tool.docker_networks()


def test_preflight_aborts_when_docker_cannot_be_inspected(monkeypatch, tmp_path):
    def run(*args, **kwargs):
        raise FileNotFoundError()

    _patch_run(monkeypatch, run)
    with pytest.raises(tool.DeployError, match="not installed"):
        tool.host_problems(make_env(tmp_path))


def test_container_state_is_only_positive_when_unambiguous(monkeypatch):
    for output, expected in (
        ("", "absent"),
        ("mcma-central\texited\n", "stopped"),
        ("mcma-central\tcreated\n", "stopped"),
        ("mcma-central\trunning\n", "running"),
        ("mcma-central\tpaused\n", "running"),
        ("mcma-central\trestarting\n", "running"),
    ):
        _patch_run(monkeypatch, lambda *a, _o=output, **k: _completed(_o))
        assert tool.container_state() == expected
    for garbage in ("mcma-central-extra\texited\n", "mcma-central\tweird\n", "mcma-central\texited\nmcma-central\trunning\n", "x"):
        _patch_run(monkeypatch, lambda *a, _o=garbage, **k: _completed(_o))
        with pytest.raises(tool.DeployError):
            tool.container_state()


@posix_user
def test_restore_needs_a_positive_stopped_answer(monkeypatch, tmp_path):
    env = make_env(tmp_path)
    tool.cmd_init(env)
    archive = tmp_path / "irrelevant.tar.gz"
    archive.write_bytes(b"")
    for output, kwargs in (("mcma-central\trunning\n", {}), ):
        _patch_run(monkeypatch, lambda *a, _o=output, **k: _completed(_o))
        with pytest.raises(tool.DeployError, match="running"):
            tool.cmd_restore(env, archive)
    _patch_run(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(tool.DeployError, match="not installed"):
        tool.cmd_restore(env, archive)                                       # cannot establish -> abort
    _patch_run(monkeypatch, lambda *a, **k: _completed(returncode=1, stderr="daemon down"))
    with pytest.raises(tool.DeployError, match="daemon down"):
        tool.cmd_restore(env, archive)
    # Stopped is accepted -- the failure is then the (empty) archive, not the state check.
    _patch_run(monkeypatch, lambda *a, **k: _completed("mcma-central\texited\n"))
    with pytest.raises((tarfile.TarError, EOFError, OSError)):
        tool.cmd_restore(env, archive)


# ------------------------- 3. Docker networks + host routes -------------------- #

ROUTE_HEADER = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"


def _route(iface, dest, mask):
    def hexle(ip):
        import ipaddress

        return int(ipaddress.ip_address(ip)).to_bytes(4, "little").hex().upper()

    return f"{iface}\t{hexle(dest)}\t00000000\t0001\t0\t0\t0\t{hexle(mask)}\t0\t0\t0\n"


def test_host_routes_are_parsed_and_default_route_ignored():
    table = ROUTE_HEADER + _route("eth0", "0.0.0.0", "0.0.0.0") + _route("eth0", "192.168.11.0", "255.255.255.0") \
        + _route("br-abcdef123456", "172.29.211.0", "255.255.255.240")
    routes = tool.host_routes(lambda: table)
    assert [(i, str(n)) for i, n in routes] == [("eth0", "192.168.11.0/24"), ("br-abcdef123456", "172.29.211.0/28")]


@pytest.mark.parametrize("table", ["", "garbage\n", ROUTE_HEADER + "eth0 ZZ 0 0 0 0 0 00\n", ROUTE_HEADER + "eth0\n"])
def test_unreadable_routing_tables_abort(table):
    with pytest.raises(tool.DeployError):
        tool.host_routes(lambda: table)


def test_missing_route_source_aborts(monkeypatch):
    monkeypatch.setattr(tool, "read_proc_routes", lambda: (_ for _ in ()).throw(tool.DeployError("cannot read")))
    with pytest.raises(tool.DeployError):
        tool.host_routes(tool.read_proc_routes)


def test_every_overlap_with_networks_or_routes_is_reported(tmp_path):
    import ipaddress

    env = make_env(tmp_path)
    net = ipaddress.ip_network
    networks = [("bridge", "1" * 64, net("172.17.0.0/16")), ("supabase", "2" * 64, net("172.29.0.0/16")),
                ("mcma-central-net", "abcdef123456" + "0" * 52, net("172.29.211.0/28"))]
    routes = [("eth0", net("192.168.11.0/24")), ("wg0", net("172.29.211.8/29")),
              ("br-abcdef123456", net("172.29.211.0/28"))]                 # MCMA's own bridge route
    found = tool.subnet_conflicts(env, networks, routes)
    assert len(found) == 2
    assert any("supabase" in f for f in found) and any("wg0" in f for f in found)
    assert not any("br-abcdef123456" in f or "mcma-central-net" in f for f in found)
    assert tool.subnet_conflicts(env, networks[:1], routes[:1]) == []


# ------------------------------- 4. identity ------------------------------------ #


def test_identity_is_fixed_everywhere():
    assert (tool.PROJECT, tool.CONTAINER_NAME, tool.IMAGE_REPO) == ("mcma-central",) * 3
    compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert "name: mcma-central\n" in compose and "container_name: mcma-central" in compose
    assert "image: mcma-central:${MCMA_IMAGE_TAG" in compose and "${MCMA_IMAGE}" not in compose
    for name in ("env.vm.example", "env.production.example"):
        env = tool.parse_env(DEPLOY / name)
        assert env["MCMA_PROJECT"] == "mcma-central" and env["MCMA_IMAGE"] == "mcma-central"
    assert tool.parse_env(DEPLOY / "env.production.example")["MCMA_ALLOW_BUILD"] == "false"
    assert tool.parse_env(DEPLOY / "env.vm.example")["MCMA_ALLOW_BUILD"] == "true"


def _inspect_json(tag, *, project="mcma-central", status="healthy", running=True, image=None):
    return json.dumps([{
        "Config": {"Image": image or f"mcma-central:{tag}", "Labels": {"com.docker.compose.project": project}},
        "State": {"Running": running, "Health": {"Status": status}},
    }])


def test_wait_healthy_checks_the_exact_container(monkeypatch):
    def with_inspect(payload):
        monkeypatch.setattr(tool, "_docker", lambda *a, **k: payload)

    with_inspect(_inspect_json("t1"))
    assert tool.wait_healthy("t1")[0].startswith("healthy")
    with_inspect(_inspect_json("t1", project="rma"))
    with pytest.raises(tool.DeployError, match="not part of"):
        tool.wait_healthy("t1")
    with_inspect(_inspect_json("t1", image="postgres:17"))
    with pytest.raises(tool.DeployError, match="expected mcma-central:t1"):
        tool.wait_healthy("t1")
    with_inspect(_inspect_json("t1", status="unhealthy"))
    with pytest.raises(tool.DeployError, match="unhealthy"):
        tool.wait_healthy("t1")
    with_inspect(_inspect_json("t1", running=False))
    with pytest.raises(tool.DeployError, match="not running"):
        tool.wait_healthy("t1")
    with_inspect("not json")
    with pytest.raises(tool.DeployError, match="unusable"):
        tool.wait_healthy("t1")


def test_wait_healthy_waits_then_times_out(monkeypatch):
    states = iter(["starting", "starting", "healthy"])
    monkeypatch.setattr(tool, "_docker", lambda *a, **k: _inspect_json("t", status=next(states)))
    ticks = {"now": 0.0}
    sleeps = []
    result = tool.wait_healthy("t", sleep=lambda s: sleeps.append(s) or ticks.__setitem__("now", ticks["now"] + s),
                               clock=lambda: ticks["now"])
    assert result and len(sleeps) == 2
    monkeypatch.setattr(tool, "_docker", lambda *a, **k: _inspect_json("t", status="starting"))
    ticks["now"] = 0.0
    with pytest.raises(tool.DeployError, match="did not become healthy"):
        tool.wait_healthy("t", timeout=10, interval=5,
                          sleep=lambda s: ticks.__setitem__("now", ticks["now"] + s), clock=lambda: ticks["now"])


# ------------------------------ 5. rollback ------------------------------------- #


class Recorder:
    def __init__(self, monkeypatch, tmp_path, *, check_ok=True, compose_fail_for=(), unhealthy_tags=()):
        self.env_file = tmp_path / "e.env"
        self.env_file.write_text(
            "MCMA_PROJECT=mcma-central\nMCMA_IMAGE=mcma-central\nMCMA_IMAGE_TAG=v1\n", encoding="utf-8")
        self.events = []
        self.compose_fail_for, self.unhealthy_tags = set(compose_fail_for), set(unhealthy_tags)
        monkeypatch.setattr(tool, "_docker", lambda *a, **k: self.events.append(("docker", a)) or "")
        monkeypatch.setattr(tool, "cmd_check", lambda env, **k: self._check(env, check_ok))
        monkeypatch.setattr(tool, "_compose", self._compose)
        monkeypatch.setattr(tool, "wait_healthy", self._wait)

    def tag(self):
        return tool.parse_env(self.env_file)["MCMA_IMAGE_TAG"]

    def _check(self, env, ok):
        self.events.append(("check", env["MCMA_IMAGE_TAG"]))
        if not ok:
            raise tool.DeployError("preflight failed")
        return []

    def _compose(self, env_file, *args, **kwargs):
        current = self.tag()
        self.events.append(("compose", current))
        if current in self.compose_fail_for:
            raise tool.DeployError("compose failed")
        return ""

    def _wait(self, tag, **kwargs):
        self.events.append(("wait", tag))
        if tag in self.unhealthy_tags:
            raise tool.DeployError("reports unhealthy")
        return [f"healthy ({tag})"]


def test_rollback_success_is_reported_only_after_health(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path)
    lines = tool.cmd_rollback(rec.env_file, "v0")
    assert rec.tag() == "v0"
    assert [e for e in rec.events if e[0] in ("check", "compose", "wait")] == [
        ("check", "v0"), ("compose", "v0"), ("wait", "v0")]
    assert "healthy" in lines[0] and any("NOT rolled back" in l for l in lines)


def test_rollback_restores_the_previous_tag_when_preflight_fails(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path, check_ok=False)
    with pytest.raises(tool.DeployError, match="preflight failed") as info:
        tool.cmd_rollback(rec.env_file, "v0")
    assert rec.tag() == "v1"
    assert not [e for e in rec.events if e[0] == "compose"]                # nothing was started
    assert any("env tag restored to v1" in p for p in info.value.problems)


def test_rollback_restores_the_previous_tag_when_compose_fails(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path, compose_fail_for={"v0"})
    with pytest.raises(tool.DeployError, match="compose failed") as info:
        tool.cmd_rollback(rec.env_file, "v0")
    assert rec.tag() == "v1"
    assert ("wait", "v1") in rec.events                                    # previous image converged + verified
    assert any("healthy again" in p for p in info.value.problems)


def test_rollback_restores_the_previous_tag_when_health_fails(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path, unhealthy_tags={"v0"})
    with pytest.raises(tool.DeployError, match="unhealthy") as info:
        tool.cmd_rollback(rec.env_file, "v0")
    assert rec.tag() == "v1"
    assert rec.events.count(("compose", "v1")) == 1 and ("wait", "v1") in rec.events
    assert any("data was not touched" in p for p in info.value.problems)


def test_rollback_reports_when_even_the_previous_image_is_not_healthy(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path, unhealthy_tags={"v0", "v1"})
    with pytest.raises(tool.DeployError) as info:
        tool.cmd_rollback(rec.env_file, "v0")
    assert rec.tag() == "v1"
    assert any("could not confirm the previous image v1" in p for p in info.value.problems)


def test_rollback_refuses_a_missing_image_and_a_no_op(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path)
    with pytest.raises(tool.DeployError, match="already on"):
        tool.cmd_rollback(rec.env_file, "v1")
    monkeypatch.setattr(tool, "_docker", lambda *a, **k: (_ for _ in ()).throw(tool.DeployError("no such image")))
    with pytest.raises(tool.DeployError, match="no such image"):
        tool.cmd_rollback(rec.env_file, "v0")
    assert rec.tag() == "v1"                                               # env untouched
    with pytest.raises(tool.DeployError, match="invalid image tag"):
        tool.cmd_rollback(rec.env_file, "bad tag")


def test_up_reports_success_only_after_health(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path, unhealthy_tags={"v1"})
    with pytest.raises(tool.DeployError, match="unhealthy"):
        tool.cmd_up(rec.env_file)
    ok = Recorder(monkeypatch, tmp_path)
    assert tool.cmd_up(ok.env_file)[-1] == "started and healthy"


# ------------------------- 6. image verification -------------------------------- #


def test_verify_image_runs_dpkg_audit_and_a_navigation_test_under_production_flags(monkeypatch):
    calls = []

    def fake(*args, **kwargs):
        calls.append(args)
        if args[0] == "run" and "--entrypoint" in args and args[args.index("--entrypoint") + 1] == "sh":
            return "AUDIT_DONE\n"
        if args[0] == "run":
            return "NAVIGATION_OK\n"
        return ""

    monkeypatch.setattr(tool, "_docker", fake)
    tool.cmd_verify_image("t9")
    audit, nav = [c for c in calls if c[0] == "run"]
    assert "dpkg --audit" in audit[-1]
    for flag in ("--read-only", "--network", "none", "no-new-privileges:true", "--user", "10001:10001"):
        assert flag in nav
    assert nav[nav.index("--cap-drop") + 1] == "ALL" and "mcma-central:t9" in nav
    assert "chromium.launch(headless=True)" in nav[-1] and "page.goto" in nav[-1]


def test_verify_image_fails_on_a_dirty_audit_or_a_failed_navigation(monkeypatch):
    monkeypatch.setattr(tool, "_docker", lambda *a, **k: "dpkg: error: something broken\nAUDIT_DONE\n")
    with pytest.raises(tool.DeployError, match="dpkg --audit reports problems"):
        tool.cmd_verify_image("t")

    def nav_fails(*args, **kwargs):
        return "AUDIT_DONE\n" if "sh" in args else "no marker\n"

    monkeypatch.setattr(tool, "_docker", nav_fails)
    with pytest.raises(tool.DeployError, match="navigation"):
        tool.cmd_verify_image("t")


# ------------------------- 7. immutable image delivery -------------------------- #


def _write_archive(tmp_path, ref="mcma-central:t1", *, tags=None, sha=None):
    """A minimal docker-save-shaped archive plus its sidecar files."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        data = json.dumps([{"Config": "c.json", "RepoTags": tags if tags is not None else [ref], "Layers": []}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    archive = tmp_path / f"mcma-central-{ref.split(':')[1]}.tar.gz"
    archive.write_bytes(gzip.compress(raw.getvalue()))
    digest = sha or hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(f"{archive}.sha256").write_text(f"{digest}  {archive.name}\n")
    Path(f"{archive}.image-id").write_text(f"sha256:{'a' * 64}\n{ref}\n")
    return archive


def test_import_rejects_checksum_mismatch_before_loading_anything(monkeypatch, tmp_path):
    loaded = []
    monkeypatch.setattr(tool.subprocess, "Popen", lambda *a, **k: loaded.append(a) or (_ for _ in ()).throw(AssertionError))
    archive = _write_archive(tmp_path)
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(tool.DeployError, match="SHA-256 mismatch"):
        tool.cmd_import_image(archive)
    assert loaded == []


@pytest.mark.parametrize("break_it", ["no-sha", "bad-sha-file", "wrong-name", "no-id-file", "bad-id"])
def test_import_rejects_missing_or_malformed_sidecars(tmp_path, break_it):
    archive = _write_archive(tmp_path)
    sha, idf = Path(f"{archive}.sha256"), Path(f"{archive}.image-id")
    if break_it == "no-sha":
        sha.unlink()
    elif break_it == "bad-sha-file":
        sha.write_text("nothex  file\n")
    elif break_it == "wrong-name":
        sha.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  other.tar.gz\n")
    elif break_it == "no-id-file":
        idf.unlink()
    elif break_it == "bad-id":
        idf.write_text("nonsense\npostgres:17\n")
    with pytest.raises(tool.DeployError):
        tool.cmd_import_image(archive)


def test_import_refuses_an_archive_holding_any_other_image(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_docker", lambda *a, **k: "")
    for tags in (["postgres:17"], ["mcma-central:t1", "postgres:17"], [], ["mcma-central:other"]):
        with pytest.raises(tool.DeployError, match="expected exactly"):
            tool.cmd_import_image(_write_archive(tmp_path, tags=tags))


def test_import_refuses_to_replace_an_existing_tag_with_a_different_image(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_docker", lambda *a, **k: f"mcma-central:t1\tsha256:{'b' * 64}\n")
    with pytest.raises(tool.DeployError, match="immutable"):
        tool.cmd_import_image(_write_archive(tmp_path))


@needs_docker
def test_real_export_import_round_trip_verifies_checksum_and_image_id(tmp_path):
    """Builds a tiny image under the dedicated repository name, exports it,
    removes the local tag, imports the archive and verifies the image id."""
    tag = "pytest-" + uuid.uuid4().hex[:8]
    ref = f"mcma-central:{tag}"
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text(f"FROM scratch\nLABEL mcma.test={tag}\n")
    try:
        built = subprocess.run(["docker", "build", "-q", "-t", ref, str(ctx)], capture_output=True, text=True, timeout=300)
        if built.returncode != 0:
            pytest.skip("docker daemon unavailable for a real build: " + built.stderr[-200:])
        original_id = tool._image_id(ref)

        out = tmp_path / "out"
        tool.cmd_export_image(tag, out)
        archive = out / f"mcma-central-{tag}.tar.gz"
        assert (out / f"{archive.name}.sha256").read_text().split()[0] == hashlib.sha256(archive.read_bytes()).hexdigest()
        assert (out / f"{archive.name}.image-id").read_text().split() == [original_id, ref]
        with pytest.raises(tool.DeployError, match="already exists"):
            tool.cmd_export_image(tag, out)                                # immutable

        tampered = tmp_path / "t" / archive.name
        tampered.parent.mkdir()
        shutil.copy(archive, tampered)
        shutil.copy(f"{archive}.sha256", f"{tampered}.sha256")
        shutil.copy(f"{archive}.image-id", f"{tampered}.image-id")
        tampered.write_bytes(tampered.read_bytes()[:-8] + b"XXXXXXXX")
        with pytest.raises(tool.DeployError, match="SHA-256 mismatch"):
            tool.cmd_import_image(tampered)

        subprocess.run(["docker", "rmi", ref], capture_output=True, timeout=120, check=True)
        lines = tool.cmd_import_image(archive)
        assert lines[-1] == f"image id verified: {original_id}" and tool._image_id(ref) == original_id
        assert tool.cmd_import_image(archive)[0] == f"loaded {ref}"        # re-import of the same image is fine
    finally:
        subprocess.run(["docker", "rmi", "-f", ref], capture_output=True, timeout=120)


# ------------------------- 8. restore manifest validation ----------------------- #


def _stage(tmp_path, files, manifest=None, extra=None):
    stage = tmp_path / f"stage-{uuid.uuid4().hex[:6]}"
    (stage / "db").mkdir(parents=True)
    for rel, data in files.items():
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    listed = {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}
    document = manifest if manifest is not None else {"sha256": listed}
    (stage / "MANIFEST.json").write_text(document if isinstance(document, str) else json.dumps(document))
    for rel, data in (extra or {}).items():
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return stage


GOOD = {"db/mcma.sqlite3": b"db", "vault/a.session": b"v"}


def test_a_complete_manifest_is_accepted(tmp_path):
    assert set(tool.load_manifest(_stage(tmp_path, GOOD))) == set(GOOD)


def test_files_not_listed_in_the_manifest_are_rejected(tmp_path):
    with pytest.raises(tool.DeployError, match="not listed"):
        tool.load_manifest(_stage(tmp_path, GOOD, extra={"vault/sneaky.session": b"x"}))


def test_a_manifest_naming_a_missing_file_is_rejected(tmp_path):
    files = dict(GOOD)
    stage = _stage(tmp_path, files, manifest={"sha256": {**{k: hashlib.sha256(v).hexdigest() for k, v in files.items()},
                                                          "vault/ghost.session": "0" * 64}})
    with pytest.raises(tool.DeployError, match="missing from the archive"):
        tool.load_manifest(stage)


@pytest.mark.parametrize("bad_path", ["/etc/passwd", "../escape", "vault/../../escape", "vault\\..\\x", "", ".",
                                      "outside/file", "./vault/a.session"])
def test_unsafe_manifest_paths_are_rejected(tmp_path, bad_path):
    stage = _stage(tmp_path, GOOD, manifest={"sha256": {"db/mcma.sqlite3": hashlib.sha256(b"db").hexdigest(),
                                                         bad_path: "0" * 64}})
    with pytest.raises(tool.DeployError, match="unsafe path"):
        tool.load_manifest(stage)


@pytest.mark.parametrize("document", [
    "not json", "[]", "{}", '{"sha256": []}', '{"sha256": {}}', '{"sha256": "x"}', '{"other": 1}', "null",
    '{"sha256": {"db/mcma.sqlite3": 5}}', '{"sha256": {"db/mcma.sqlite3": "short"}}',
])
def test_malformed_manifests_are_rejected(tmp_path, document):
    with pytest.raises(tool.DeployError):
        tool.load_manifest(_stage(tmp_path, GOOD, manifest=document))


def test_a_manifest_without_the_database_or_with_a_bad_checksum_is_rejected(tmp_path):
    only_vault = {"vault/a.session": b"v"}
    with pytest.raises(tool.DeployError, match="db/mcma.sqlite3"):
        tool.load_manifest(_stage(tmp_path, only_vault))
    stage = _stage(tmp_path, GOOD)
    (stage / "vault" / "a.session").write_bytes(b"changed")
    with pytest.raises(tool.DeployError, match="integrity"):
        tool.load_manifest(stage)


def test_a_missing_manifest_is_rejected(tmp_path):
    stage = _stage(tmp_path, GOOD)
    (stage / "MANIFEST.json").unlink()
    with pytest.raises(tool.DeployError, match="no MANIFEST.json"):
        tool.load_manifest(stage)


# --------------------------- 10. documentation ---------------------------------- #


def test_docs_do_not_send_other_computers_to_a_vm_local_path():
    doc = (DEPLOY.parents[1] / "docs" / "architecture" / "CENTRAL_SERVER_DEPLOYMENT.md").read_text(encoding="utf-8")
    docker_part = doc.split("# Docker deployment")[1]
    assert "show-cert" in docker_part and "fingerprint" in docker_part.lower()
    for line in docker_part.splitlines():
        if line.strip().startswith("curl") and "--cacert" in line:
            assert "/data/mcma" not in line, line
    assert "import-image" in docker_part and "docker load" in docker_part and "MCMA_ALLOW_BUILD" in docker_part


# ------------------------- atomic env-file update (set-tag) --------------------- #


def _env_file(tmp_path, mode=None):
    path = tmp_path / "mcma.env"
    path.write_bytes(b"MCMA_PROJECT=mcma-central\nSECRET_LOOKING=hunter2\nMCMA_IMAGE_TAG=old\n")
    if mode is not None and os.name == "posix":
        os.chmod(path, mode)
    return path


def _no_temp_left(directory):
    return [p.name for p in directory.iterdir() if p.name.startswith(".mcma-env.")] == []


def test_set_tag_replaces_atomically_and_leaves_no_temp_file(tmp_path):
    path = _env_file(tmp_path)
    tool.cmd_set_tag(path, "new-1")
    assert path.read_bytes() == b"MCMA_PROJECT=mcma-central\nSECRET_LOOKING=hunter2\nMCMA_IMAGE_TAG=new-1\n"
    assert _no_temp_left(tmp_path)
    tool.cmd_set_tag(path, "new-2")
    assert path.read_bytes().endswith(b"MCMA_IMAGE_TAG=new-2\n")


def test_set_tag_appends_when_the_key_is_absent(tmp_path):
    path = tmp_path / "e.env"
    path.write_bytes(b"MCMA_PROJECT=mcma-central\n")
    tool.cmd_set_tag(path, "t1")
    assert path.read_bytes() == b"MCMA_PROJECT=mcma-central\n\nMCMA_IMAGE_TAG=t1\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.parametrize("mode", [0o600, 0o640, 0o644, 0o400])
def test_set_tag_preserves_the_original_mode(tmp_path, mode):
    path = _env_file(tmp_path, mode)
    before = path.stat()
    tool.cmd_set_tag(path, "new")
    after = path.stat()
    assert after.st_mode & 0o7777 == mode
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership")
def test_set_tag_never_silently_changes_ownership(tmp_path, monkeypatch):
    """If the original's owner cannot be reproduced, refuse instead of
    replacing the file with one owned by somebody else."""
    path = _env_file(tmp_path)
    original = path.read_bytes()
    real_stat = os.stat

    class Foreign:
        def __init__(self, st):
            self.st_mode, self.st_uid, self.st_gid = st.st_mode, st.st_uid + 1, st.st_gid

    monkeypatch.setattr(tool.os, "stat", lambda p, *a, **k: Foreign(real_stat(p, *a, **k)) if str(p) == str(path) else real_stat(p, *a, **k))
    if os.geteuid() == 0:
        pytest.skip("root can chown; the refusal path needs an unprivileged user")
    with pytest.raises(tool.DeployError, match="original is unchanged"):
        tool.cmd_set_tag(path, "new")
    assert path.read_bytes() == original and _no_temp_left(tmp_path)


@pytest.mark.parametrize("failing", ["write", "fsync", "replace"])
def test_a_failure_before_the_rename_leaves_the_original_byte_for_byte(tmp_path, monkeypatch, failing):
    path = _env_file(tmp_path, 0o640)
    original = path.read_bytes()

    def boom(*args, **kwargs):
        raise OSError(28, "No space left on device: hunter2")

    monkeypatch.setattr(tool.os, failing, boom)
    with pytest.raises(tool.DeployError, match="original is unchanged") as info:
        tool.cmd_set_tag(path, "new")
    assert path.read_bytes() == original
    assert _no_temp_left(tmp_path)
    assert "hunter2" not in str(info.value) and "No space" not in str(info.value)   # no contents / OS text


def test_a_partial_write_is_completed_or_fails_cleanly(tmp_path, monkeypatch):
    path = _env_file(tmp_path)
    real_write = os.write
    monkeypatch.setattr(tool.os, "write", lambda fd, data: real_write(fd, bytes(data)[:5]))   # short writes
    tool.cmd_set_tag(path, "short-writes")
    assert path.read_bytes().endswith(b"MCMA_IMAGE_TAG=short-writes\n")
    assert _no_temp_left(tmp_path)


def test_an_unreadable_env_file_is_a_deploy_error_without_contents(tmp_path):
    with pytest.raises(tool.DeployError, match="cannot be read"):
        tool.cmd_set_tag(tmp_path / "missing.env", "t")


@pytest.mark.skipif(os.name != "posix", reason="parent-directory fsync is POSIX only")
def test_the_parent_directory_is_fsynced_after_the_replace(tmp_path, monkeypatch):
    path = _env_file(tmp_path)
    synced = []
    real_fsync, real_open = os.fsync, os.open
    dir_fds = set()

    def spy_open(p, flags, *a, **k):
        fd = real_open(p, flags, *a, **k)
        if os.path.isdir(p):
            dir_fds.add(fd)
        return fd

    monkeypatch.setattr(tool.os, "open", spy_open)
    monkeypatch.setattr(tool.os, "fsync", lambda fd: synced.append(fd in dir_fds) or real_fsync(fd))
    tool.cmd_set_tag(path, "new")
    assert synced == [False, True]                       # the file first, then its directory


@pytest.mark.skipif(os.name != "posix", reason="parent-directory fsync is POSIX only")
def test_a_directory_fsync_failure_after_the_replace_is_reported_honestly(tmp_path, monkeypatch):
    path = _env_file(tmp_path)
    real_fsync = os.fsync
    calls = []

    def flaky(fd):
        calls.append(fd)
        if len(calls) == 2:                                # the directory sync
            raise OSError(5, "io")
        return real_fsync(fd)

    monkeypatch.setattr(tool.os, "fsync", flaky)
    with pytest.raises(tool.DeployError, match="was replaced but its directory could not be synced"):
        tool.cmd_set_tag(path, "new")
    assert path.read_bytes().endswith(b"MCMA_IMAGE_TAG=new\n") and _no_temp_left(tmp_path)


def test_rollback_does_not_claim_a_restore_that_failed(monkeypatch, tmp_path):
    rec = Recorder(monkeypatch, tmp_path, compose_fail_for={"v0"})
    real_write = tool._atomic_write

    def fail_when_restoring(target, data):
        if b"MCMA_IMAGE_TAG=v1" in data:
            raise tool.DeployError("could not be updated safely; the original is unchanged")
        return real_write(target, data)

    monkeypatch.setattr(tool, "_atomic_write", fail_when_restoring)
    with pytest.raises(tool.DeployError) as info:
        tool.cmd_rollback(rec.env_file, "v0")
    text = " | ".join(info.value.problems)
    assert "could NOT restore the env tag to v1" in text and "set-tag v1" in text
    assert "env tag restored" not in text and "healthy again" not in text
    assert rec.tag() == "v0"                                             # what the file really says
    assert rec.events.count(("compose", "v0")) == 1 and ("compose", "v1") not in rec.events   # no second compose
