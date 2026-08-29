"""
tests/test_session_keeper.py — Unit Tests for Session Keeper
============================================================
Tests missing auth file handling, health check return contract,
and command-line arguments.
"""

import pytest
import asyncio
from tools.session_keeper import check_session_health, DEFAULT_INTERVAL_MINUTES


def test_session_health_missing_file():
    """Test that check_session_health handles non-existent auth file cleanly."""
    result = asyncio.run(check_session_health(auth_file="temp/non_existent_auth.json"))
    assert result["valid"] is False
    assert "not found" in result["message"].lower()
    assert result["timestamp"] is not None


def test_default_interval():
    """Test default interval is 10 minutes."""
    assert DEFAULT_INTERVAL_MINUTES == 10
