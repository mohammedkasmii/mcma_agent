"""mcma.app.workstation_runner.logging_setup -- bounded rotating local logs.
log_event() is the only sanctioned way to write to this logger: it takes a
fixed event name plus primitive keyword fields and refuses a hardcoded list
of forbidden field names, so a future call site cannot pass a secret by
accident. Never logs request/response bodies, headers, ciphertext, or raw
exception text -- callers pass safe categories (e.g. event="heartbeat_failed",
reason="connection")."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOGGER_NAME = "mcma.workstation_runner"

_MAX_BYTES = 1 * 1024 * 1024
_BACKUP_COUNT = 5

_FORBIDDEN_FIELDS = frozenset({
    "secret", "pairing_code", "authorization", "runner_secret", "password",
    "token", "ciphertext", "body", "headers",
})


def configure_logging(log_dir: Path) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    target_path = str((log_dir / "workstation_runner.log").resolve())
    # Idempotent on the target FILE, not on "any handler present": a test
    # harness (pytest's own log capture) may attach unrelated handlers to
    # this logger between calls, and that must never cause a second
    # RotatingFileHandler pointed at the same file.
    if any(
        isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == target_path
        for h in logger.handlers
    ):
        return logger
    handler = logging.handlers.RotatingFileHandler(
        target_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, **safe_fields) -> None:
    forbidden = _FORBIDDEN_FIELDS & set(safe_fields)
    if forbidden:
        raise ValueError(f"refusing to log forbidden field(s): {sorted(forbidden)}")
    fields = " ".join(f"{k}={v!r}" for k, v in sorted(safe_fields.items()))
    logger.info("%s %s", event, fields)
