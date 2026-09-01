"""
A real FastAPI application, real routes, real built frontend -- seeded with
synthetic data and served over loopback HTTP for browser E2E.

This is NOT a second web server and not a mock of the application. It calls
the same create_api_app() and mount_frontend() the composition root calls, so
what the browser exercises is the actual serving contract: route precedence,
the SPA fallback, the CSP header, /assets, and /events.

What it deliberately leaves out is everything that would require a portal or a
browser supervisor: no runner loop, no Playwright-driven SinAuto, no TLS. Jobs
are inserted directly at the statuses the UI must render, because the point is
to prove what the employee sees, not to re-test the state machine that the
Python suite already covers.

Local single-user mode is on, so there is no login step to automate; the
authenticated principal is the seeded local employee.
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from mcma.app.api.app import create_api_app
from mcma.app.frontend import mount_frontend
from mcma.app.provisioning import ensure_local_employee
from mcma.execution.inputs import TestOnlyPlaintextEncryptor
from mcma.persistence.db import open_database

# Synthetic throughout. No production account id, no real name, no real
# registration or police number appears in this file.
ACCOUNTS = (
    ("e2e-acct-mcma-a", "MCMA Zone A", "MCMA", "ZONE-A"),
    ("e2e-acct-mcma-b", "MCMA Zone B", "MCMA", "ZONE-B"),
    ("e2e-acct-mamda-a", "MAMDA Zone A", "MAMDA", "ZONE-A"),
)

READY_JOB = "e2e-job-ready"
AWAITING_JOB = "e2e-job-awaiting"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed(conn) -> None:
    for account_id, label, entity, scope in ACCOUNTS:
        conn.execute(
            "INSERT INTO accounts (account_id, label, entity, scope, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (account_id, label, entity, scope, _now()),
        )

    user_id = ensure_local_employee(conn)
    for account_id, *_ in ACCOUNTS:
        conn.execute(
            "INSERT OR IGNORE INTO user_account_access (user_id, account_id, granted_at) "
            "VALUES (?, ?, ?)",
            (user_id, account_id, _now()),
        )

    conn.execute(
        "INSERT INTO claims (claim_pk, account_id, portal_claim_id, reference, insured, "
        "police, matricule_norm, first_seen_version, last_seen_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)",
        (
            "e2e-claim-1",
            "e2e-acct-mcma-a",
            "e2e-portal-1",
            "REF-E2E-0001",
            "Assure Test E2E",
            "POL-E2E-0001",
            "0000-A-0",
        ),
    )

    # Two execution jobs at the two human-handoff statuses. Inserted directly:
    # reaching them for real would need the portal.
    for job_id, status in ((READY_JOB, "READY_FOR_HUMAN_REVIEW"), (AWAITING_JOB, "AWAITING_HUMAN_CONFIRMATION")):
        conn.execute(
            "INSERT INTO automation_jobs (job_id, account_id, requested_by_user_id, "
            "parent_job_id, workflow_name, mode, status, input_hash, idempotency_key, "
            "created_at, started_at, state_version) "
            "VALUES (?, ?, ?, NULL, 'e2e_workflow', 'EXECUTE', ?, 'e2e-hash', ?, ?, ?, 1)",
            (job_id, "e2e-acct-mcma-a", user_id, status, job_id, _now(), _now()),
        )
    # isolation_level=None: every statement above is already committed.


def build() -> object:
    db_path = Path(tempfile.mkdtemp(prefix="mcma-e2e-")) / f"{uuid.uuid4().hex}.sqlite3"
    conn = open_database(db_path)
    _seed(conn)
    app = create_api_app(
        conn,
        auth_provider=None,
        encryptor=TestOnlyPlaintextEncryptor(),
        secure_cookies=False,
        local_user_id=ensure_local_employee(conn),
    )
    mount_frontend(app)
    return app


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    uvicorn.run(build(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
