"""
INC-12 -- shared fixtures/stubs for tests/execution/jobs/*. Self-contained
(own db_path/conn/seed helpers) per this project's established
bounded-duplication convention.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pytest

from mcma.execution.inputs import TestOnlyPlaintextEncryptor, compute_content_hash
from mcma.persistence.db import open_database

ACCOUNT_ID = "acct-1"
USER_ID = "user-1"
WORKFLOW = "mission_normal"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcma_test.sqlite3"


@pytest.fixture()
def conn(db_path: Path) -> sqlite3.Connection:
    connection = open_database(db_path)
    connection.execute(
        "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
        "VALUES (?, 'Test', 'MAMDA', 'OUJDA', 1, '2026-01-01T00:00:00+00:00')",
        (ACCOUNT_ID,),
    )
    connection.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, 'h', 'admin', 1)",
        (USER_ID, USER_ID),
    )
    yield connection
    connection.close()


@pytest.fixture()
def encryptor() -> TestOnlyPlaintextEncryptor:
    return TestOnlyPlaintextEncryptor()


@dataclass(frozen=True)
class _StubProvenance:
    input_hash: str
    plan_hash: str
    builder_version: str = "test-1"


@dataclass(frozen=True)
class StubPlan:
    """Duck-types mcma.planning.plan.ProposedPlan's shape used by
    execution.jobs (.needs_review, .provenance.plan_hash,
    .canonical_json())."""

    needs_review: Sequence[str]
    provenance: _StubProvenance

    def canonical_json(self) -> str:
        return json.dumps({"plan_hash": self.provenance.plan_hash, "needs_review": list(self.needs_review)})


def make_stub_plan(input_hash: str, plan_hash: str = "planhash-1", needs_review=()) -> StubPlan:
    return StubPlan(needs_review=tuple(needs_review), provenance=_StubProvenance(input_hash, plan_hash))


def typed_input_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def input_hash_for(payload: dict) -> str:
    return compute_content_hash(typed_input_bytes(payload))
