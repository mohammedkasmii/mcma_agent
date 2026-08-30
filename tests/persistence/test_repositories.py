"""
INC-10 -- repository round-trip tests (one per aggregate).
"""

from mcma.persistence.repositories.accounts import (
    Account,
    AccountsRepository,
    PortalSessionsRepository,
    RolePermissionsRepository,
    UserAccountAccessRepository,
    UsersRepository,
)
from mcma.persistence.repositories.audit import AuditEventsRepository, EmployeeActionsRepository
from mcma.persistence.repositories.claims import (
    CategoriesRepository,
    CategoryPresenceRepository,
    ClaimsRepository,
    ObservedFinalizationsRepository,
    PollRunCategoriesRepository,
    PollRunsRepository,
    UnmatchedNotificationsRepository,
)
from mcma.persistence.repositories.jobs import AutomationJobsRepository, JobInputsRepository
from mcma.persistence.repositories.outbox import AccountStateVersionRepository, EventOutboxRepository


def test_accounts_round_trip(conn):
    repo = AccountsRepository(conn)
    repo.create(Account("acct-1", "Oujda", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    fetched = repo.get("acct-1")
    assert fetched.label == "Oujda"
    assert repo.get("nonexistent") is None
    assert fetched in repo.list_active()


def test_portal_sessions_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    repo = PortalSessionsRepository(conn)
    repo.create("sess-1", "acct-1", "vault-ref-1", "ACTIVE")
    row = repo.get_for_account("acct-1")
    assert row["status"] == "ACTIVE"
    repo.set_status("sess-1", "REVOKED")
    assert repo.get_for_account("acct-1")["status"] == "REVOKED"


def test_users_and_roles_round_trip(conn):
    users = UsersRepository(conn)
    users.create("u1", "alice", "argon2-hash", "admin")
    assert users.get_by_username("alice")["user_id"] == "u1"
    assert users.count() == 1

    roles = RolePermissionsRepository(conn)
    roles.grant("admin", "jobs:execute")
    roles.grant("admin", "jobs:plan")
    assert set(roles.permissions_for_role("admin")) == {"jobs:execute", "jobs:plan"}
    assert roles.permissions_for_role("viewer") == ()


def test_user_account_access_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    UsersRepository(conn).create("u1", "alice", "h", "admin")
    access = UserAccountAccessRepository(conn)
    access.grant("u1", "acct-1", "2026-01-01T00:00:00+00:00")
    assert access.has_access("u1", "acct-1") is True
    assert access.accessible_accounts("u1") == ("acct-1",)
    access.revoke("u1", "acct-1")
    assert access.has_access("u1", "acct-1") is False


def test_claims_and_categories_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    claims = ClaimsRepository(conn)
    claims.upsert("claim-1", "acct-1", "IDS-1", version=1, reference="REF-1")
    row = claims.get("claim-1")
    assert row["portal_claim_id"] == "IDS-1"
    claims.upsert("claim-1-dup-key", "acct-1", "IDS-1", version=2, reference="REF-1-updated")
    updated = claims.get_by_portal_claim_id("acct-1", "IDS-1")
    assert updated["claim_pk"] == "claim-1"  # same identity, updated in place
    assert updated["reference"] == "REF-1-updated"

    categories = CategoriesRepository(conn)
    categories.ensure("CAT1", "Category One")
    presence = CategoryPresenceRepository(conn)
    presence.ensure_row("acct-1", "claim-1", "CAT1", since_version=1)
    fetched = presence.get("acct-1", "claim-1", "CAT1")
    assert fetched["presence_status"] == "ACTIVE"
    presence.update_lifecycle(
        "acct-1", "claim-1", "CAT1",
        present=False, presence_status="MISSING_PENDING_CONFIRMATION",
        consecutive_absence_count=1, last_complete_poll_version=5, last_seen_poll_run_id="poll-1",
    )
    assert presence.get("acct-1", "claim-1", "CAT1")["consecutive_absence_count"] == 1


def test_poll_runs_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    CategoriesRepository(conn).ensure("CAT1", "Category One")
    polls = PollRunsRepository(conn)
    polls.create("poll-1", "acct-1", "2026-01-01T00:00:00+00:00", "COMPLETE", session_valid=True)
    assert polls.get("poll-1")["status"] == "COMPLETE"

    poll_categories = PollRunCategoriesRepository(conn)
    poll_categories.create("poll-1", "CAT1", "COMPLETE", session_valid=True, rows_seen=3)
    assert poll_categories.get("poll-1", "CAT1")["rows_seen"] == 3


def test_unmatched_notifications_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    staging = UnmatchedNotificationsRepository(conn)
    staging.create("stg-1", "acct-1", raw_payload="{}", seen_at="2026-01-01T00:00:00+00:00", reference="REF-1")
    assert len(staging.list_for_account("acct-1")) == 1


def test_observed_finalizations_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    ClaimsRepository(conn).upsert("claim-1", "acct-1", "IDS-1", version=1)
    finalizations = ObservedFinalizationsRepository(conn)
    finalizations.record("claim-1", "2026-01-01T00:00:00+00:00", "POLL_READBACK")
    assert len(finalizations.list_for_claim("claim-1")) == 1


def test_automation_jobs_and_inputs_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    UsersRepository(conn).create("u1", "alice", "h", "admin")
    jobs = AutomationJobsRepository(conn)
    jobs.insert(
        "job-1", "acct-1", "u1", "mission_normal", "DRY_RUN", "QUEUED", "hash1", "idem-1",
        "2026-01-01T00:00:00+00:00", state_version=1,
    )
    assert jobs.get("job-1")["status"] == "QUEUED"
    assert jobs.get_by_idempotency_key("acct-1", "idem-1")["job_id"] == "job-1"
    jobs.update_status("job-1", "PLANNING", state_version=2)
    assert jobs.get("job-1")["status"] == "PLANNING"
    assert jobs.get("job-1") in jobs.list_non_terminal()

    inputs = JobInputsRepository(conn)
    inputs.insert("job-1", "hash1", b"ciphertext", "CONTAINS_PII", "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00")
    assert bytes(inputs.get("job-1")["ciphertext"]) == b"ciphertext"
    inputs.soft_delete("job-1", "2026-01-05T00:00:00+00:00")
    assert inputs.get("job-1")["deleted_at"] is not None


def test_employee_actions_and_audit_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    UsersRepository(conn).create("u1", "alice", "h", "admin")
    ClaimsRepository(conn).upsert("claim-1", "acct-1", "IDS-1", version=1)

    actions = EmployeeActionsRepository(conn)
    actions.create("action-1", "claim-1", "IN_PROGRESS", "u1", "2026-01-01T00:00:00+00:00", version=1)
    assert len(actions.list_for_claim("claim-1")) == 1

    audit = AuditEventsRepository(conn)
    audit.record("audit-1", "JOB_CREATED", "2026-01-01T00:00:00+00:00", actor_user_id="u1", account_id="acct-1")
    assert len(audit.list_for_account("acct-1")) == 1


def test_outbox_round_trip(conn):
    AccountsRepository(conn).create(Account("acct-1", "L", "MAMDA", "OUJDA", True, "2026-01-01T00:00:00+00:00"))
    versions = AccountStateVersionRepository(conn)
    assert versions.current("acct-1") == 0
    assert versions.bump("acct-1") == 1
    assert versions.bump("acct-1") == 2

    outbox = EventOutboxRepository(conn)
    event_id_1 = outbox.insert("acct-1", 1, "job", "JOB_CREATED", '{"job_id":"j1"}', "2026-01-01T00:00:00+00:00")
    event_id_2 = outbox.insert("acct-1", 2, "job", "JOB_UPDATED", '{"job_id":"j1"}', "2026-01-01T00:00:01+00:00")
    assert event_id_2 == event_id_1 + 1
    assert len(outbox.events_after(event_id_1 - 1)) == 2
    assert len(outbox.events_after(event_id_1)) == 1
    assert outbox.earliest_event_id() == event_id_1
    assert outbox.latest_event_id() == event_id_2
