"""
mcma.app.sse -- per-account SSE stream: global event_id cursor,
Last-Event-ID replay, snapshot resync on a stale cursor, and periodic
re-authorization (INC-15, ADR-0009, DATA_MODEL.md §7/§8, correction #9).

Auth does not exist yet (INC-16/17 come later) -- this module depends
only on the injected `Authorizer` Protocol below, avoiding a circular
dependency. INC-17 supplies the real, authenticated implementation and
proves that revoking `user_account_access` drops/rebuilds the affected
stream; this module's own tests use a stub.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Protocol

from sse_starlette.sse import EventSourceResponse

from mcma.persistence.outbox import cursor_is_stale, events_after, latest_event_id

REAUTHORIZATION_INTERVAL_SECONDS = 30


class Authorizer(Protocol):
    def visible_accounts(self, principal) -> set: ...
    def is_authorized(self, principal, account_id: str) -> bool: ...


@dataclass(frozen=True)
class ReplaySegment:
    """One thing to send to the client: either a full resync snapshot
    (needs_resync=True, cursor is the fresh baseline to resume from) or a
    plain ordered batch of delta events."""

    needs_resync: bool
    cursor: int
    events: tuple


def compute_replay(conn, principal, authorizer: Authorizer, last_event_id: Optional[int]) -> ReplaySegment:
    """Pure (aside from the DB read) -- no I/O to the client, easily
    tested without a real SSE connection. `last_event_id=None` means a
    fresh connection with no prior cursor: it starts from "now" (the
    current latest_event_id), never replaying history it never asked
    for."""
    visible = authorizer.visible_accounts(principal)
    current_latest = latest_event_id(conn)

    if last_event_id is None:
        return ReplaySegment(needs_resync=False, cursor=current_latest, events=())

    if cursor_is_stale(conn, last_event_id):
        return ReplaySegment(needs_resync=True, cursor=current_latest, events=())

    rows = events_after(conn, last_event_id, tuple(visible))
    return ReplaySegment(needs_resync=False, cursor=(rows[-1]["event_id"] if rows else last_event_id), events=rows)


def _event_payload(row) -> dict:
    return {
        "id": str(row["event_id"]),
        "event": row["type"],
        "data": row["payload_json"],
    }


async def stream_events(
    conn,
    principal,
    authorizer: Authorizer,
    *,
    last_event_id: Optional[int] = None,
    poll_interval_seconds: float = 1.0,
    max_iterations: Optional[int] = None,
    sleep=None,
) -> AsyncIterator[dict]:
    """The actual generator EventSourceResponse consumes. Re-checks
    authorization every iteration (at minimum once per
    poll_interval_seconds -- always at least as often as
    REAUTHORIZATION_INTERVAL_SECONDS requires) -- on revocation, the
    stream ends (the caller/transport is expected to not reconnect an
    unauthorized principal). `sleep` is injectable for tests;
    `max_iterations` bounds a test run instead of looping forever."""
    sleep = sleep or asyncio.sleep
    cursor = last_event_id
    iterations = 0

    segment = compute_replay(conn, principal, authorizer, cursor)
    if segment.needs_resync:
        yield {"event": "resync", "data": json.dumps({"cursor": segment.cursor})}
        cursor = segment.cursor
    else:
        for row in segment.events:
            yield _event_payload(row)
        cursor = segment.cursor

    while max_iterations is None or iterations < max_iterations:
        accounts_to_check = authorizer.visible_accounts(principal)
        if accounts_to_check and not all(authorizer.is_authorized(principal, acc) for acc in accounts_to_check):
            return  # revoked -- drop the stream
        segment = compute_replay(conn, principal, authorizer, cursor)
        if segment.needs_resync:
            yield {"event": "resync", "data": json.dumps({"cursor": segment.cursor})}
            cursor = segment.cursor
        else:
            for row in segment.events:
                yield _event_payload(row)
            cursor = segment.cursor
        iterations += 1
        await sleep(poll_interval_seconds)


def create_sse_endpoint(conn, authorizer: Authorizer, get_principal):
    """Returns a FastAPI-route-ready async callable. `get_principal(request)`
    resolves the authenticated principal -- injected so this module never
    imports the real auth system (INC-16/17 wires the real one)."""

    async def endpoint(request):
        principal = get_principal(request)
        last_event_id_header = request.headers.get("last-event-id")
        last_event_id = int(last_event_id_header) if last_event_id_header else None
        generator = stream_events(conn, principal, authorizer, last_event_id=last_event_id)
        return EventSourceResponse(generator)

    return endpoint
