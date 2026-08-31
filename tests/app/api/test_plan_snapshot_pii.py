"""Dossier PII must not survive in automation_jobs.plan_snapshot.

Phase C.1 encrypted job_inputs and its audit found this second path: the
snapshot stored ProposedPlan.canonical_json() verbatim, which carries the
vehicle registration and the claim identifier in the clear. A copy of the
database still disclosed which vehicle and which claim every job
concerned.

These are the regression tests that replace the skipped
PII_IN_PLAN_SNAPSHOT_PENDING_FOLLOW_UP finding.

The markers are recognisable so a leak is unmistakable in a failure
message rather than something to squint at.
"""

import json

import pytest

from api_test_support import (
    OUJDA,
    app_and_client,  # noqa: F401
    conn,  # noqa: F401
    create_user,
    csrf_headers,
    db_path,  # noqa: F401
    grant_access,
    login_client,
)

PII_REGISTRATION = "77001-C-3"
PII_CLAIM = "699001"
OLD_SNAPSHOT = json.dumps(
    {"expected_identity": {"registration": {"raw": "PII_OLD_REG"}, "id_sinistre": "PII_OLD_CLAIM"}}
)


def _plan_a_dry_run(conn):
    """Drives the REAL planner over the REAL Mode Normal input, so the
    identity block under test is the one production would produce."""
    import sys

    sys.path.insert(0, "tests/execution/runner")
    from runner_test_support import MODE_NORMAL_TYPED_INPUT

    from mcma.execution.inputs import TestOnlyPlaintextEncryptor, compute_content_hash
    from mcma.execution.jobs import enqueue_dry_run, run_dry_run_planning
    from mcma.mapping.wexia import parse_wexia
    from mcma.planning.plan import detect_workflow
    from mcma.planning.registry import default_registry, workflow_name_for

    # requested_by_user_id is a real FK.
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('operator-1', 'operator-1', 'x', 'operator', 1)"
    )
    parsed = parse_wexia(MODE_NORMAL_TYPED_INPUT)
    workflow_name = workflow_name_for(detect_workflow(parsed))
    payload = json.dumps(MODE_NORMAL_TYPED_INPUT, sort_keys=True).encode("utf-8")

    job_id = enqueue_dry_run(
        conn, account_id=OUJDA, requested_by_user_id="operator-1", workflow_name=workflow_name,
        input_hash=compute_content_hash(payload), typed_input_bytes=payload,
        idempotency_key="pii-1", encryptor=TestOnlyPlaintextEncryptor(),
    )
    builder = default_registry().get(workflow_name)
    run_dry_run_planning(conn, job_id, build_plan=lambda: builder(parsed))
    return job_id


def _job_row(conn, job_id):
    return conn.execute("SELECT * FROM automation_jobs WHERE job_id = ?", (job_id,)).fetchone()


# --------------------------------------------------------------------- #
# Nothing is persisted
# --------------------------------------------------------------------- #


def test_planning_leaves_no_snapshot_behind(conn):
    job_id = _plan_a_dry_run(conn)
    assert _job_row(conn, job_id)["plan_snapshot"] is None


def test_no_column_of_the_job_row_contains_the_registration_or_claim(conn):
    """Not just plan_snapshot: the whole row is swept, so moving the same
    data into a neighbouring column would fail this too."""
    job_id = _plan_a_dry_run(conn)
    row = _job_row(conn, job_id)
    for key in row.keys():
        value = row[key]
        if value is None:
            continue
        assert PII_REGISTRATION not in str(value), f"registration leaked in column {key!r}"
        assert PII_CLAIM not in str(value), f"claim id leaked in column {key!r}"
        assert "77001C3" not in str(value), f"normalized registration leaked in column {key!r}"


def test_the_plan_hash_is_still_stored(conn):
    """Execution authorization compares it, so removing the snapshot must
    not have taken the digest with it."""
    job_id = _plan_a_dry_run(conn)
    plan_hash = _job_row(conn, job_id)["plan_hash"]
    assert plan_hash
    assert len(plan_hash) == 64          # sha256 hex, a digest not content


def test_the_plan_can_still_be_rebuilt_and_matches_the_stored_hash(conn):
    """Data minimisation is only safe because the plan is reconstructible:
    the encrypted input plus the pure planner reproduce the same hash."""
    import sys

    sys.path.insert(0, "tests/execution/runner")
    from runner_test_support import MODE_NORMAL_TYPED_INPUT

    from mcma.execution.inputs import TestOnlyPlaintextEncryptor, retrieve_and_verify_job_input
    from mcma.mapping.wexia import parse_wexia
    from mcma.planning.plan import detect_workflow
    from mcma.planning.registry import default_registry, workflow_name_for

    job_id = _plan_a_dry_run(conn)
    row = _job_row(conn, job_id)

    retained = retrieve_and_verify_job_input(
        conn, job_id, row["input_hash"], TestOnlyPlaintextEncryptor()
    )
    parsed = parse_wexia(json.loads(retained))
    rebuilt = default_registry().get(workflow_name_for(detect_workflow(parsed)))(parsed)
    assert rebuilt.provenance.plan_hash == row["plan_hash"]
    # And the identity really is in the rebuilt plan -- it was never
    # unavailable, only never written down.
    assert PII_REGISTRATION in rebuilt.canonical_json()


def test_no_other_table_picked_up_the_snapshot(conn):
    """Removing it from one column must not mean caching it in another."""
    _plan_a_dry_run(conn)
    for table in ("event_outbox", "audit_events"):
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():
            joined = str(tuple(row))
            assert PII_REGISTRATION not in joined
            assert PII_CLAIM not in joined


# --------------------------------------------------------------------- #
# Migration clears what old installations already wrote
# --------------------------------------------------------------------- #


def test_the_migration_erases_snapshots_written_before_the_fix(conn, db_path):
    """An install that has been running already has this data on disk.
    Hiding it from the API would not remove it."""
    from mcma.persistence.db import open_database

    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('u1', 'u1', 'x', 'operator', 1)"
    )
    conn.execute(
        "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, workflow_name, "
        "mode, status, input_hash, idempotency_key, created_at, state_version, plan_snapshot) "
        "VALUES ('old-job', ?, 'u1', 'MODE_NORMAL', 'DRY_RUN', 'PLANNED', 'h', 'k', "
        "'2026-01-01T00:00:00+00:00', 1, ?)",
        (OUJDA, OLD_SNAPSHOT),
    )
    assert "PII_OLD_REG" in _job_row(conn, "old-job")["plan_snapshot"]

    # Re-running migrations is what an upgrade does.
    conn.execute("DELETE FROM schema_migrations WHERE version = '0003_drop_plan_snapshot_pii'")
    migrated = open_database(db_path)

    row = migrated.execute(
        "SELECT plan_snapshot FROM automation_jobs WHERE job_id = 'old-job'"
    ).fetchone()
    assert row["plan_snapshot"] is None


# --------------------------------------------------------------------- #
# The API cannot leak it either
# --------------------------------------------------------------------- #


def test_jobs_response_is_an_allowlist_not_the_whole_row(conn, app_and_client):
    """dict(row) published every column by default, which is how this data
    reached the browser. A new sensitive column must not become public
    just by existing."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    job_id = _plan_a_dry_run(conn)
    # Something sensitive sitting in the row, as if an old install.
    conn.execute("UPDATE automation_jobs SET plan_snapshot = ? WHERE job_id = ?",
                 (OLD_SNAPSHOT, job_id))
    login_client(client, "alice", "pw12345")

    response = client.get("/jobs")
    assert response.status_code == 200
    body = response.text
    assert "PII_OLD_REG" not in body
    assert "PII_OLD_CLAIM" not in body
    assert PII_REGISTRATION not in body
    assert PII_CLAIM not in body

    job = response.json()["jobs"][0]
    assert "plan_snapshot" not in job          # not even a key
    assert set(job.keys()) <= {
        "job_id", "account_id", "parent_job_id", "workflow_name", "mode", "status",
        "reason_code", "plan_hash", "created_at", "started_at", "finished_at",
    }
    # The fields the dashboard actually uses are still there.
    assert job["job_id"] == job_id
    assert job["status"]


def test_a_future_sensitive_column_is_not_published_automatically(conn, app_and_client):
    """The point of the allowlist, tested directly."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    _plan_a_dry_run(conn)
    conn.execute("ALTER TABLE automation_jobs ADD COLUMN future_secret TEXT")
    conn.execute("UPDATE automation_jobs SET future_secret = 'PII_FUTURE_LEAK'")
    login_client(client, "alice", "pw12345")

    response = client.get("/jobs")
    assert "PII_FUTURE_LEAK" not in response.text


def test_the_plan_preview_is_served_on_demand_without_the_identity(conn, app_and_client):
    """The dashboard genuinely needs a preview -- it is what an employee
    reads before authorizing a fill -- so it is rebuilt from the encrypted
    input rather than stored. The identity block is deliberately not in
    the projection: it is exactly the data being removed, and the employee
    already knows which dossier they uploaded."""
    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    job_id = _plan_a_dry_run(conn)
    login_client(client, "alice", "pw12345")

    response = client.get(f"/jobs/{job_id}/plan")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan_hash"] == _job_row(conn, job_id)["plan_hash"]
    assert body["repair_workflow"]
    assert body["steps"]                       # the preview is real
    assert PII_REGISTRATION not in response.text
    assert PII_CLAIM not in response.text
    assert "expected_identity" not in response.text


def test_the_plan_preview_is_account_scoped(conn, app_and_client):
    from api_test_support import NADOR

    app, client, _ = app_and_client
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, NADOR)          # NOT the job's account
    job_id = _plan_a_dry_run(conn)
    login_client(client, "alice", "pw12345")

    assert client.get(f"/jobs/{job_id}/plan").status_code in (403, 404)


def test_the_plan_preview_requires_authentication(conn, app_and_client):
    app, client, _ = app_and_client
    job_id = _plan_a_dry_run(conn)
    assert client.get(f"/jobs/{job_id}/plan").status_code == 401
