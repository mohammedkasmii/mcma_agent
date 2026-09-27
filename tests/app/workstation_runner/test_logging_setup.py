import logging
import logging.handlers

import pytest

from mcma.app.workstation_runner.logging_setup import LOGGER_NAME, configure_logging, log_event


@pytest.fixture(autouse=True)
def _reset_logger_state():
    """logging.getLogger(LOGGER_NAME) is a process-wide singleton -- reset
    its handlers before each test so tests don't see each other's
    configure_logging(some_other_tmp_path) calls."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    yield
    logger.handlers.clear()


def test_configure_logging_creates_rotating_file(tmp_path):
    logger = configure_logging(tmp_path)
    log_event(logger, "startup")
    for handler in logger.handlers:
        handler.flush()
    files = list(tmp_path.glob("*.log"))
    assert len(files) == 1
    assert "startup" in files[0].read_text(encoding="utf-8")


def _rotating_handlers(logger):
    return [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]


def test_configure_logging_is_idempotent(tmp_path):
    logger1 = configure_logging(tmp_path)
    logger2 = configure_logging(tmp_path)
    assert logger1 is logger2
    assert len(_rotating_handlers(logger1)) == 1


def test_configure_logging_bounds_rotation_size(tmp_path):
    logger = configure_logging(tmp_path)
    handler = _rotating_handlers(logger)[0]
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert 0 < handler.maxBytes <= 5 * 1024 * 1024
    assert 0 < handler.backupCount <= 10


@pytest.mark.parametrize("forbidden_key", ["secret", "pairing_code", "authorization", "runner_secret", "password"])
def test_log_event_refuses_forbidden_fields(tmp_path, forbidden_key):
    logger = configure_logging(tmp_path)
    with pytest.raises(ValueError):
        log_event(logger, "test_event", **{forbidden_key: "x"})
