"""Pilot-integration correction (section 1) -- no automated test may
reference input_dossier/ as a real path to read from. The generic,
redacting tools/private_dossier_validation.py remains the ONLY
authorized reader, and it is never invoked by an automated test either
(tests/tools/test_private_dossier_validation.py exercises its pure
logic against synthetic data only).

This scans the actual AST of every test file under tests/ rather than a
bare substring search, so a docstring explaining WHY input_dossier/ must
never be touched (as this file's own docstring does, and as
tests/test_mapper.py's fixture docstring does) does not itself trip the
guard -- only a string literal used as a VALUE (a path component, a
glob pattern, an argument to open()/Path()/os.path.join()/glob()) does.
"""

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
NEEDLE = "input_dossier"


def _docstring_nodes(tree: ast.AST) -> set:
    """Every string-literal AST node that is a genuine docstring (the
    first statement of the module, a function, or a class body) --
    these are prose, not values a running test could use as a path."""
    docstring_nodes = set()
    candidates = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in candidates:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            docstring_nodes.add(id(body[0].value))
    return docstring_nodes


def _non_docstring_input_dossier_references(source: str) -> list:
    """Returns every string constant containing "input_dossier" that is
    NOT a docstring -- a real reference a test could act on."""
    tree = ast.parse(source)
    docstring_ids = _docstring_nodes(tree)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and NEEDLE in node.value:
            if id(node) not in docstring_ids:
                violations.append((node.lineno, node.value))
    return violations


def test_no_automated_test_references_input_dossier_as_a_path():
    offenders = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.name == "test_no_input_dossier_access.py":
            continue  # this guard's own file legitimately mentions/constructs the literal string
        source = path.read_text(encoding="utf-8")
        if NEEDLE not in source:
            continue
        violations = _non_docstring_input_dossier_references(source)
        for lineno, value in violations:
            offenders.append(f"{path.relative_to(TESTS_DIR.parent)}:{lineno}: {value!r}")
    assert offenders == [], "automated test(s) reference input_dossier/ as a real value:\n" + "\n".join(offenders)


def test_this_guard_actually_catches_a_real_reference():
    """Positive control: proves the AST scan above is not vacuous (it
    would also pass on a file with zero references at all) by running it
    directly against a synthetic snippet that DOES use input_dossier/ as
    a real path, confirming it is caught."""
    snippet = 'import os\npath = os.path.join("input_dossier", "x.json")\n'
    violations = _non_docstring_input_dossier_references(snippet)
    assert len(violations) == 1


def test_a_docstring_mentioning_input_dossier_is_not_flagged():
    """Negative control: a plain prose docstring explaining the policy
    (exactly what this file's own module docstring does) must NOT be
    flagged -- only a real value reference should be."""
    snippet = '"""This module never reads input_dossier/ -- policy only."""\nx = 1\n'
    violations = _non_docstring_input_dossier_references(snippet)
    assert violations == []
