import pytest
from pathlib import Path

from mcma.app.workstation_runner.config import (
    ConfigError, build_config, validate_server_origin, validate_workstation_label,
)


@pytest.mark.parametrize("raw,expected", [
    ("https://central.example.local", "https://central.example.local"),
    ("https://central.example.local/", "https://central.example.local"),
    ("https://central.example.local:8443", "https://central.example.local:8443"),
])
def test_validate_server_origin_accepts_bare_https_origin(raw, expected):
    assert validate_server_origin(raw) == expected


@pytest.mark.parametrize("raw", [
    "http://central.example.local",                       # not https
    "https://user:pass@central.example.local",             # embedded credentials
    "https://central.example.local/runner",                # unexpected path
    "https://central.example.local?x=1",                   # query string
    "https://central.example.local#frag",                  # fragment
    "not a url",
    "",
    "ftp://central.example.local",
    "https://central.example.local:99999",   # port out of range -- urlsplit(...).port raises ValueError lazily
    "https://central.example.local:notaport",
])
def test_validate_server_origin_rejects_everything_else(raw):
    with pytest.raises(ConfigError):
        validate_server_origin(raw)


def test_validate_workstation_label_trims_and_accepts():
    assert validate_workstation_label(" Poste-1 ") == "Poste-1"


@pytest.mark.parametrize("raw", ["", "   ", "x" * 41, "bad;label"])
def test_validate_workstation_label_rejects_invalid(raw):
    with pytest.raises(ConfigError):
        validate_workstation_label(raw)


def test_build_config_accepts_missing_ca_cert():
    cfg = build_config(server_origin="https://central.example.local", ca_cert_path=None, workstation_label="Poste-1")
    assert cfg.server_origin == "https://central.example.local"
    assert cfg.ca_cert_path is None
    assert cfg.workstation_label == "Poste-1"


def test_build_config_rejects_nonexistent_ca_cert(tmp_path: Path):
    with pytest.raises(ConfigError):
        build_config(
            server_origin="https://central.example.local",
            ca_cert_path=tmp_path / "missing.pem",
            workstation_label="Poste-1",
        )
