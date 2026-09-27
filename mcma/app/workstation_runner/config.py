"""mcma.app.workstation_runner.config -- validated local configuration for
the pairing GUI. Everything a human can type into the pairing form is
validated here before it touches the network or the filesystem."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(Exception):
    """A fixed, French-safe validation failure. The caller decides the
    exact French text shown in the GUI; this carries only a stable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$")  # mirrors registry._LABEL_RE


def validate_server_origin(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    try:
        # urlsplit() itself never raises, but .hostname and .port are lazy
        # properties that DO raise ValueError for a malformed netloc (e.g.
        # a non-numeric or out-of-range port) -- both must be inside this
        # try, not just the urlsplit() call, or a bad port would escape as
        # a raw ValueError instead of the documented ConfigError.
        parts = urlsplit(raw.strip())
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        raise ConfigError("SERVER_ORIGIN_INVALID") from None
    if parts.scheme != "https":
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if not hostname:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if parts.username or parts.password:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if parts.query or parts.fragment:
        raise ConfigError("SERVER_ORIGIN_INVALID")
    if parts.path not in ("", "/"):
        raise ConfigError("SERVER_ORIGIN_INVALID")
    netloc = hostname + (f":{port}" if port else "")
    return f"https://{netloc}"


def validate_workstation_label(raw: object) -> str:
    if not isinstance(raw, str):
        raise ConfigError("WORKSTATION_LABEL_INVALID")
    trimmed = raw.strip()
    if not _LABEL_RE.match(trimmed):
        raise ConfigError("WORKSTATION_LABEL_INVALID")
    return trimmed


@dataclass(frozen=True)
class RunnerConfig:
    server_origin: str
    ca_cert_path: Path | None
    workstation_label: str


def build_config(*, server_origin: object, ca_cert_path: object, workstation_label: object) -> RunnerConfig:
    origin = validate_server_origin(server_origin)
    label = validate_workstation_label(workstation_label)
    cert_path: Path | None = None
    if ca_cert_path:
        cert_path = Path(ca_cert_path)
        if not cert_path.is_file():
            raise ConfigError("CA_CERT_NOT_FOUND")
    return RunnerConfig(server_origin=origin, ca_cert_path=cert_path, workstation_label=label)
