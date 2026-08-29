"""
db/migrate.py — One-Time Migration from Flat JSON to SQLite
============================================================
Imports the existing agency data so nothing employees typed is lost:

  logs/mcma_notifications.json   -> claims
  logs/notification_actions.json -> employee_actions (statuses and notes)

PROJECT_ARCHITECTURE_BLUEPRINT.md §12 requires that unmatched entries are
REPORTED, never silently dropped. Legacy actions were keyed on `reference`
alone, with no account or category; this matches them against the claims that
were imported alongside them and prints anything it could not place.

Safe to re-run: claims upsert on (account_id, category_code, reference), and an
existing action is only overwritten when the legacy value is newer.

Usage:
    python -m db.migrate
    python -m db.migrate --dry-run
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from core.accounts import ACCOUNTS, DEFAULT_ACCOUNT_ID
from db.repository import Repository

NOTIFICATIONS_JSON = os.path.join("logs", "mcma_notifications.json")
ACTIONS_JSON = os.path.join("logs", "notification_actions.json")

VALID_STATUSES = {"TODO", "IN_PROGRESS", "DONE", "WAITING"}

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _load(path: str) -> Any:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"    [!] Could not read {path}: {e}")
        return None


def migrate(repo: Repository, dry_run: bool = False) -> Dict[str, int]:
    stats = {"accounts": 0, "claims_new": 0, "claims_seen": 0,
             "actions_applied": 0, "actions_unmatched": 0}

    # 1. Seed the four account profiles.
    print("[*] Seeding account profiles...")
    for acc in ACCOUNTS:
        if not dry_run:
            repo.upsert_account(
                account_id=acc["account_id"],
                entity=acc["entity"],
                portfolio=acc["portfolio"],
                display_name=acc["display_name"],
                base_url=acc["base_url"],
            )
        stats["accounts"] += 1
        print(f"    [+] {acc['account_id']:<14} {acc['display_name']}")

    # 2. Import cached notifications into the default account.
    #    The legacy system had no notion of accounts, so everything it captured
    #    belongs to whichever account was logged in — DEFAULT_ACCOUNT_ID.
    notifs = _load(NOTIFICATIONS_JSON)
    if notifs and notifs.get("categories"):
        print(f"\n[*] Importing claims from {NOTIFICATIONS_JSON} into '{DEFAULT_ACCOUNT_ID}'...")
        for cat in notifs["categories"]:
            code = cat.get("code_alerte") or "LEGACY"
            name = cat.get("category_name") or "ALERTE"
            items = cat.get("items") or []
            if not dry_run:
                new, seen = repo.upsert_claims_for_category(
                    DEFAULT_ACCOUNT_ID, code, name, items
                )
            else:
                new, seen = 0, len(items)
            stats["claims_new"] += new
            stats["claims_seen"] += seen
            print(f"    [+] {name:<40} {seen:>4} item(s), {new} new")
    else:
        print(f"\n[i] No cached notifications at {NOTIFICATIONS_JSON} — skipping claim import.")

    # 3. Apply saved employee statuses and notes.
    actions = _load(ACTIONS_JSON)
    if actions:
        print(f"\n[*] Applying employee actions from {ACTIONS_JSON}...")
        unmatched: List[str] = []
        for reference, payload in actions.items():
            if not isinstance(payload, dict):
                continue
            status = str(payload.get("status") or "TODO").upper()
            if status not in VALID_STATUSES:
                status = "TODO"
            note = str(payload.get("note") or "")

            claim = _find_claim_any_category(repo, reference)
            if claim is None:
                unmatched.append(reference)
                continue
            if not dry_run:
                repo.set_employee_action(
                    claim_id=claim["id"],
                    status=status,
                    note=note,
                    updated_by=payload.get("updated_by") or "migration",
                )
            stats["actions_applied"] += 1

        stats["actions_unmatched"] = len(unmatched)
        print(f"    [+] Applied {stats['actions_applied']} action(s).")
        if unmatched:
            print(f"\n    [!] {len(unmatched)} action(s) could NOT be matched to a claim.")
            print("        These are reported, not dropped. They will attach automatically")
            print("        if the claim reappears on a later poll:")
            for ref in unmatched:
                info = actions[ref]
                print(f"          - {ref}  status={info.get('status')}  note={(info.get('note') or '')[:40]!r}")
    else:
        print(f"\n[i] No saved actions at {ACTIONS_JSON} — nothing to apply.")

    if not dry_run:
        repo.audit("MIGRATION", actor="migration", details=stats)

    return stats


def _find_claim_any_category(repo: Repository, reference: str):
    """Legacy actions have no category, so search every category of every account."""
    row = repo.conn.execute(
        "SELECT * FROM claims WHERE reference = ? ORDER BY id LIMIT 1", (reference,)
    ).fetchone()
    return dict(row) if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate MCMA flat JSON files into SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    parser.add_argument("--db", default=None, help="Database path (default: data/mcma.db)")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  MCMA — MIGRATION JSON -> SQLITE")
    if args.dry_run:
        print("  MODE: DRY RUN (aucune écriture)")
    print("=" * 70 + "\n")

    repo = Repository(args.db)
    try:
        stats = migrate(repo, dry_run=args.dry_run)
    finally:
        repo.close()

    print("\n" + "=" * 70)
    print("  RÉSUMÉ")
    print(f"    Comptes            : {stats['accounts']}")
    print(f"    Sinistres importés : {stats['claims_new']} nouveaux / {stats['claims_seen']} vus")
    print(f"    Actions appliquées : {stats['actions_applied']}")
    print(f"    Actions orphelines : {stats['actions_unmatched']}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
