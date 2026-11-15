"""deploytool: install-sinauto-client-cert, the sinauto-client layout entry,
`check` validation and backup exclusion.

Every bundle is generated at test time; no real certificate is involved.
Most end-to-end tests need POSIX (ownership, `-passin fd:N`) and openssl;
the argv/environment/no-write guarantees are also checked portably."""

import importlib.util
import inspect
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "central"
PASS = "deploy-test-passphrase-Ω"


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tool = _load("deploytool_mtls", DEPLOY / "deploytool.py")
factory = _load(
    "mcma_test_client_cert_factory", Path(__file__).resolve().parents[1] / "central" / "client_cert_factory.py",
)

posix_user = pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() < 1000),
    reason="needs POSIX and a non-root uid >= 1000 (run as an unprivileged user)",
)
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


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


def answers(*values):
    queue = list(values)
    return lambda _prompt: queue.pop(0)


@pytest.fixture
def portable(monkeypatch):
    """validate_env insists on POSIX absolute paths; the portable tests below
    exercise only what happens after it, so it is stubbed for them."""
    monkeypatch.setattr(tool, "validate_env", lambda env: [])


def _marked_root(tmp_path, env):
    """A marked data root with the sinauto-client directory, without init
    (init needs chown, which is POSIX-only)."""
    root = Path(env["MCMA_DATA_ROOT"])
    (root / tool.SINAUTO_DIR).mkdir(parents=True)
    (root / tool.MARKER).write_text(tool.MARKER_TEXT, encoding="utf-8")
    return root


def _bundle(**issue_kwargs) -> bytes:
    return factory.client_bundle(PASS, **issue_kwargs)


# ------------------------------- portable -------------------------------- #


def test_the_layout_has_the_directory_and_backups_never_include_it():
    assert tool.LAYOUT[tool.SINAUTO_DIR] == 0o700
    assert tool.SINAUTO_DIR not in tool._BACKUP_TREES
    assert "sinauto" not in inspect.getsource(tool.cmd_backup)


def test_the_cli_offers_no_way_to_pass_the_passphrase(tmp_path):
    env_file = tmp_path / "e.env"
    env_file.write_text("", encoding="utf-8")
    for extra in (["--passphrase", "x"], ["--password", "x"], ["--passphrase-file", "x"], []):
        with pytest.raises(SystemExit) as info:
            tool.main(["--env-file", str(env_file), "install-sinauto-client-cert", *extra])
        assert info.value.code == 2
    source = inspect.getsource(tool.cmd_install_sinauto_client_cert)
    assert "environ" not in source and "getenv" not in source


def test_the_shell_wrapper_takes_exactly_one_path_argument():
    text = (DEPLOY / "mcma-deploy.sh").read_text(encoding="utf-8")
    assert 'install-sinauto-client-cert)' in text
    assert '[[ $# -eq 1 ]]' in text.split("install-sinauto-client-cert)", 1)[1].split(";;", 1)[0]
    assert 'tool install-sinauto-client-cert "$1"' in text


def test_a_non_interactive_run_is_refused_before_anything_is_read(tmp_path, portable):
    env = make_env(tmp_path)
    root = _marked_root(tmp_path, env)
    with pytest.raises(tool.DeployError, match="interactive terminal"):
        tool.cmd_install_sinauto_client_cert(env, tmp_path / "absent.p12", interactive=False, prompt=answers())
    assert list((root / tool.SINAUTO_DIR).iterdir()) == []


def test_different_passphrases_write_nothing(tmp_path, portable):
    env = make_env(tmp_path)
    root = _marked_root(tmp_path, env)
    source = tmp_path / "bundle.p12"
    source.write_bytes(_bundle())
    with pytest.raises(tool.DeployError, match="do not match; nothing was written"):
        tool.cmd_install_sinauto_client_cert(env, source, interactive=True, prompt=answers(PASS, PASS + "x"))
    assert list((root / tool.SINAUTO_DIR).iterdir()) == []


def test_a_missing_directory_or_unmarked_root_is_refused(tmp_path, portable):
    env = make_env(tmp_path)
    with pytest.raises(tool.DeployError):
        tool.cmd_install_sinauto_client_cert(env, tmp_path / "x.p12", interactive=True, prompt=answers(PASS, PASS))
    root = Path(env["MCMA_DATA_ROOT"])
    root.mkdir()
    (root / tool.MARKER).write_text(tool.MARKER_TEXT, encoding="utf-8")
    with pytest.raises(tool.DeployError, match="run init first"):
        tool.cmd_install_sinauto_client_cert(env, tmp_path / "x.p12", interactive=True, prompt=answers(PASS, PASS))


def test_an_oversized_or_missing_source_is_refused(tmp_path, portable):
    env = make_env(tmp_path)
    _marked_root(tmp_path, env)
    big = tmp_path / "big.p12"
    big.write_bytes(b"\0" * (tool.SINAUTO_MAX_PFX_BYTES + 1))
    with pytest.raises(tool.DeployError, match="larger than"):
        tool.cmd_install_sinauto_client_cert(env, big, interactive=True, prompt=answers(PASS, PASS))
    with pytest.raises(tool.DeployError, match="not found"):
        tool.cmd_install_sinauto_client_cert(env, tmp_path / "nope.p12", interactive=True, prompt=answers(PASS, PASS))


@pytest.mark.parametrize(("passphrase", "expected"), [
    ("", "must not be empty"), ("a\tb", "control characters"), ("x" * 1025, "at most"),
])
def test_unacceptable_passphrases_are_refused_before_openssl_runs(monkeypatch, passphrase, expected):
    monkeypatch.setattr(tool.subprocess, "run", lambda *a, **k: pytest.fail("openssl must not run"))
    problems, metadata = tool.inspect_pkcs12(b"bundle", passphrase)
    assert expected in problems[0] and metadata == {}


def test_the_passphrase_never_appears_in_argv_or_the_environment(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 1, b"", b"error")

    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    problems, _ = tool.inspect_pkcs12(b"BUNDLE-BYTES", PASS)
    assert problems == ["the bundle could not be opened (wrong passphrase, or not a valid PKCS#12 file)"]
    assert len(calls) == 2                                  # modern, then -legacy
    for argv, kwargs in calls:
        assert PASS not in " ".join(argv)
        index = argv.index("-passin")
        assert argv[index + 1].startswith("fd:")
        assert kwargs["pass_fds"] == (int(argv[index + 1][3:]),)
        assert "env" not in kwargs
        assert kwargs["input"] == b"BUNDLE-BYTES"           # stdin carries the bundle, never the passphrase
    assert calls[1][0][:3] == ["openssl", "pkcs12", "-legacy"]


def test_openssl_dates_are_parsed():
    assert tool._openssl_date("Oct 29 10:00:00 2029 GMT") == 1887962400
    assert tool._openssl_date("Jan  2 03:04:05 2030 GMT") is not None
    assert tool._openssl_date("garbage") is None


def test_the_example_env_and_compose_hold_paths_only():
    compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert "MCMA_SINAUTO_CLIENT_PFX_PATH: /etc/mcma/sinauto-client/sinauto-client.p12" in compose
    assert "MCMA_SINAUTO_CLIENT_PASSPHRASE_PATH: /etc/mcma/sinauto-client/sinauto-client.pass" in compose
    block = compose.split("source: ${MCMA_DATA_ROOT}/sinauto-client", 1)[1].split("- type:", 1)[0]
    assert "target: /etc/mcma/sinauto-client" in block
    assert "read_only: true" in block and "create_host_path: false" in block
    for name in ("env.production.example", "env.vm.example", "Dockerfile"):
        text = (DEPLOY / name).read_text(encoding="utf-8").upper()
        assert "PASSPHRASE=" not in text and "PASSWORD=" not in text and ".P12" not in text.split("#")[0]


# --------------------------- POSIX + openssl ----------------------------- #


def _init(tmp_path, **override):
    env = make_env(tmp_path, **override)
    tool.cmd_init(env)
    return env, Path(env["MCMA_DATA_ROOT"])


@posix_user
@needs_openssl
def test_install_from_the_production_starting_state(tmp_path):
    """The bundle already sits at sinauto-client/sinauto-client.p12, 0600
    (root-owned in production; this unprivileged test cannot create a
    root-owned file). It is replaced in place by identical bytes owned by
    MCMA_UID:MCMA_GID, the passphrase file is created, and only public
    metadata is printed."""
    env, root = _init(tmp_path)
    directory = root / tool.SINAUTO_DIR
    original = _bundle(cn="client-002")
    target = directory / tool.SINAUTO_PFX
    target.write_bytes(original)
    os.chmod(target, 0o600)

    lines = tool.cmd_install_sinauto_client_cert(env, target, interactive=True, prompt=answers(PASS, PASS))

    assert target.read_bytes() == original
    secret = directory / tool.SINAUTO_PASS
    assert secret.read_bytes() == PASS.encode("utf-8")       # no trailing newline, nothing else
    for path in (target, secret):
        info = path.stat()
        assert info.st_mode & 0o777 == 0o600
        assert (info.st_uid, info.st_gid) == (int(env["MCMA_UID"]), int(env["MCMA_GID"]))
    assert directory.stat().st_mode & 0o777 == 0o700
    assert sorted(p.name for p in directory.iterdir()) == [tool.SINAUTO_PFX, tool.SINAUTO_PASS]
    text = "\n".join(lines)
    assert PASS not in text and "CN=client-002" in text and "sha256" in text
    assert "was not modified" not in text                    # source == destination

    assert tool.sinauto_client_problems(root, int(env["MCMA_UID"]), posix=True) == []

    # The installed pair satisfies the server's own loader.
    from mcma.core.client_certificate import load_sinauto_client_certificate

    certificate = load_sinauto_client_certificate(target, secret, "sinauto.mamda-mcma.ma")
    assert certificate.subject == "CN=client-002"


@posix_user
@needs_openssl
def test_ownership_comes_from_mcma_uid_and_gid(tmp_path, monkeypatch):
    env, root = _init(tmp_path)
    env = dict(env, MCMA_UID="20001", MCMA_GID="20002")
    owners = []
    monkeypatch.setattr(tool.os, "fchown", lambda fd, uid, gid: owners.append((uid, gid)))
    monkeypatch.setattr(tool.os, "chown", lambda path, uid, gid: owners.append((uid, gid)))
    source = tmp_path / "bundle.p12"
    original = _bundle()
    source.write_bytes(original)
    lines = tool.cmd_install_sinauto_client_cert(env, source, interactive=True, prompt=answers(PASS, PASS))
    assert owners and set(owners) == {(20001, 20002)}
    assert any("was not modified" in line for line in lines)  # an outside source is left alone
    assert source.read_bytes() == original


@posix_user
@needs_openssl
@pytest.mark.parametrize("case", ["wrong_passphrase", "expired", "no_client_auth", "not_pkcs12"])
def test_an_invalid_bundle_writes_nothing_and_leaves_the_existing_file(tmp_path, case):
    import datetime as dt

    env, root = _init(tmp_path)
    directory = root / tool.SINAUTO_DIR
    existing = directory / tool.SINAUTO_PFX
    existing.write_bytes(b"previous-bundle")
    os.chmod(existing, 0o600)
    now = dt.datetime.now(dt.timezone.utc)
    if case == "expired":
        bundle = _bundle(not_before=now - dt.timedelta(days=9), not_after=now - dt.timedelta(days=1))
    elif case == "no_client_auth":
        bundle = _bundle(eku=(factory.SERVER_AUTH,))
    elif case == "not_pkcs12":
        bundle = b"not a bundle"
    else:
        bundle = _bundle()
    source = tmp_path / "candidate.p12"
    source.write_bytes(bundle)
    typed = "wrong-passphrase" if case == "wrong_passphrase" else PASS
    with pytest.raises(tool.DeployError) as info:
        tool.cmd_install_sinauto_client_cert(env, source, interactive=True, prompt=answers(typed, typed))
    assert "nothing was written" in info.value.problems
    assert typed not in str(info.value) and PASS not in str(info.value)
    assert existing.read_bytes() == b"previous-bundle"
    assert sorted(p.name for p in directory.iterdir()) == [tool.SINAUTO_PFX]


@posix_user
@needs_openssl
def test_a_symlinked_source_is_refused(tmp_path):
    env, _ = _init(tmp_path)
    real = tmp_path / "real.p12"
    real.write_bytes(_bundle())
    link = tmp_path / "link.p12"
    link.symlink_to(real)
    with pytest.raises(tool.DeployError, match="symlink"):
        tool.cmd_install_sinauto_client_cert(env, link, interactive=True, prompt=answers(PASS, PASS))


@posix_user
@needs_openssl
def test_check_reports_missing_unsafe_or_wrong_client_certificate_files(tmp_path):
    env, root = _init(tmp_path)
    uid = int(env["MCMA_UID"])
    directory = root / tool.SINAUTO_DIR
    problems = tool.sinauto_client_problems(root, uid, posix=True)
    assert len(problems) == 2 and all("run install-sinauto-client-cert" in p for p in problems)

    source = tmp_path / "bundle.p12"
    source.write_bytes(_bundle())
    tool.cmd_install_sinauto_client_cert(env, source, interactive=True, prompt=answers(PASS, PASS))
    assert tool.sinauto_client_problems(root, uid, posix=True) == []

    os.chmod(directory / tool.SINAUTO_PASS, 0o644)
    assert any("must be mode 0600" in p for p in tool.sinauto_client_problems(root, uid, posix=True))
    os.chmod(directory / tool.SINAUTO_PASS, 0o600)

    (directory / tool.SINAUTO_PASS).write_bytes(b"not-the-passphrase\n")
    problems = tool.sinauto_client_problems(root, uid, posix=True)
    assert any("could not be opened" in p for p in problems)
    assert all("not-the-passphrase" not in p for p in problems)


@posix_user
@needs_openssl
def test_init_creates_the_directory_with_the_layout_mode(tmp_path):
    _, root = _init(tmp_path)
    directory = root / tool.SINAUTO_DIR
    assert directory.is_dir() and directory.stat().st_mode & 0o777 == 0o700
