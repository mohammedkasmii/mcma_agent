"""Fresh-process import proof, following the pattern in
tests/contracts/test_import_boundaries.py: importing the package in a
brand-new interpreter must never pull in Playwright, SQLite, FastAPI,
mcma.portal, mcma.execution, or mcma.persistence."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

_FORBIDDEN_MODULE_PREFIXES = (
    "playwright", "sqlite3", "fastapi", "mcma.portal", "mcma.execution", "mcma.persistence",
)

_CHECK_SCRIPT = """
import sys
import mcma.app.workstation_runner
import mcma.app.workstation_runner.config
import mcma.app.workstation_runner.identity
import mcma.app.workstation_runner.http_client
import mcma.app.workstation_runner.heartbeat
import mcma.app.workstation_runner.controller
import mcma.app.workstation_runner.logging_setup
forbidden = {forbidden!r}
hit = [m for m in sys.modules if any(m == p or m.startswith(p + ".") for p in forbidden)]
if hit:
    print("FORBIDDEN_IMPORTED:" + ",".join(sorted(hit)))
    sys.exit(1)
print("OK")
""".replace("{forbidden!r}", repr(_FORBIDDEN_MODULE_PREFIXES))

_FULL_CHECK_SCRIPT = _CHECK_SCRIPT.replace(
    "import mcma.app.workstation_runner.logging_setup\n",
    "import mcma.app.workstation_runner.logging_setup\nimport mcma.app.workstation_runner.gui\nimport mcma.app.workstation_runner.app\n",
)


def test_fresh_process_import_proof():
    proc = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK"


@pytest.mark.skipif(sys.platform != "win32", reason="tkinter import checked only where a Windows desktop session is expected")
def test_fresh_process_import_proof_including_gui_and_app():
    proc = subprocess.run(
        [sys.executable, "-c", _FULL_CHECK_SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK"
