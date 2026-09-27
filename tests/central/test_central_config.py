"""Central-server configuration: explicit loading and fail-closed
validation."""

import dataclasses
from pathlib import Path

import pytest

from central_test_support import central_settings
from mcma.core.central_config import (
    CentralConfigurationError,
    load_central_settings,
    repository_served_dirs,
    validate_central_settings,
)
from mcma.core.config import RuntimeMode, Settings


def test_a_valid_configuration_passes(tmp_path):
    validate_central_settings(central_settings(tmp_path))


def test_local_defaults_are_not_a_valid_central_configuration():
    with pytest.raises(CentralConfigurationError) as info:
        validate_central_settings(Settings())
    problems = " | ".join(info.value.problems)
    assert "runtime_mode" in problems and "session_vault_key_path is required" in problems


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"local_single_user_mode": True}, "local_single_user_mode"),
        ({"allow_test_plaintext_job_inputs": True}, "allow_test_plaintext_job_inputs"),
        ({"allow_test_only_session_vault": True}, "allow_test_only_session_vault"),
        ({"dev_mode": True}, "dev_mode"),
        ({"allowed_host": "127.0.0.1:8080"}, "allowed_host"),
        ({"headless_browser": False}, "headless_browser"),
        ({"runtime_mode": RuntimeMode.LOCAL_WINDOWS}, "runtime_mode"),
        ({"session_vault_key_path": None}, "session_vault_key_path is required"),
        ({"job_input_key_path": None}, "job_input_key_path is required"),
        ({"instance_lock_path": None}, "instance_lock_path is required"),
        ({"tls_cert_path": None}, "tls_cert_path is required"),
        ({"tls_key_path": None}, "tls_key_path is required"),
        ({"db_path": Path("var") / "mcma.sqlite3"}, "db_path must be an absolute path"),
        ({"vault_dir": Path("var") / "vault"}, "vault_dir must be an absolute path"),
        ({"api_host": "0.0.0.0"}, "wildcard"),
        ({"api_host": "::"}, "wildcard"),
        ({"notification_poll_interval_seconds": 0}, "poll intervals"),
    ],
)
def test_unsafe_or_missing_settings_are_refused(tmp_path, override, expected):
    with pytest.raises(CentralConfigurationError) as info:
        validate_central_settings(central_settings(tmp_path, **override))
    assert expected in " | ".join(info.value.problems)


@pytest.mark.parametrize("served", repository_served_dirs())
@pytest.mark.parametrize("name", ["db_path", "vault_dir"])
def test_database_and_vault_may_not_live_in_a_served_directory(tmp_path, served, name):
    settings = central_settings(tmp_path, **{name: served / "inner" / "x"})
    with pytest.raises(CentralConfigurationError, match="publicly served"):
        validate_central_settings(settings)


def test_extra_public_directories_are_honoured(tmp_path):
    public = tmp_path / "public"
    settings = central_settings(tmp_path, public_static_dirs=(public,), vault_dir=public / "vault")
    with pytest.raises(CentralConfigurationError, match="publicly served"):
        validate_central_settings(settings)


def test_the_two_key_files_must_differ(tmp_path):
    base = central_settings(tmp_path)
    same = dataclasses.replace(base, job_input_key_path=base.session_vault_key_path)
    with pytest.raises(CentralConfigurationError, match="different files"):
        validate_central_settings(same)


# ------------------------------- loading -------------------------------- #

_TOML = """
api_host = "10.0.0.5"
db_path = "{root}/data/mcma.sqlite3"
vault_dir = "{root}/vault"
tls_cert_path = "{root}/secrets/server.crt"
tls_key_path = "{root}/secrets/server.key"
session_vault_key_path = "{root}/secrets/session.key"
job_input_key_path = "{root}/secrets/inputs.key"
instance_lock_path = "{root}/data/mcma.lock"
notification_category_codes = ["A", "B"]
"""


def _config_file(tmp_path, extra=""):
    path = tmp_path / "mcma.toml"
    path.write_text(_TOML.format(root=tmp_path.as_posix()) + extra, encoding="utf-8")
    return path


def test_loader_reads_the_file_and_derives_central_mode(tmp_path):
    settings = load_central_settings(_config_file(tmp_path), environ={})
    assert settings.runtime_mode is RuntimeMode.CENTRAL_SERVER
    assert settings.headless_browser is True
    assert settings.local_single_user_mode is False
    assert settings.notification_category_codes == ("A", "B")
    assert not settings.allowed_host.startswith("127.")
    assert settings.db_path == Path(tmp_path.as_posix()) / "data" / "mcma.sqlite3"


def test_environment_overrides_the_file_and_finds_the_file(tmp_path):
    env = {
        "MCMA_CONFIG_FILE": str(_config_file(tmp_path)),
        "MCMA_API_PORT": "9443",
        "MCMA_NOTIFICATION_POLL_INTERVAL_SECONDS": "120",
    }
    settings = load_central_settings(environ=env)
    assert settings.api_port == 9443
    assert settings.notification_poll_interval_seconds == 120.0


def test_environment_can_supply_everything_without_a_file(tmp_path):
    env = {
        "MCMA_API_HOST": "10.0.0.5",
        "MCMA_DB_PATH": str(tmp_path / "d.sqlite3"),
        "MCMA_VAULT_DIR": str(tmp_path / "v"),
        "MCMA_TLS_CERT_PATH": str(tmp_path / "c"),
        "MCMA_TLS_KEY_PATH": str(tmp_path / "k"),
        "MCMA_SESSION_VAULT_KEY_PATH": str(tmp_path / "s.key"),
        "MCMA_JOB_INPUT_KEY_PATH": str(tmp_path / "i.key"),
        "MCMA_INSTANCE_LOCK_PATH": str(tmp_path / "l"),
    }
    assert load_central_settings(environ=env).runtime_mode is RuntimeMode.CENTRAL_SERVER


def test_missing_required_settings_are_all_reported_and_no_defaults_apply(tmp_path):
    path = tmp_path / "mcma.toml"
    path.write_text('api_host = "10.0.0.5"\n', encoding="utf-8")
    with pytest.raises(CentralConfigurationError) as info:
        load_central_settings(path, environ={})
    assert len(info.value.problems) == 7  # every other required key


def test_unknown_and_derived_keys_are_errors(tmp_path):
    with pytest.raises(CentralConfigurationError, match="unknown setting"):
        load_central_settings(_config_file(tmp_path, 'db_pth = "x"\n'), environ={})
    with pytest.raises(CentralConfigurationError, match="derived"):
        load_central_settings(_config_file(tmp_path, 'runtime_mode = "local_windows"\n'), environ={})


def test_unsafe_values_in_the_file_are_refused(tmp_path):
    with pytest.raises(CentralConfigurationError, match="local_single_user_mode"):
        load_central_settings(_config_file(tmp_path, "local_single_user_mode = true\n"), environ={})


def test_bad_types_and_missing_file_are_refused(tmp_path):
    with pytest.raises(CentralConfigurationError, match="invalid value"):
        load_central_settings(_config_file(tmp_path), environ={"MCMA_API_PORT": "not-a-number"})
    with pytest.raises(CentralConfigurationError, match="not found"):
        load_central_settings(tmp_path / "absent.toml", environ={})


def test_local_settings_are_unchanged_by_the_new_fields():
    from mcma.app.main import local_settings

    settings = local_settings()
    assert settings.runtime_mode is RuntimeMode.LOCAL_WINDOWS
    assert settings.session_vault_key_path is None and settings.job_input_key_path is None
    assert settings.local_single_user_mode is True
