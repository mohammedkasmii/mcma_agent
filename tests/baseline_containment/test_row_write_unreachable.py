"""
INC-00 §6.14 — no reachable baseline call path can post the row-write
endpoints. Endpoint names may remain only as inert data (module-level
blocklists) or docstrings. No tracked production module imports the
untracked v12_camoufox_output.generated_client.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TRACKED_FILE_SET = [
    "main.py",
    "run_dossier.py",
    "menu.py",
    "trigger.py",
    "garage_conventionne.py",
    "browser/mode_normal.py",
    "browser/mode_conventionne.py",
    "browser/form_filler.py",
    "browser/mission_navigator.py",
    "browser/safety_interceptor.py",
]

ROW_WRITE_ENDPOINTS = ("updateDevisDet", "createRapportDefDet")

CONTAINED_FUNCTIONS = [
    ("main.py", "process_workflow"),
    ("browser/mode_normal.py", "fill_mode_normal"),
    ("browser/mode_conventionne.py", "fill_garage_conventionne"),
    ("browser/mode_conventionne.py", "_edit_single_row_dynamic"),
]


def _parse(rel_path):
    return ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))


def _is_docstring_stmt(stmt):
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _inert_constant_ids(tree):
    """Constants inside module-level data assignments or docstrings are inert."""
    inert = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) or _is_docstring_stmt(stmt):
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Constant):
                    inert.add(id(sub))
    # Docstrings of functions/classes are inert too.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and _is_docstring_stmt(node.body[0]):
                inert.add(id(node.body[0].value))
    return inert


def test_contained_writer_bodies_are_refusals():
    for rel_path, func_name in CONTAINED_FUNCTIONS:
        tree = _parse(rel_path)
        node = _find_function(tree, func_name)
        assert node is not None, f"{rel_path}:{func_name} not found"
        body = list(node.body)
        if body and _is_docstring_stmt(body[0]):
            body = body[1:]
        assert len(body) == 1 and isinstance(body[0], ast.Raise), (
            f"{rel_path}:{func_name} is not a pure refusal body"
        )


def test_no_executable_row_write_call_site_remains():
    for rel_path in TRACKED_FILE_SET:
        tree = _parse(rel_path)
        inert = _inert_constant_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(ep in node.value for ep in ROW_WRITE_ENDPOINTS)
            ):
                assert id(node) in inert, (
                    f"{rel_path}: executable reference to a row-write endpoint "
                    f"remains: {node.value!r}"
                )


def test_no_tracked_production_import_of_v12_camoufox_output():
    for rel_path in TRACKED_FILE_SET:
        tree = _parse(rel_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.startswith("v12_camoufox_output"), (
                    f"{rel_path} imports {name}"
                )
