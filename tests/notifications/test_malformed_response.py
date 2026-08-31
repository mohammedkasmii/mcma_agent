"""INC-15 Fable-review correction -- a malformed/missing-data-key
notification response must be classified FAILED, never a COMPLETE
zero-row poll, so it can never falsely advance the absence counter to
RESOLVED_ON_PORTAL."""

import asyncio

from mcma.notifications.extract import run_poll
from mcma.persistence.repositories.claims import CategoryPresenceRepository, PollRunCategoriesRepository
from notifications_test_support import CATEGORY, OUJDA, seed_claim


def run_async(coro):
    return asyncio.run(coro)


class _MalformedResponseReader:
    """Simulates mcma.portal.capabilities.ReadCapability.read_notifications
    raising on a malformed payload (e.g. a session-expired error page) --
    exactly the fix applied to that method."""

    async def read_notifications(self, code_alerte: str):
        raise ValueError("notification fetch returned a malformed/incomplete payload -- treating as a failed poll")


def test_malformed_response_never_advances_absence_and_never_resolves(conn):
    seed_claim(conn, OUJDA, "claim-1", "IDS-1")
    reader = _MalformedResponseReader()

    for _ in range(5):  # far more than the 3-poll resolve threshold
        poll_run_id = run_async(run_poll(conn, OUJDA, reader, [CATEGORY], version=1))
        assert PollRunCategoriesRepository(conn).get(poll_run_id, CATEGORY)["status"] == "FAILED"

    row = CategoryPresenceRepository(conn).get(OUJDA, "claim-1", CATEGORY)
    # Never even created (no COMPLETE poll ever ran) -- or if created,
    # still at zero/ACTIVE. Either way, never RESOLVED_ON_PORTAL.
    if row is not None:
        assert row["consecutive_absence_count"] == 0
        assert row["presence_status"] == "ACTIVE"
