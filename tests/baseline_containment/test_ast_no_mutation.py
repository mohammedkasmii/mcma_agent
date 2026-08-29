"""
INC-00 §6.12 — structural lock: each contained writer body is exactly one
Raise (optionally preceded by a docstring), with no page/write call and no
charge-mutuelle or row-endpoint string remaining.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONTAINED_FUNCTIONS = [
    ("main.py", "process_workflow"),
    ("browser/mode_normal.py", "fill_mode_normal"),
    ("browser/mode_conventionne.py", "fill_garage_conventionne"),
    ("browser/mode_conventionne.py", "_edit_single_row_dynamic"),
]

FORBIDDEN_BODY_STRINGS = (
    "MontantChargeMutuelle",
    "MontantChargeSocietaire",
    "updateDevisDet",
    "createRapportDefDet",
)


def _find_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _is_docstring_stmt(stmt):
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _assert_refusal_body(rel_path, func_name):
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    node = _find_function(tree, func_name)
    assert node is not None, f"{rel_path}:{func_name} not found"

    body = list(node.body)
    if body and _is_docstring_stmt(body[0]):
        body = body[1:]
    assert len(body) == 1 and isinstance(body[0], ast.Raise), (
        f"{rel_path}:{func_name} body must be exactly one Raise "
        f"(optionally preceded by a docstring); found: "
        f"{[type(s).__name__ for s in body]}"
    )

    dumped = ast.dump(node)
    for forbidden in FORBIDDEN_BODY_STRINGS:
        assert forbidden not in dumped, (
            f"{rel_path}:{func_name} still references '{forbidden}'"
        )


def test_process_workflow_body_is_single_raise():
    _assert_refusal_body("main.py", "process_workflow")


def test_mode_normal_body_is_single_raise():
    _assert_refusal_body("browser/mode_normal.py", "fill_mode_normal")


def test_mode_conventionne_bodies_are_single_raise():
    _assert_refusal_body("browser/mode_conventionne.py", "fill_garage_conventionne")
    _assert_refusal_body("browser/mode_conventionne.py", "_edit_single_row_dynamic")
