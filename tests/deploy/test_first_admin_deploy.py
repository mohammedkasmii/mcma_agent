"""`mcma-deploy.sh create-first-admin`: the throw-away container command and
its refusals. Docker is faked; nothing is started."""

import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "central"


def _load_tool():
    spec = importlib.util.spec_from_file_location("deploytool_admin", DEPLOY / "deploytool.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploytool_admin"] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

ENV = {
    "MCMA_PROJECT": "mcma-central", "MCMA_DATA_ROOT": "/data/mcma-dev", "MCMA_BIND_ADDRESS": "192.168.11.111",
    "MCMA_HTTPS_PORT": "18443", "MCMA_NET_SUBNET": "172.29.211.0/28", "MCMA_CONTAINER_IP": "172.29.211.2",
    "MCMA_TLS_SERVER_NAME": "192.168.11.111", "MCMA_UID": "10001", "MCMA_GID": "10001",
    "MCMA_IMAGE": "mcma-central", "MCMA_IMAGE_TAG": "20260927-abc",
}


def _pairs(argv):
    return {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("-")}


def test_the_docker_command_is_network_less_unprivileged_and_mounts_only_the_database():
    argv = tool.first_admin_argv(ENV, "boss", tty=True)
    assert argv[:2] == ["docker", "run"] and "--rm" in argv and "-i" in argv and "-t" in argv
    assert _pairs(argv)["--network"] == "none"
    assert not {"-p", "--publish", "-P", "--publish-all"} & set(argv)
    assert "--read-only" in argv and _pairs(argv)["--cap-drop"] == "ALL"
    assert _pairs(argv)["--security-opt"] == "no-new-privileges:true"
    assert "--privileged=false" in argv and "--privileged" not in argv
    assert _pairs(argv)["--user"] == "10001:10001"
    assert _pairs(argv)["--memory"] and _pairs(argv)["--pids-limit"]
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a in ("--mount", "-v", "--volume")]
    assert mounts == ["type=bind,source=/data/mcma-dev/db,target=/var/lib/mcma/data"]     # read-write, database only
    assert "readonly" not in mounts[0] and ",ro" not in mounts[0]
    assert argv[argv.index("--entrypoint") + 1] == "python"
    assert "mcma-central:20260927-abc" in argv
    assert argv[-4:] == ["-m", "mcma.app.first_admin_cli", "--", "boss"]


def test_no_unrelated_secrets_or_sockets_are_mounted_or_passed():
    argv = tool.first_admin_argv(ENV, "boss", tty=False)
    text = " ".join(argv)
    for forbidden in ("keys", "tls", "vault", "config", "session-vault", "job-input", "server.key", "docker.sock",
                      "/etc/mcma", "host"):
        assert forbidden not in text, forbidden
    assert not {"--env-file", "--volumes-from", "--pid", "--device", "--ipc", "--uts", "--cap-add"} & set(argv)
    envs = [a for a in tool.first_admin_argv(ENV, "boss", tty=False) if "=" in a and a.startswith("MCMA_")]
    assert sorted(envs) == ["MCMA_DB_PATH=/var/lib/mcma/data/mcma.sqlite3",
                            "MCMA_INSTANCE_LOCK_PATH=/var/lib/mcma/data/mcma.lock"]


def test_without_a_terminal_no_tty_flag_is_requested():
    argv = tool.first_admin_argv(ENV, "boss", tty=False)
    assert "-i" in argv and "-t" not in argv


def test_no_password_can_reach_the_command_line_or_environment():
    assert list(inspect.signature(tool.first_admin_argv).parameters) == ["env", "username", "tty"]
    assert list(inspect.signature(tool.cmd_create_first_admin).parameters) == ["env", "username"]
    secret = "S3cret-phrase-value"
    argv = tool.first_admin_argv(ENV, "boss", tty=True)
    assert secret not in " ".join(argv) and not any("PASS" in a.upper() for a in argv)
    for option in (["--password", secret], [f"--password={secret}"]):
        with pytest.raises(SystemExit):                                        # the CLI has no such option
            tool.main(["--env-file", "x.env", "create-first-admin", "boss", *option])


@pytest.fixture()
def wired(monkeypatch):
    """Everything host-side faked; records what would have been executed."""
    calls = {"docker": [], "interactive": []}
    monkeypatch.setattr(tool, "validate_env", lambda env: [])
    monkeypatch.setattr(tool, "require_owned_root", lambda env: Path("/data/mcma-dev"))
    monkeypatch.setattr(tool, "marker_problem", lambda root: "skip")
    monkeypatch.setattr(tool, "_run_interactive", lambda argv: calls["interactive"].append(argv) or calls.get("exit", 0))
    state = {"ps": ""}

    def fake_docker(*args, **kwargs):
        calls["docker"].append(args)
        if args[0] == "ps":
            return state["ps"]
        return ""

    monkeypatch.setattr(tool, "_docker", fake_docker)
    calls["state"] = state
    return calls


def test_it_refuses_while_the_application_is_running_and_launches_nothing(wired):
    for running in ("mcma-central\trunning\n", "mcma-central\trestarting\n", "mcma-central\tpaused\n"):
        wired["state"]["ps"] = running
        with pytest.raises(tool.DeployError, match="running"):
            tool.cmd_create_first_admin(ENV, "boss")
    assert wired["interactive"] == []


def test_it_refuses_when_docker_cannot_confirm_the_container_is_stopped(monkeypatch, wired):
    def unavailable(*args, **kwargs):
        raise tool.DeployError("docker did not answer within 30s")

    monkeypatch.setattr(tool, "_docker", unavailable)
    with pytest.raises(tool.DeployError, match="did not answer"):
        tool.cmd_create_first_admin(ENV, "boss")
    assert wired["interactive"] == []


@pytest.mark.parametrize("ps", ["", "mcma-central\texited\n", "mcma-central\tcreated\n"])
def test_it_proceeds_when_the_container_is_stopped_or_absent(wired, ps, tmp_path, monkeypatch):
    wired["state"]["ps"] = ps
    monkeypatch.setattr(tool.Path, "is_dir", lambda self: True)
    lines = tool.cmd_create_first_admin(ENV, "boss")
    assert lines and len(wired["interactive"]) == 1
    argv = wired["interactive"][0]
    assert argv[:2] == ["docker", "run"] and _pairs(argv)["--network"] == "none"
    assert ("image", "inspect", "mcma-central:20260927-abc") in wired["docker"]


def test_a_missing_image_aborts_before_running_anything(monkeypatch, wired):
    def fake(*args, **kwargs):
        if args[0] == "image":
            raise tool.DeployError("docker failed (docker image, exit 1): No such image")
        return ""

    monkeypatch.setattr(tool, "_docker", fake)
    monkeypatch.setattr(tool.Path, "is_dir", lambda self: True)
    with pytest.raises(tool.DeployError, match="No such image"):
        tool.cmd_create_first_admin(ENV, "boss")
    assert wired["interactive"] == []


def test_a_failed_container_run_is_reported_as_failure(wired, monkeypatch):
    monkeypatch.setattr(tool.Path, "is_dir", lambda self: True)
    monkeypatch.setattr(tool, "_run_interactive", lambda argv: 1)
    with pytest.raises(tool.DeployError, match="did not create an administrator"):
        tool.cmd_create_first_admin(ENV, "boss")


@pytest.mark.parametrize("name", ["", "ab", "-rf", "a;b", "$(x)", "x" * 33, "bad" + chr(10) + "name", "with space", "a@b.c", "abc" + chr(10), ".dot", "é-é"])
def test_hostile_usernames_never_reach_docker(wired, name):
    with pytest.raises(tool.DeployError):
        tool.cmd_create_first_admin(ENV, name)
    assert wired["interactive"] == []


@pytest.mark.parametrize("name", ["abc", "Boss", "a.b-c_d", "x" * 32, "9lives"])
def test_usernames_the_backend_accepts_are_accepted_host_side(wired, name, monkeypatch):
    wired["state"]["ps"] = ""
    monkeypatch.setattr(tool.Path, "is_dir", lambda self: True)
    assert tool.cmd_create_first_admin(ENV, name)


def test_the_host_side_error_message_states_the_real_policy(wired):
    with pytest.raises(tool.DeployError) as info:
        tool.cmd_create_first_admin(ENV, "a@b")
    assert "3 à 32 caractères" in str(info.value)
    assert "commençant par une lettre ou un chiffre" in str(info.value)


def test_the_shell_wrapper_exposes_the_command_and_never_takes_a_password():
    text = (DEPLOY / "mcma-deploy.sh").read_text(encoding="utf-8")
    assert "create-first-admin)" in text and 'tool create-first-admin "$1"' in text
    assert "[[ $# -eq 1 ]]" in text.split("create-first-admin)")[1].split(";;")[0]
    body = text.split("create-first-admin)")[1].split(";;")[0]
    assert "read " not in body and "read -s" not in body and "getpass" not in body and "--password" not in body


def test_the_interactive_runner_inherits_the_terminal(monkeypatch):
    seen = {}
    monkeypatch.setattr(tool.subprocess, "run", lambda argv, **kw: seen.update(kw) or subprocess.CompletedProcess(argv, 0))
    assert tool._run_interactive(["docker", "run"]) == 0
    assert seen == {}                                   # no capture_output / stdin=PIPE: the hidden prompt works
