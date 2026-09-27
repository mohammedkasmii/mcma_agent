"""
mcma.core.central_config -- explicit, fail-closed configuration for the
central Ubuntu server (Phase 1).

load_settings() in mcma.core.config still returns defaults and reads
nothing. That is right for tests and the local pilot and wrong for a
server, where "the defaults" would be repo-relative paths, DEV mode and
the loopback mock portal. The central server therefore has its own
deterministic loader and validator:

    load_central_settings()      TOML file (path from MCMA_CONFIG_FILE or an
                                 argument) with MCMA_<FIELD> environment
                                 overrides. Every required path must be
                                 given; unknown keys are an error, so a typo
                                 cannot silently leave a setting at its
                                 default.
    validate_central_settings()  refuses every unsafe combination and
                                 reports ALL problems at once.

Configuration holds PATHS to secrets, never secrets. Error messages name
the offending setting and never echo a value that could be sensitive.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from mcma.core.config import RuntimeMode, Settings, _is_loopback_host

CONFIG_FILE_ENV = "MCMA_CONFIG_FILE"
ENV_PREFIX = "MCMA_"

# Must be supplied explicitly -- no default is acceptable for a server.
REQUIRED_KEYS: Tuple[str, ...] = (
    "api_host",
    "db_path",
    "vault_dir",
    "tls_cert_path",
    "tls_key_path",
    "session_vault_key_path",
    "job_input_key_path",
    "instance_lock_path",
)

# Derived by the loader; the operator may not set them.
_DERIVED_KEYS = frozenset({"runtime_mode"})

_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]", "*"})


class CentralConfigurationError(Exception):
    """One or more central-server settings are missing or unsafe.
    `problems` lists every one, as fixed sentences naming the setting."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("invalid central server configuration: " + "; ".join(self.problems))


def repository_served_dirs() -> Tuple[Path, ...]:
    """Directories this repository serves to browsers: the built frontend,
    the baseline static dir and the legacy web assets."""
    root = Path(__file__).resolve().parents[2]
    return (root / "frontend" / "dist", root / "static", root / "mcma" / "web")


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        resolved = Path(path).resolve(strict=False)
        root = Path(directory).resolve(strict=False)
    except (OSError, RuntimeError):
        return True  # cannot prove it is outside -> treat as inside (fail closed)
    return resolved == root or root in resolved.parents


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(path)


def validate_central_settings(settings: Settings) -> None:
    """Raises CentralConfigurationError listing every problem, or returns
    None. Pure apart from resolving paths; touches no file contents."""
    problems: list[str] = []

    if settings.runtime_mode is not RuntimeMode.CENTRAL_SERVER:
        problems.append("runtime_mode must be central_server")
    if settings.local_single_user_mode:
        problems.append("local_single_user_mode must be disabled (it authenticates loopback callers automatically)")
    if settings.allow_test_plaintext_job_inputs:
        problems.append("allow_test_plaintext_job_inputs is test-only and must be disabled")
    if settings.allow_test_only_session_vault:
        problems.append("allow_test_only_session_vault is test-only and must be disabled")
    if settings.dev_mode:
        problems.append("dev_mode (mock-portal execution) must be disabled")
    if _is_loopback_host(settings.allowed_host):
        problems.append("allowed_host must not be a loopback/mock execution target")
    if not settings.headless_browser:
        problems.append("headless_browser must be true (a server has no display)")
    if settings.poll_interval_seconds <= 0 or settings.notification_poll_interval_seconds <= 0:
        problems.append("poll intervals must be positive")

    path_settings = {
        "db_path": settings.db_path,
        "vault_dir": settings.vault_dir,
        "session_vault_key_path": settings.session_vault_key_path,
        "job_input_key_path": settings.job_input_key_path,
        "instance_lock_path": settings.instance_lock_path,
        "tls_cert_path": settings.tls_cert_path,
        "tls_key_path": settings.tls_key_path,
    }
    for name, value in path_settings.items():
        if value is None:
            problems.append(f"{name} is required")
        elif not Path(value).is_absolute():
            problems.append(f"{name} must be an absolute path")

    if (
        settings.session_vault_key_path is not None
        and settings.job_input_key_path is not None
        and _resolved(settings.session_vault_key_path) == _resolved(settings.job_input_key_path)
    ):
        # Compared after resolving symlinks and "..": two spellings of one
        # file are one file. Hard links and identical key BYTES are caught
        # at startup, once the files can be inspected.
        problems.append("session_vault_key_path and job_input_key_path must be different files")

    served = repository_served_dirs() + tuple(Path(p) for p in settings.public_static_dirs)
    # Confidential paths only: the TLS PRIVATE key is one, the public
    # certificate is not (it is meant to be handed to clients).
    for name in (
        "db_path", "vault_dir", "session_vault_key_path", "job_input_key_path",
        "instance_lock_path", "tls_key_path",
    ):
        value = path_settings[name]
        if value is not None and any(_is_inside(value, directory) for directory in served):
            problems.append(f"{name} must not be inside a publicly served static/frontend directory")

    # API exposure. HTTPS is the only listener there is (ADR-0008,
    # deploy/serve.md): a certificate and key are mandatory whether the
    # server is reached directly or through a reverse proxy, and a
    # blanket wildcard bind is the documented baseline failure (F18).
    if settings.api_host.strip().lower() in _WILDCARD_HOSTS:
        problems.append("api_host must be a specific interface address, not a wildcard bind")

    if problems:
        raise CentralConfigurationError(problems)


# --------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------- #

_FIELDS = {field.name: field for field in dataclasses.fields(Settings)}


def _coerce(name: str, raw: Any) -> Any:
    # `from __future__ import annotations` is not used in mcma.core.config,
    # so field types are real objects; compare by their text.
    annotation = str(_FIELDS[name].type)
    try:
        if "Tuple[pathlib.Path" in annotation or "Tuple[Path" in annotation:
            items = raw.split(",") if isinstance(raw, str) else list(raw)
            return tuple(Path(str(item).strip()) for item in items if str(item).strip())
        if "Tuple[str" in annotation:
            items = raw.split(",") if isinstance(raw, str) else list(raw)
            return tuple(str(item).strip() for item in items if str(item).strip())
        if "Path" in annotation or "pathlib" in annotation:
            return Path(str(raw))
        if "bool" in annotation:
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off"):
                return False
            raise ValueError
        if "float" in annotation:
            return float(raw)
        if "int" in annotation:
            return int(raw)
        if "str" in annotation:
            return str(raw)
    except (TypeError, ValueError):
        raise CentralConfigurationError([f"{name} has an invalid value"]) from None
    raise CentralConfigurationError([f"{name} cannot be set from configuration"])


def load_central_settings(
    config_path: Optional[Path] = None, *, environ: Optional[Mapping[str, str]] = None
) -> Settings:
    """Builds and validates the central server's Settings. File first,
    then MCMA_<FIELD> environment overrides. Raises
    CentralConfigurationError; never falls back to defaults for a
    required setting."""
    env = os.environ if environ is None else environ
    if config_path is None and env.get(CONFIG_FILE_ENV):
        config_path = Path(env[CONFIG_FILE_ENV])

    values: dict[str, Any] = {}
    if config_path is not None:
        try:
            with open(config_path, "rb") as handle:
                values.update(tomllib.load(handle))
        except FileNotFoundError:
            raise CentralConfigurationError([f"configuration file not found: {config_path}"]) from None
        except (OSError, tomllib.TOMLDecodeError):
            raise CentralConfigurationError([f"configuration file could not be read: {config_path}"]) from None
    for name in _FIELDS:
        key = ENV_PREFIX + name.upper()
        if key in env:
            values[name] = env[key]

    problems: list[str] = []
    problems += [f"unknown setting {name!r}" for name in sorted(set(values) - set(_FIELDS))]
    problems += [f"{name} is derived and cannot be set" for name in sorted(_DERIVED_KEYS & set(values))]
    problems += [f"{name} is required" for name in REQUIRED_KEYS if name not in values]
    if problems:
        raise CentralConfigurationError(problems)

    kwargs: dict[str, Any] = {name: _coerce(name, raw) for name, raw in values.items()}
    kwargs["runtime_mode"] = RuntimeMode.CENTRAL_SERVER
    kwargs.setdefault("headless_browser", True)
    # The central server never executes a form. allowed_host is the
    # form-filling target; it is pointed at the real portal host (not the
    # loopback mock) purely so that no mock target exists in this
    # composition. Nothing in central mode reads it for execution.
    kwargs.setdefault("allowed_host", kwargs.get("portal_host", Settings().portal_host))
    settings = Settings(**kwargs)
    validate_central_settings(settings)
    return settings
