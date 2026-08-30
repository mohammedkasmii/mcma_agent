"""
INC-10 -- pytest fixtures for tests/persistence/*. Plain constants/helpers
live in persistence_test_support.py, not here (bare "conftest" collision
risk across tests/mock/conftest.py, tests/portal/safety/conftest.py, etc.
if a helper module were named conftest.py instead of a real conftest --
this file IS a real conftest.py, which pytest handles per-directory).
"""

from persistence_test_support import conn, db_path  # noqa: F401
