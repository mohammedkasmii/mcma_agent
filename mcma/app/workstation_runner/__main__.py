"""python -m mcma.app.workstation_runner -- also the pythonw.exe entry
point (no console required, no stdout the user would ever see)."""

from __future__ import annotations

import sys

from mcma.app.workstation_runner.app import run

if __name__ == "__main__":
    sys.exit(run())
