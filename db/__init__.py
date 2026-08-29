"""
db package — SQLite persistence layer.

The only module that issues SQL. See PROJECT_ARCHITECTURE_BLUEPRINT.md §7.
"""

from db.schema import connect, init_db, next_version, current_version, DB_PATH
from db.repository import Repository, MISSING_POLLS_BEFORE_ARCHIVE

__all__ = [
    "connect",
    "init_db",
    "next_version",
    "current_version",
    "DB_PATH",
    "Repository",
    "MISSING_POLLS_BEFORE_ARCHIVE",
]
