"""
mcma.app.auth.passwords -- Argon2id password hashing (INC-16, ADR-0008).
argon2-cffi's default PasswordHasher already uses Argon2id; verification
failure of any kind (mismatch, malformed hash, internal error) always
returns False -- never raises out to a caller that might treat an
exception as "authenticated".
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False  # fail closed: a malformed hash or any other error is never "authenticated"
