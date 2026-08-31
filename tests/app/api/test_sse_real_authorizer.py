"""INC-17 -- SSE backed by the REAL Authorizer (RealAuthorizer, backed by
the actual user_account_access table), not the INC-15 stub: a real
authenticated Principal sees only its own accounts' events, and revoking
a real user_account_access row drops the stream mid-iteration."""

import asyncio

from mcma.app.api.app import RealAuthorizer
from mcma.app.api.authz import Principal
from mcma.app.sse import stream_events
from mcma.persistence.repositories.outbox import AccountStateVersionRepository, EventOutboxRepository
from api_test_support import NADOR, OUJDA, create_user, grant_access


def run_async(coro):
    return asyncio.run(coro)


def emit_event(conn, account_id: str) -> int:
    version = AccountStateVersionRepository(conn).bump(account_id)
    return EventOutboxRepository(conn).insert(account_id, version, "test", "TEST_EVENT", "{}", "2026-01-01T00:00:00+00:00")


def test_real_authorizer_only_shows_the_principals_own_accounts(conn):
    user_id = create_user(conn, "alice", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    principal = Principal(user_id=user_id, username="alice", role="operator")
    authorizer = RealAuthorizer(conn)

    emit_event(conn, OUJDA)
    emit_event(conn, NADOR)  # not visible to this principal

    async def _collect():
        events = []
        async for event in stream_events(
            conn, principal, authorizer, last_event_id=0, max_iterations=0, sleep=lambda s: asyncio.sleep(0)
        ):
            events.append(event)
        return events

    events = run_async(_collect())
    assert len(events) == 1


def test_real_authorizer_revocation_drops_the_stream(conn):
    from mcma.persistence.repositories.accounts import UserAccountAccessRepository

    user_id = create_user(conn, "bob", "pw12345", "operator")
    grant_access(conn, user_id, OUJDA)
    principal = Principal(user_id=user_id, username="bob", role="operator")
    authorizer = RealAuthorizer(conn)

    emit_event(conn, OUJDA)

    async def _collect():
        events = []
        async for event in stream_events(
            conn, principal, authorizer, last_event_id=0, max_iterations=5, sleep=lambda s: asyncio.sleep(0)
        ):
            events.append(event)
            # Revoke the REAL user_account_access row right after the
            # first event, then emit a new one -- without a real
            # revocation check, the next iteration would pick it up.
            UserAccountAccessRepository(conn).revoke(user_id, OUJDA)
            emit_event(conn, OUJDA)
        return events

    events = run_async(_collect())
    assert len(events) == 1  # the post-revocation event is never yielded
