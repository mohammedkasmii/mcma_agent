"""INC-16 -- Argon2id hashing, AuthProvider seam, no default credentials."""

from mcma.app.auth.passwords import hash_password, verify_password
from mcma.app.auth.provider import AuthProvider, LocalUserAuthProvider


def test_argon2id_hash_and_verify():
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery staple") is True
    assert verify_password(hashed, "wrong password") is False


def test_verify_password_fails_closed_on_malformed_hash():
    assert verify_password("not-a-real-hash", "anything") is False


def test_no_default_credentials_exist(conn):
    row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    assert row["c"] == 0  # a fresh database has no users, admin or otherwise


def test_local_user_auth_provider_authenticates_active_user_only(conn):
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, 'admin', 1)",
        ("u1", "alice", hash_password("s3cret-pw")),
    )
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) VALUES (?, ?, ?, 'viewer', 0)",
        ("u2", "bob", hash_password("another-pw")),
    )
    provider = LocalUserAuthProvider(conn)

    authenticated = provider.authenticate("alice", "s3cret-pw")
    assert authenticated is not None
    assert authenticated.user_id == "u1"
    assert authenticated.role == "admin"

    assert provider.authenticate("alice", "wrong-pw") is None
    assert provider.authenticate("bob", "another-pw") is None  # inactive
    assert provider.authenticate("nobody", "x") is None


def test_auth_provider_seam_substitutable(conn):
    """AR-L2: a second provider can be injected -- domain/workflow code
    would only ever depend on the AuthProvider Protocol, never the
    concrete LocalUserAuthProvider class."""

    class StubProvider:
        def authenticate(self, username, password):
            return None

    def uses_any_provider(provider: AuthProvider):
        return provider.authenticate("x", "y")

    assert uses_any_provider(StubProvider()) is None
    assert uses_any_provider(LocalUserAuthProvider(conn)) is None
