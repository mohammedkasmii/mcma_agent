"""
INC-00 §6.7 — menu.py option 1 cannot invoke run_dossier.py; options 2-6 preserved.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)


def _menu_source():
    return (ROOT / "menu.py").read_text(encoding="utf-8")


def _choice_branch(tree, value):
    """Returns the ast.If body for the `choice == value` branch, or None."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == value
        ):
            return node.body
    return None


def test_menu_option1_fill_action_removed():
    src = _menu_source()
    tree = ast.parse(src)
    branch = _choice_branch(tree, "1")
    assert branch is not None, "menu option 1 branch not found"

    branch_src = "\n".join(ast.unparse(stmt) for stmt in branch)
    assert "run_dossier" not in branch_src, "option 1 can still invoke run_dossier.py"
    assert "subprocess" not in branch_src, "option 1 still spawns a subprocess"
    assert "_INC00_CONTAINMENT_MSG" in branch_src, (
        "option 1 must print the permanent-containment notice"
    )

    import menu

    assert menu._INC00_CONTAINMENT_MSG == CONTAINMENT_MSG


def test_menu_options_2_to_6_preserved():
    src = _menu_source()
    tree = ast.parse(src)
    for value in ("2", "3", "4", "5", "6"):
        branch = _choice_branch(tree, value)
        assert branch is not None, f"menu option {value} branch was removed"

    branch2_src = "\n".join(ast.unparse(stmt) for stmt in _choice_branch(tree, "2"))
    assert "auth_setup.py" in branch2_src, "option 2 (login) no longer launches auth_setup.py"
