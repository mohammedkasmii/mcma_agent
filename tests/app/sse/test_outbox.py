"""INC-15 -- outbox atomicity, global cursor, retention semantics."""

from mcma.execution.jobs import enqueue_dry_run, transition
from mcma.execution.inputs import TestOnlyPlaintextEncryptor, compute_content_hash
from mcma.persistence.outbox import cleanup_retention, cursor_is_stale, earliest_retained_event_id, latest_event_id
from sse_test_support import ACCOUNT_A, ACCOUNT_B, emit_event


def test_outbox_event_written_in_same_transaction_as_state_change(conn):
    """Reuses INC-12's own atomic-transition machinery (job row + outbox
    event, one transaction) as the concrete proof of this outbox-level
    requirement."""
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES ('u1','u1','h','admin',1)"
    )
    payload = b'{"dossier":"x"}'
    job_id = enqueue_dry_run(
        conn, account_id=ACCOUNT_A, requested_by_user_id="u1", workflow_name="mission_normal",
        input_hash=compute_content_hash(payload), typed_input_bytes=payload,
        idempotency_key="k1", encryptor=TestOnlyPlaintextEncryptor(),
    )
    events_before = conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]
    transition(conn, job_id, "PLANNING")
    events_after = conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"]
    assert events_after == events_before + 1


def test_sse_cursor_is_global_event_id(conn):
    id_a = emit_event(conn, ACCOUNT_A)
    id_b = emit_event(conn, ACCOUNT_B)
    assert id_b == id_a + 1  # global, shared across accounts -- not per-account


def test_retention_bounded_by_time_and_count_not_by_idle_client_cursor(conn):
    for _ in range(5):
        emit_event(conn, ACCOUNT_A, created_at="2020-01-01T00:00:00+00:00")  # ancient
    # An idle client's cursor still points at event_id=1 -- cleanup must
    # not be blocked by that.
    removed = cleanup_retention(conn, retention_seconds=1, keep_count=0)
    assert removed == 5
    assert earliest_retained_event_id(conn) is None


def test_retention_never_drops_below_keep_count(conn):
    for _ in range(5):
        emit_event(conn, ACCOUNT_A, created_at="2020-01-01T00:00:00+00:00")
    removed = cleanup_retention(conn, retention_seconds=1, keep_count=3)
    assert removed == 2
    assert conn.execute("SELECT COUNT(*) AS c FROM event_outbox").fetchone()["c"] == 3


def test_cursor_older_than_retention_forces_full_snapshot_resync(conn):
    ids = [emit_event(conn, ACCOUNT_A, created_at="2020-01-01T00:00:00+00:00") for _ in range(3)]
    cleanup_retention(conn, retention_seconds=1, keep_count=1)  # drops the first two
    assert cursor_is_stale(conn, ids[0]) is True
    assert cursor_is_stale(conn, ids[-1]) is False


def test_cursor_is_stale_false_when_nothing_retained_yet(conn):
    assert cursor_is_stale(conn, 0) is False
    assert latest_event_id(conn) == 0
