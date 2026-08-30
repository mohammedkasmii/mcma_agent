"""
INC-08 -- permanent regression test for the CI run 33317487676 host
mismatch. Every contract in capabilities_test_support.py was built with
ALLOWED_HOST="127.0.0.1:8080", but test_live_chromium_proof.py independently
defined its own PROOF_PORT=18765 and served the live mock there. Since
mcma.portal.contracts.evaluate_request requires contract.host ==
canonical.host, no contract could ever match, and every one of that file's
5 tests was denied unconditionally -- silently, since "denied" is also what
the three negative-control tests expect, so only the two positive controls
visibly failed.

This test would have failed on 585ab15 (the commit under review when the
mismatch was found): it directly checks the property that broke, and it
statically enforces the fix (import the shared constant, never redefine it).
"""

import ast
from pathlib import Path

from capabilities_test_support import (
    ALLOWED_HOST,
    AUTH_LOGIN_CONTRACT,
    AUTH_LOGIN_PAGE_CONTRACT,
    READ_LIST_MISSIONS_CONTRACT,
    READ_NORMAL_ROWS_CONTRACT,
    READ_PEC_ROWS_CONTRACT,
    READ_SEARCH_PAGE_CONTRACT,
    ROGUE_FINAL_LABELED_AUTH_CONTRACT,
    ROGUE_ROW_WRITE_CONTRACT,
)

ALL_NAMED_CONTRACTS = (
    AUTH_LOGIN_CONTRACT,
    AUTH_LOGIN_PAGE_CONTRACT,
    READ_LIST_MISSIONS_CONTRACT,
    READ_NORMAL_ROWS_CONTRACT,
    READ_PEC_ROWS_CONTRACT,
    READ_SEARCH_PAGE_CONTRACT,
    ROGUE_ROW_WRITE_CONTRACT,
    ROGUE_FINAL_LABELED_AUTH_CONTRACT,
)


def test_every_shared_contract_uses_the_single_allowed_host():
    for contract in ALL_NAMED_CONTRACTS:
        assert contract.host == ALLOWED_HOST, contract.route


def test_live_chromium_proof_imports_the_shared_host_and_never_redefines_it():
    """Static source check on the live-Chromium proof file itself: it must
    import ALLOWED_HOST from capabilities_test_support (never define its own
    host/port literal), and it must never locally reassign the imported
    name afterward (which would silently shadow it and reintroduce exactly
    this bug)."""
    path = Path(__file__).with_name("test_live_chromium_proof.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "capabilities_test_support":
            imported_names.update(alias.name for alias in node.names)
    assert "ALLOWED_HOST" in imported_names, (
        "test_live_chromium_proof.py must import ALLOWED_HOST from "
        "capabilities_test_support, never define its own host/port literal"
    )

    reassigned_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    reassigned_names.add(target.id)
    assert "ALLOWED_HOST" not in reassigned_names, (
        "test_live_chromium_proof.py must not locally reassign ALLOWED_HOST "
        "after importing it -- that would shadow the shared value"
    )
