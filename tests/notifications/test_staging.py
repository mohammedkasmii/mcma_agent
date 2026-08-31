"""INC-14 -- idSinistre-less notifications are staged, never claims."""

from mcma.notifications.staging import stage_or_upsert_claim
from mcma.persistence.repositories.claims import ClaimsRepository, UnmatchedNotificationsRepository
from notifications_test_support import NADOR, OUJDA


def test_notification_without_idSinistre_goes_to_staging_not_claims(conn):
    result = stage_or_upsert_claim(conn, OUJDA, {"reference": "REF-1"}, version=1)
    assert result is None
    assert conn.execute("SELECT COUNT(*) AS c FROM claims").fetchone()["c"] == 0
    assert len(UnmatchedNotificationsRepository(conn).list_for_account(OUJDA)) == 1


def test_notification_with_idSinistre_upserts_into_claims(conn):
    result = stage_or_upsert_claim(conn, OUJDA, {"idSinistre": "534660", "reference": "REF-2"}, version=1)
    assert result is not None
    row = ClaimsRepository(conn).get(result)
    assert row["portal_claim_id"] == "534660"
    assert UnmatchedNotificationsRepository(conn).list_for_account(OUJDA) == ()


def test_same_external_id_under_different_accounts_stays_isolated(conn):
    oujda_pk = stage_or_upsert_claim(conn, OUJDA, {"idSinistre": "SAME-ID"}, version=1)
    nador_pk = stage_or_upsert_claim(conn, NADOR, {"idSinistre": "SAME-ID"}, version=1)
    assert oujda_pk != nador_pk
    assert ClaimsRepository(conn).get_by_portal_claim_id(OUJDA, "SAME-ID")["claim_pk"] == oujda_pk
    assert ClaimsRepository(conn).get_by_portal_claim_id(NADOR, "SAME-ID")["claim_pk"] == nador_pk
