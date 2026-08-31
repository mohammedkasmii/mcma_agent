"""INC-12 -- DRY_RUN state machine, read-capability-only proof."""

from mcma.execution.jobs import enqueue_dry_run, run_dry_run_identity_check, run_dry_run_planning
from jobs_test_support import ACCOUNT_ID, USER_ID, WORKFLOW, input_hash_for, make_stub_plan, typed_input_bytes


class _StubReadOnlyIdentityCheck:
    """Structurally incapable of writing -- has no write-like method at
    all, only __call__, so a caller could not accidentally invoke a write
    even if it tried."""

    def __init__(self, matches: bool):
        self._matches = matches
        self.called = False

    def __call__(self) -> bool:
        self.called = True
        return self._matches


def _enqueue(conn, encryptor, payload, key="key-1"):
    return enqueue_dry_run(
        conn,
        account_id=ACCOUNT_ID,
        requested_by_user_id=USER_ID,
        workflow_name=WORKFLOW,
        input_hash=input_hash_for(payload),
        typed_input_bytes=typed_input_bytes(payload),
        idempotency_key=key,
        encryptor=encryptor,
    )


def test_dry_run_planning_writeable_reaches_planned(conn, encryptor):
    payload = {"dossier": "a"}
    job_id = _enqueue(conn, encryptor, payload)
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, job_id, build_plan=lambda: plan)
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "PLANNED"


def test_dry_run_planning_needs_review_stops_there(conn, encryptor):
    payload = {"dossier": "b"}
    job_id = _enqueue(conn, encryptor, payload)
    plan = make_stub_plan(input_hash_for(payload), needs_review=("AMBIGUOUS_GLASS",))
    run_dry_run_planning(conn, job_id, build_plan=lambda: plan)
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "NEEDS_REVIEW"


def test_dry_run_path_uses_read_capability_only(conn, encryptor):
    payload = {"dossier": "c"}
    job_id = _enqueue(conn, encryptor, payload)
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, job_id, build_plan=lambda: plan)

    check = _StubReadOnlyIdentityCheck(matches=True)
    matched = run_dry_run_identity_check(conn, job_id, check_identity_read_only=check)

    assert check.called is True
    assert matched is True
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "DRY_RUN_VERIFIED"
    # No VerifiedMissionWriter-shaped object was ever constructed or
    # passed anywhere in this path -- run_dry_run_identity_check's own
    # signature accepts only a bare bool-returning callable.
    import inspect

    from mcma.execution.jobs import run_dry_run_identity_check as fn

    sig = inspect.signature(fn)
    assert list(sig.parameters) == ["conn", "job_id", "check_identity_read_only"]


def test_dry_run_identity_mismatch_fails_closed(conn, encryptor):
    payload = {"dossier": "d"}
    job_id = _enqueue(conn, encryptor, payload)
    plan = make_stub_plan(input_hash_for(payload))
    run_dry_run_planning(conn, job_id, build_plan=lambda: plan)

    check = _StubReadOnlyIdentityCheck(matches=False)
    matched = run_dry_run_identity_check(conn, job_id, check_identity_read_only=check)
    assert matched is False
    assert conn.execute("SELECT status FROM automation_jobs WHERE job_id=?", (job_id,)).fetchone()["status"] == "IDENTITY_FAILED"
