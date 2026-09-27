"""Importing the central composition root must not load the local job
runner or any writer machinery. Checked in a FRESH interpreter, because
sys.modules in the test process is polluted by every other test."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_MODULES = (
    "mcma.app.main",
    "mcma.execution.runner",
    "mcma.execution.browser_handoff",   # defines ActiveReviewRegistry
    "mcma.portal.writer",
    "mcma.portal.pilot_contracts",
    "mock_server",
)

_PROBE = """
import json, sys
import {target}
loaded = sorted(m for m in sys.modules if m.startswith("mcma") or m == "mock_server")
print(json.dumps(loaded))
"""


def _loaded_after_importing(target: str) -> set:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(target=target)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def test_central_server_import_does_not_load_local_execution_machinery():
    loaded = _loaded_after_importing("mcma.app.central_server")
    assert "mcma.app.central_server" in loaded
    leaked = [name for name in FORBIDDEN_MODULES if name in loaded]
    assert leaked == []


def test_the_shared_composition_module_is_equally_clean():
    loaded = _loaded_after_importing("mcma.app.composition")
    assert [name for name in FORBIDDEN_MODULES if name in loaded] == []


def test_the_probe_can_actually_see_the_local_composition():
    """Guards the guard: if the local root did not show up here, an empty
    'leaked' list above would prove nothing."""
    loaded = _loaded_after_importing("mcma.app.main")
    assert "mcma.execution.runner" in loaded and "mcma.execution.browser_handoff" in loaded
