"""
INC-03 — enforceable dependency-direction contracts for the mcma/ modular
monolith (MODULE_BOUNDARIES.md). Purity is a test, not a convention.
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MCMA_MODULES = [
    "core",
    "domain",
    "mapping",
    "planning",
    "persistence",
    "portal",
    "execution",
    "notifications",
    "app",
]

PURE_PACKAGES = ("mcma.core", "mcma.domain", "mcma.mapping", "mcma.planning")
IO_LIBS = ("playwright", "sqlite3", "fastapi", "httpx", "requests")

LEGACY_TOP_LEVEL = (
    "core",
    "browser",
    "mapper",
    "main",
    "mock_server",
    "run_dossier",
    "menu",
    "trigger",
    "auth_setup",
    "session_keeper",
    "get_notifications",
    "garage_conventionne",
)

SINGLE_OWNER = {
    "playwright": "mcma.portal",
    "sqlite3": "mcma.persistence",
    "fastapi": "mcma.app",
}


def test_mcma_skeleton_importable():
    proc = subprocess.run(
        [sys.executable, "-c", "import " + ", ".join(f"mcma.{m}" for m in MCMA_MODULES)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"mcma skeleton not importable: {proc.stderr}"


def test_domain_imports_no_io():
    """Importing the pure packages must not transitively import any I/O lib
    (checked in a fresh interpreter so other tests cannot pollute sys.modules)."""
    code = (
        "import sys\n"
        f"import {', '.join(PURE_PACKAGES)}\n"
        f"loaded = [lib for lib in {IO_LIBS!r} if lib in sys.modules]\n"
        "assert not loaded, f'pure packages transitively imported: {loaded}'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr


def _imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_single_owner_playwright_sqlite_fastapi():
    """Static scan: exactly one mcma owner per external concern; no mcma file
    imports a legacy top-level module (one-way isolation until INC-22)."""
    for py_file in (ROOT / "mcma").rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        imported = _imports_of(py_file)
        for lib, owner in SINGLE_OWNER.items():
            owner_dir = owner.split(".")[1]
            if lib in imported:
                assert rel.startswith(f"mcma/{owner_dir}/"), (
                    f"{rel} imports {lib}; only {owner} may"
                )
        legacy_hits = imported.intersection(LEGACY_TOP_LEVEL)
        assert not legacy_hits, f"{rel} imports legacy module(s) {legacy_hits}"


def test_no_dependency_cycles():
    """lint-imports enforces the layered one-way contract (cycles impossible)
    plus the purity/ownership/legacy contracts declared in pyproject.toml."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"import-linter contracts broken:\n{proc.stdout}\n{proc.stderr}"
