"""INC-15 -- SSE reconnect replay, authorization filtering, revocation."""

import asyncio

from mcma.app.sse import compute_replay, stream_events
from mcma.persistence.outbox import cleanup_retention
from sse_test_support import ACCOUNT_A, ACCOUNT_B, StubAuthorizer, emit_event


def run_async(coro):
    return asyncio.run(coro)


def test_reconnect_replays_events_after_cursor_authorization_filtered(conn):
    id_1 = emit_event(conn, ACCOUNT_A)
    emit_event(conn, ACCOUNT_B)  # not visible to this principal
    id_3 = emit_event(conn, ACCOUNT_A)

    authorizer = StubAuthorizer(visible={ACCOUNT_A})
    segment = compute_replay(conn, "principal-1", authorizer, last_event_id=0)
    assert [row["event_id"] for row in segment.events] == [id_1, id_3]
    assert segment.needs_resync is False


def test_fresh_connection_with_no_cursor_starts_from_now(conn):
    emit_event(conn, ACCOUNT_A)
    authorizer = StubAuthorizer(visible={ACCOUNT_A})
    segment = compute_replay(conn, "principal-1", authorizer, last_event_id=None)
    assert segment.events == ()
    assert segment.needs_resync is False


def test_cursor_older_than_retention_forces_full_snapshot_resync(conn):
    ids = [emit_event(conn, ACCOUNT_A, created_at="2020-01-01T00:00:00+00:00") for _ in range(3)]
    cleanup_retention(conn, retention_seconds=1, keep_count=1)
    authorizer = StubAuthorizer(visible={ACCOUNT_A})
    segment = compute_replay(conn, "principal-1", authorizer, last_event_id=ids[0])
    assert segment.needs_resync is True


def test_stream_filters_by_injected_authorizer(conn):
    emit_event(conn, ACCOUNT_A)
    emit_event(conn, ACCOUNT_B)
    authorizer = StubAuthorizer(visible={ACCOUNT_A})

    async def _collect():
        events = []
        async for event in stream_events(
            conn, "principal-1", authorizer, last_event_id=0, max_iterations=0, sleep=lambda s: asyncio.sleep(0)
        ):
            events.append(event)
        return events

    events = run_async(_collect())
    assert len(events) == 1  # only account_a's event


def test_sse_revocation_drops_the_stream(conn):
    emit_event(conn, ACCOUNT_A)
    authorizer = StubAuthorizer(visible={ACCOUNT_A})

    async def _collect():
        events = []
        async for event in stream_events(
            conn, "principal-1", authorizer, last_event_id=0, max_iterations=5, sleep=lambda s: asyncio.sleep(0)
        ):
            events.append(event)
            # Revoke right after the first event, THEN emit a new event --
            # without revocation-checking, the next loop iteration would
            # pick this up and yield it.
            authorizer.revoke()
            emit_event(conn, ACCOUNT_A)
        return events

    events = run_async(_collect())
    # Exactly the one event from before revocation -- the post-revocation
    # event is never yielded because the stream is dropped first.
    assert len(events) == 1
