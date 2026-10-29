"""Auth SQL (D-020) against a real, disposable PostgreSQL.

Opt-in like tests/test_watchlist_postgres.py: skipped unless
HALALLENS_TEST_PG_DSN points at a throwaway database (the test applies
database/schema.sql and the auth migration, then drops the tables it uses).
Proves what mocks cannot: the SQL runs, a proof is single-use under
concurrency, and a login that checked the old password cannot leave a session
behind after a password reset.
"""

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DSN = os.getenv("HALALLENS_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="HALALLENS_TEST_PG_DSN not set (disposable Postgres only)")

ROOT = Path(__file__).resolve().parents[1]
ADMINS = ["owner@example.com"]


@pytest.fixture()
def db():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from database.database_manager import BSEDatabaseManager

    admin = psycopg2.connect(DSN)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute((ROOT / "database/schema.sql").read_text(encoding="utf-8"))
        cur.execute((ROOT / "database/migrations/20261029_auth_email_verification.sql").read_text(encoding="utf-8"))

    @contextmanager
    def get_connection():
        conn = psycopg2.connect(DSN, cursor_factory=RealDictCursor)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    manager = BSEDatabaseManager.__new__(BSEDatabaseManager)  # no pool, no startup DDL
    manager.get_connection = get_connection
    yield manager, admin
    admin.close()


def _add_user(admin, email, *, password_hash=None, verified=True, google_sub=None, provider="password"):
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, password_hash, provider, google_sub, email_verified_at) "
            "VALUES (%s, %s, %s, %s, CASE WHEN %s THEN NOW() END) RETURNING id",
            (email, password_hash, provider, google_sub, verified),
        )
        return cur.fetchone()[0]


def _token(manager, purpose, email, user_id, digest, minutes=30):
    manager.issue_auth_token(
        purpose=purpose, email=email, user_id=user_id, token_digest=digest,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=minutes),
    )


def _count(admin, sql, *args):
    with admin.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def test_signup_proof_is_single_use_under_concurrency(db):
    manager, admin = db
    _token(manager, "signup", "owner@example.com", None, "d-signup")
    results = []
    barrier = threading.Barrier(6)

    def confirm():
        barrier.wait()
        results.append(manager.complete_signup(token_digest="d-signup", password_hash="h", admin_emails=ADMINS)[0])

    threads = [threading.Thread(target=confirm) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["invalid_token"] * 5 + ["ok"]
    assert _count(admin, "SELECT count(*) FROM users WHERE email = %s AND is_admin AND email_verified_at IS NOT NULL",
                  "owner@example.com") == 1


def test_reset_after_a_slow_old_password_login_leaves_no_session(db):
    manager, admin = db
    user_id = _add_user(admin, "u@example.com", password_hash="old-hash")
    _token(manager, "reset_password", "u@example.com", user_id, "d-reset")
    login_holds_lock = threading.Event()

    def slow_check(stored):
        login_holds_lock.set()
        time.sleep(1.0)  # PBKDF2 while the row is locked
        return stored == "old-hash"

    def login():
        manager.login_with_password(
            email="u@example.com", check_password=slow_check, rehash=lambda h: None,
            session_digest="old-password-session", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )

    t = threading.Thread(target=login)
    t.start()
    login_holds_lock.wait(5)
    status, _ = manager.complete_password_reset(token_digest="d-reset", password_hash="new-hash", admin_emails=ADMINS)
    t.join()
    assert status == "ok"
    # The reset waited for the login's lock, then revoked the session it made.
    assert _count(admin, "SELECT count(*) FROM user_sessions") == 0
    assert _count(admin, "SELECT count(*) FROM users WHERE password_hash = 'new-hash'") == 1


def test_login_after_reset_cannot_use_the_old_password(db):
    manager, admin = db
    user_id = _add_user(admin, "u@example.com", password_hash="old-hash", verified=False)
    _token(manager, "reset_password", "u@example.com", user_id, "d-reset")
    assert manager.complete_password_reset(token_digest="d-reset", password_hash="new-hash", admin_emails=ADMINS)[0] == "ok"
    status, _ = manager.login_with_password(
        email="u@example.com", check_password=lambda h: h == "old-hash", rehash=lambda h: None,
        session_digest="s", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert status == "bad_credentials"
    assert _count(admin, "SELECT count(*) FROM users WHERE email_verified_at IS NOT NULL") == 1


def test_unverified_login_creates_no_session(db):
    manager, admin = db
    _add_user(admin, "legacy@example.com", password_hash="h", verified=False)
    status, _ = manager.login_with_password(
        email="legacy@example.com", check_password=lambda h: True, rehash=lambda h: None,
        session_digest="s", expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert status == "unverified"
    assert _count(admin, "SELECT count(*) FROM user_sessions") == 0


def test_only_the_latest_proof_works_and_expired_ones_fail(db):
    manager, admin = db
    user_id = _add_user(admin, "u@example.com", password_hash="h")
    _token(manager, "reset_password", "u@example.com", user_id, "first")
    _token(manager, "reset_password", "u@example.com", user_id, "second", minutes=-1)  # already expired
    for digest in ("first", "second"):
        assert manager.complete_password_reset(token_digest=digest, password_hash="x", admin_emails=ADMINS)[0] == "invalid_token"


def test_google_sign_in_rules(db):
    manager, admin = db
    _add_user(admin, "taken@example.com", password_hash="h", verified=False)
    assert manager.google_sign_in(email="taken@example.com", google_sub="g1", full_name=None,
                                  avatar_url=None, admin_emails=ADMINS) == ("email_in_use", None)
    assert _count(admin, "SELECT count(*) FROM users WHERE google_sub IS NOT NULL") == 0

    status, user = manager.google_sign_in(email="owner@example.com", google_sub="g2", full_name="O",
                                          avatar_url=None, admin_emails=ADMINS)
    assert status == "ok" and user["is_admin"] and user["email_verified_at"] and user["provider"] == "google"

    linked = _add_user(admin, "linked@example.com", password_hash="h", verified=False, google_sub="g3")
    status, user = manager.google_sign_in(email="linked@example.com", google_sub="g3", full_name=None,
                                          avatar_url=None, admin_emails=ADMINS)
    assert status == "ok" and user["id"] == linked and user["email_verified_at"]


def test_migration_revokes_unproven_admins_and_sessions(db):
    _manager, admin = db
    user_id = _add_user(admin, "old-admin@example.com", password_hash="h", verified=False)
    with admin.cursor() as cur:
        cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (user_id,))
        cur.execute("INSERT INTO user_sessions (token, user_id, expires_at) VALUES ('t', %s, NOW() + interval '1 day')", (user_id,))
        cur.execute((ROOT / "database/migrations/20261029_auth_email_verification.sql").read_text(encoding="utf-8"))
    assert _count(admin, "SELECT count(*) FROM users WHERE is_admin") == 0
    assert _count(admin, "SELECT count(*) FROM user_sessions") == 0
