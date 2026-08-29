"""
db/repository.py — Data Access Layer
=====================================
The only module that issues SQL. Everything above it works with plain dicts.

Implements PROJECT_ARCHITECTURE_BLUEPRINT.md §7 and §8. Two rules run through
every method here:

  1. Every business write bumps the global state version and stamps it into the
     touched row's changed_version, so GET /api/v1/state?since=N can answer
     "what changed" with an indexed scan (§7.4).
  2. Lifecycle reconciliation is scoped to a single alert CATEGORY and only ever
     runs on a category that was polled successfully (§8.1, §8.2). A failed
     category must never cause its claims to be archived.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db.schema import connect, init_db, next_version, current_version

MISSING_POLLS_BEFORE_ARCHIVE = 3


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repository:
    """Synchronous SQLite repository. One instance per process."""

    def __init__(self, db_path: Optional[str] = None):
        from db.schema import DB_PATH
        self.conn = connect(db_path or DB_PATH)
        init_db(self.conn)

    def close(self) -> None:
        self.conn.close()

    # -----------------------------------------------------------------
    # Accounts & sessions
    # -----------------------------------------------------------------

    def upsert_account(
        self,
        account_id: str,
        entity: str,
        portfolio: str,
        display_name: str,
        base_url: str,
        is_enabled: bool = True,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO accounts(account_id, entity, portfolio, display_name,
                                     base_url, is_enabled, created_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(account_id) DO UPDATE SET
                    entity=excluded.entity,
                    portfolio=excluded.portfolio,
                    display_name=excluded.display_name,
                    base_url=excluded.base_url,
                    is_enabled=excluded.is_enabled
                """,
                (account_id, entity, portfolio, display_name, base_url,
                 1 if is_enabled else 0, _now()),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO portal_sessions(account_id, auth_state_path) VALUES (?,?)",
                (account_id, f"sessions/{account_id}.json"),
            )

    def list_accounts(self, only_enabled: bool = True) -> List[Dict[str, Any]]:
        sql = """
            SELECT a.*, s.health_status, s.last_validated_at,
                   s.last_successful_poll_at, s.last_poll_outcome,
                   s.last_error, s.auth_state_path,
                   (SELECT COUNT(*) FROM claims c
                     WHERE c.account_id = a.account_id
                       AND c.portal_presence != 'RESOLVED_ON_PORTAL') AS active_claims
            FROM accounts a
            LEFT JOIN portal_sessions s ON s.account_id = a.account_id
        """
        if only_enabled:
            sql += " WHERE a.is_enabled = 1"
        sql += " ORDER BY a.account_id"
        return [dict(r) for r in self.conn.execute(sql)]

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        for acc in self.list_accounts(only_enabled=False):
            if acc["account_id"] == account_id:
                return acc
        return None

    def set_session_health(
        self,
        account_id: str,
        health_status: str,
        error: Optional[str] = None,
        validated: bool = False,
    ) -> None:
        with self.conn:
            v = next_version(self.conn)
            fields = ["health_status = ?", "last_error = ?", "changed_version = ?"]
            params: List[Any] = [health_status, error, v]
            if validated:
                fields.append("last_validated_at = ?")
                params.append(_now())
            params.append(account_id)
            self.conn.execute(
                f"UPDATE portal_sessions SET {', '.join(fields)} WHERE account_id = ?",
                params,
            )

    # -----------------------------------------------------------------
    # Poll runs
    # -----------------------------------------------------------------

    def start_poll_run(self, account_id: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO poll_runs(account_id, started_at, outcome) VALUES (?,?,?)",
                (account_id, _now(), "UNREACHABLE"),
            )
            return int(cur.lastrowid)

    def record_category_outcome(
        self,
        poll_run_id: int,
        category_code: str,
        category_name: str,
        outcome: str,
        alerts_seen: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Records one category's result. §8.2 — a category that FAILED must be
        distinguishable from one that was genuinely EMPTY, because only the
        latter may archive its claims.
        """
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO poll_run_categories
                    (poll_run_id, category_code, category_name, outcome, alerts_seen, error)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(poll_run_id, category_code) DO UPDATE SET
                    outcome=excluded.outcome,
                    alerts_seen=excluded.alerts_seen,
                    error=excluded.error
                """,
                (poll_run_id, category_code, category_name, outcome, alerts_seen, error),
            )

    def finish_poll_run(self, poll_run_id: int, outcome: str, error: Optional[str] = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE poll_runs SET finished_at = ?, outcome = ?, error = ? WHERE id = ?",
                (_now(), outcome, error, poll_run_id),
            )
            if outcome in ("SUCCESS", "PARTIAL"):
                v = next_version(self.conn)
                account_id = self.conn.execute(
                    "SELECT account_id FROM poll_runs WHERE id = ?", (poll_run_id,)
                ).fetchone()["account_id"]
                self.conn.execute(
                    """UPDATE portal_sessions
                          SET last_successful_poll_at = ?, last_poll_outcome = ?,
                              changed_version = ?
                        WHERE account_id = ?""",
                    (_now(), outcome, v, account_id),
                )

    # -----------------------------------------------------------------
    # Claims — ingest & lifecycle
    # -----------------------------------------------------------------

    def upsert_claims_for_category(
        self,
        account_id: str,
        category_code: str,
        category_name: str,
        items: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        """
        Inserts or refreshes every claim seen in one category.
        Returns (new_count, seen_count).
        """
        new_count = 0
        now = _now()
        with self.conn:
            for item in items:
                reference = (item.get("reference") or "").strip()
                if not reference:
                    continue
                v = next_version(self.conn)
                existing = self.conn.execute(
                    """SELECT id FROM claims
                        WHERE account_id=? AND category_code=? AND reference=?""",
                    (account_id, category_code, reference),
                ).fetchone()

                raw_date = (item.get("date_survenance") or "").strip()
                params = {
                    "account_id": account_id,
                    "category_code": category_code,
                    "category_name": category_name,
                    "reference": reference,
                    "id_sinistre": (item.get("id_sinistre") or "").strip(),
                    "date_survenance": _to_iso(raw_date),
                    "date_survenance_raw": raw_date,
                    "societaire": (item.get("societaire") or "").strip(),
                    "police": (item.get("police") or "").strip(),
                    "matricule": (item.get("matricule") or "").strip(),
                    "nature": (item.get("nature") or "").strip(),
                    "portal_status": (item.get("statut") or "").strip(),
                    "direct_url": (item.get("direct_url") or "").strip(),
                    "now": now,
                    "v": v,
                }

                if existing:
                    self.conn.execute(
                        """UPDATE claims SET
                               category_name=:category_name, id_sinistre=:id_sinistre,
                               date_survenance=:date_survenance,
                               date_survenance_raw=:date_survenance_raw,
                               societaire=:societaire, police=:police,
                               matricule=:matricule, nature=:nature,
                               portal_status=:portal_status, direct_url=:direct_url,
                               portal_presence='ACTIVE', consecutive_missing_polls=0,
                               last_seen_at=:now, changed_version=:v
                           WHERE id = :id""",
                        {**params, "id": existing["id"]},
                    )
                else:
                    cur = self.conn.execute(
                        """INSERT INTO claims
                               (account_id, category_code, category_name, reference,
                                id_sinistre, date_survenance, date_survenance_raw,
                                societaire, police, matricule, nature, portal_status,
                                direct_url, portal_presence, consecutive_missing_polls,
                                first_seen_at, last_seen_at, changed_version)
                           VALUES
                               (:account_id, :category_code, :category_name, :reference,
                                :id_sinistre, :date_survenance, :date_survenance_raw,
                                :societaire, :police, :matricule, :nature, :portal_status,
                                :direct_url, 'ACTIVE', 0, :now, :now, :v)""",
                        params,
                    )
                    new_count += 1
                    self.conn.execute(
                        """INSERT OR IGNORE INTO employee_actions
                               (claim_id, employee_status, note, updated_at, changed_version)
                           VALUES (?, 'TODO', '', ?, ?)""",
                        (cur.lastrowid, now, v),
                    )
        return new_count, len(items)

    def reconcile_category(
        self,
        account_id: str,
        category_code: str,
        seen_references: List[str],
    ) -> Dict[str, int]:
        """
        Advances the portal-presence lifecycle for ONE category.

        §8.1 — the caller must only invoke this for a category whose poll outcome
        was SUCCESS or EMPTY. A FAILED category must be skipped entirely, or its
        claims would be counted missing and archived after three ticks.
        """
        seen = set(seen_references)
        stats = {"pending": 0, "archived": 0}
        with self.conn:
            rows = self.conn.execute(
                """SELECT id, reference, consecutive_missing_polls, portal_presence
                     FROM claims
                    WHERE account_id=? AND category_code=?
                      AND portal_presence != 'RESOLVED_ON_PORTAL'""",
                (account_id, category_code),
            ).fetchall()

            for row in rows:
                if row["reference"] in seen:
                    continue
                missing = row["consecutive_missing_polls"] + 1
                presence = (
                    "RESOLVED_ON_PORTAL"
                    if missing >= MISSING_POLLS_BEFORE_ARCHIVE
                    else "MISSING_PENDING_CONFIRMATION"
                )
                v = next_version(self.conn)
                self.conn.execute(
                    """UPDATE claims
                          SET consecutive_missing_polls=?, portal_presence=?, changed_version=?
                        WHERE id=?""",
                    (missing, presence, v, row["id"]),
                )
                if presence == "RESOLVED_ON_PORTAL":
                    stats["archived"] += 1
                else:
                    stats["pending"] += 1
        return stats

    # -----------------------------------------------------------------
    # Employee actions
    # -----------------------------------------------------------------

    def set_employee_action(
        self,
        claim_id: int,
        status: str,
        note: str = "",
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.conn:
            v = next_version(self.conn)
            self.conn.execute(
                """INSERT INTO employee_actions
                       (claim_id, employee_status, note, updated_by, updated_at, changed_version)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(claim_id) DO UPDATE SET
                       employee_status=excluded.employee_status,
                       note=excluded.note,
                       updated_by=excluded.updated_by,
                       updated_at=excluded.updated_at,
                       changed_version=excluded.changed_version""",
                (claim_id, status, note, updated_by, _now(), v),
            )
            # The claim row itself must also move, so a note change shows up in
            # the delta feed alongside its claim.
            self.conn.execute(
                "UPDATE claims SET changed_version=? WHERE id=?", (v, claim_id)
            )
        return {"claim_id": claim_id, "status": status, "note": note, "version": v}

    def find_claim(
        self, account_id: str, category_code: str, reference: str
    ) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """SELECT * FROM claims
                WHERE account_id=? AND category_code=? AND reference=?""",
            (account_id, category_code, reference),
        ).fetchone()
        return dict(row) if row else None

    # -----------------------------------------------------------------
    # Delta feed (§7.4, §9.1)
    # -----------------------------------------------------------------

    def get_state(self, since: int = 0) -> Dict[str, Any]:
        claims = [
            dict(r)
            for r in self.conn.execute(
                """SELECT c.*, a.employee_status, a.note, a.updated_by, a.updated_at
                     FROM claims c
                     LEFT JOIN employee_actions a ON a.claim_id = c.id
                    WHERE c.changed_version > ?
                    ORDER BY c.changed_version""",
                (since,),
            )
        ]
        archived = [c["id"] for c in claims if c["portal_presence"] == "RESOLVED_ON_PORTAL"]
        return {
            "version": current_version(self.conn),
            "accounts": self.list_accounts(),
            "claims": [c for c in claims if c["portal_presence"] != "RESOLVED_ON_PORTAL"],
            "archived": archived,
        }

    def counts(self) -> Dict[str, int]:
        row = self.conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN a.employee_status='DONE' THEN 1 ELSE 0 END) AS done
                 FROM claims c
                 LEFT JOIN employee_actions a ON a.claim_id = c.id
                WHERE c.portal_presence != 'RESOLVED_ON_PORTAL'"""
        ).fetchone()
        return {"total": row["total"] or 0, "done": row["done"] or 0}

    # -----------------------------------------------------------------
    # Audit
    # -----------------------------------------------------------------

    def audit(
        self,
        event_type: str,
        actor: str = "worker",
        account_id: Optional[str] = None,
        claim_id: Optional[int] = None,
        job_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO audit_events
                       (ts, event_type, actor, account_id, claim_id, job_id, details)
                   VALUES (?,?,?,?,?,?,?)""",
                (_now(), event_type, actor, account_id, claim_id, job_id,
                 json.dumps(details, ensure_ascii=False) if details else None),
            )


def _to_iso(raw: str) -> str:
    """
    Normalises 'DD/MM/YYYY HH:MM' to ISO. Returns '' when unparseable — the raw
    string is always preserved separately, so nothing is lost.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""
