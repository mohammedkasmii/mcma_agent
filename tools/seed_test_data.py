"""
tools/seed_test_data.py — Fictional Claims for Testing
=======================================================
Inserts a handful of obviously fake claims so the dashboard can be exercised
without any portal access, credentials, or SMS code.

Run from the project root:

    python -m tools.seed_test_data            insert the fixtures
    python -m tools.seed_test_data --clear    remove them again

Every reference is prefixed TEST- and lives in the TESTCAT category, so --clear
can remove exactly what this script created and nothing else. The names are
fictional; never seed real sociétaire data.
"""

import argparse
import sys

from db.repository import Repository

ACCOUNT = "mcma_oujda"
CATEGORY_CODE = "TESTCAT"
CATEGORY_NAME = "CATEGORIE DE TEST (donnees fictives)"

FIXTURES = [
    {
        "reference": "TEST-001",
        "id_sinistre": "900001",
        "societaire": "ALAOUI Mohamed",
        "matricule": "12345-A-7",
        "police": "DEMO-0000001",
        "date_survenance": "19/06/2025 00:00",
        "nature": "MATÉRIEL",
        "statut": "DÉCLARÉ",
    },
    {
        "reference": "TEST-002",
        "id_sinistre": "900002",
        "societaire": "BENNANI Fatima",
        "matricule": "67890-B-12",
        "police": "DEMO-0000002",
        "date_survenance": "20/06/2025 10:30",
        "nature": "MATÉRIEL",
        "statut": "EN COURS",
    },
    {
        "reference": "TEST-003",
        "id_sinistre": "900003",
        "societaire": "TAZI Youssef",
        "matricule": "WW123456",
        "police": "DEMO-0000003",
        "date_survenance": "21/06/2025 16:45",
        "nature": "CORPOREL",
        "statut": "DÉCLARÉ",
    },
]

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def seed(repo: Repository) -> None:
    new, seen = repo.upsert_claims_for_category(
        ACCOUNT, CATEGORY_CODE, CATEGORY_NAME, FIXTURES
    )
    print(f"[+] {new} nouveau(x) sinistre(s) de test sur {seen} traité(s).")
    for f in FIXTURES:
        print(f"    - {f['reference']:<10} {f['societaire']:<20} {f['matricule']}")
    print("\n[i] Ouvrez http://localhost:8000 — ils doivent apparaître.")


def clear(repo: Repository) -> None:
    rows = repo.conn.execute(
        "SELECT id FROM claims WHERE account_id=? AND category_code=?",
        (ACCOUNT, CATEGORY_CODE),
    ).fetchall()
    with repo.conn:
        repo.conn.execute(
            "DELETE FROM claims WHERE account_id=? AND category_code=?",
            (ACCOUNT, CATEGORY_CODE),
        )
    print(f"[+] {len(rows)} sinistre(s) de test supprimé(s).")
    print("[i] Les sinistres réels ne sont pas touchés.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fictional claims for testing")
    parser.add_argument("--clear", action="store_true", help="Remove the test claims")
    args = parser.parse_args()

    repo = Repository()
    try:
        clear(repo) if args.clear else seed(repo)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
