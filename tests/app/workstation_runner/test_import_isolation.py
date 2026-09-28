"""Fresh-process import proof, following the pattern in
tests/contracts/test_import_boundaries.py: importing the LIGHTWEIGHT
workstation-runner modules in a brand-new interpreter must never pull in
Playwright, SQLite, FastAPI, mcma.portal, mcma.execution, or
mcma.persistence. The composition root (app.py, which also pulls in
gui.py) is the ONE documented, reviewed exception that may import
mcma.portal -- see pyproject.toml's allow_indirect_imports=true note -- but
even THAT process must never eagerly import the real `playwright` package
itself: mcma.portal's own modules only ever import it lazily, inside
function bodies, at actual browser-launch time (see mcma.portal.browser's
own docstring)."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

_STRICT_FORBIDDEN = (
    "playwright", "sqlite3", "fastapi", "mcma.portal", "mcma.execution", "mcma.persistence",
)

# app.py is the one documented exception allowed to import mcma.portal --
# but never the real playwright package itself (lazy-imported only inside
# a function body, at actual browser-launch time), and never SQLite,
# FastAPI, or the execution/persistence layers, none of which this package
# needs.
_FULL_FORBIDDEN = ("playwright", "sqlite3", "fastapi", "mcma.execution", "mcma.persistence")

_CHECK_SCRIPT = """
import sys
import mcma.app.workstation_runner
import mcma.app.workstation_runner.config
import mcma.app.workstation_runner.identity
import mcma.app.workstation_runner.http_client
import mcma.app.workstation_runner.heartbeat
import mcma.app.workstation_runner.controller
import mcma.app.workstation_runner.browser_worker
import mcma.app.workstation_runner.dry_run_executor
import mcma.app.workstation_runner.execute_executor
import mcma.app.workstation_runner.job_worker
import mcma.app.workstation_runner.logging_setup
forbidden = {forbidden!r}
hit = [m for m in sys.modules if any(m == p or m.startswith(p + ".") for p in forbidden)]
if hit:
    print("FORBIDDEN_IMPORTED:" + ",".join(sorted(hit)))
    sys.exit(1)
print("OK")
"""

_STRICT_CHECK_SCRIPT = _CHECK_SCRIPT.replace("{forbidden!r}", repr(_STRICT_FORBIDDEN))

_FULL_CHECK_SCRIPT = _CHECK_SCRIPT.replace(
    "import mcma.app.workstation_runner.logging_setup\n",
    "import mcma.app.workstation_runner.logging_setup\nimport mcma.app.workstation_runner.gui\nimport mcma.app.workstation_runner.app\n",
).replace("{forbidden!r}", repr(_FULL_FORBIDDEN))


def test_fresh_process_import_proof():
    """The lightweight modules alone -- never mcma.portal, never Playwright,
    never SQLite/FastAPI/execution/persistence."""
    proc = subprocess.run(
        [sys.executable, "-c", _STRICT_CHECK_SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK"


@pytest.mark.skipif(sys.platform != "win32", reason="tkinter import checked only where a Windows desktop session is expected")
def test_fresh_process_import_proof_including_gui_and_app():
    """The full composition root: mcma.portal is expected and allowed here
    (app.py's one documented exception), but the real playwright package
    must still never be eagerly imported, and SQLite/FastAPI/execution/
    persistence remain forbidden even here."""
    proc = subprocess.run(
        [sys.executable, "-c", _FULL_CHECK_SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "OK"
