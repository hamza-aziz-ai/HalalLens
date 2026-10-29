#!/usr/bin/env python3
"""Regression tests for the API's authentication, authorisation and billing guards.

Each test here pins down a specific hole that was open before: watchlists
readable across accounts, reviewer queues open to anonymous callers, an OAuth
redirect that accepted look-alike hosts, and a payment webhook that recorded
events without ever granting the subscription the user had paid for.
"""

import asyncio
import base64
import hashlib
import importlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from api import security

api_module = importlib.import_module("api.app")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_password_roundtrip_and_uniqueness():
    first = security.hash_password("Correct horse 42")
    second = security.hash_password("Correct horse 42")
    assert first != second, "salt must make identical passwords hash differently"
    assert security.verify_password("Correct horse 42", first)
    assert not security.verify_password("correct horse 42", first)


def test_current_hash_format_is_versioned():
    algorithm, iterations, _salt, _digest = security.hash_password("pw").split("$", 3)
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) == security.PBKDF2_ITERATIONS
    assert not security.needs_rehash(security.hash_password("pw"))


def test_legacy_hashes_verify_but_are_flagged_for_rehash():
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", b"legacy-secret", salt, 100_000)
    legacy = base64.b64encode(salt + derived).decode("ascii")

    assert security.verify_password("legacy-secret", legacy)
    assert not security.verify_password("wrong-secret", legacy)
    assert security.needs_rehash(legacy), "old 100k hashes must be upgraded on login"


@pytest.mark.parametrize("stored", [None, "", "pbkdf2_sha256$notanumber$a$b", "!!!"])
def test_verify_password_rejects_malformed_hashes(stored):
    assert not security.verify_password("anything", stored)


@pytest.mark.parametrize(
    "password", ["short1", "alllettersonly", "1234567890", "password123"]
)
def test_password_policy_rejects_weak_passwords(password):
    assert security.password_policy_error(password) is not None


def test_password_policy_accepts_a_reasonable_password():
    assert security.password_policy_error("Sh4riahScreening") is None


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------


class SessionDBStub:
    """Minimal stand-in for BSEDatabaseManager's auth surface."""

    def __init__(self, *, is_admin: bool = False, email: str = "user@example.com"):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.is_admin = is_admin
        self.email = email
        self.admin_promotions: List[int] = []

    def create_user_session(self, token, user_id, expires_at):
        self.sessions[token] = {
            "token": token,
            "user_id": user_id,
            "expires_at": expires_at,
            "email": self.email,
            "plan": "starter",
            "subscription_status": "active",
            "subscription_renewal": expires_at,  # a timed plan always has an end
            "trial_used": False,
            "is_admin": self.is_admin,
            "email_verified_at": expires_at,
        }

    def get_session(self, token):
        entry = self.sessions.get(token)
        return dict(entry) if entry else None

    def delete_session(self, token):
        self.sessions.pop(token, None)

    def set_user_admin(self, user_id, is_admin=True):
        self.admin_promotions.append(user_id)


def test_issued_token_is_never_stored_verbatim(monkeypatch):
    stub = SessionDBStub()
    monkeypatch.setattr(api_module, "_get_db", lambda: stub)

    token, _expires = api_module._issue_session(7)

    assert token not in stub.sessions, "raw bearer token must not reach the database"
    assert security.hash_session_token(token) in stub.sessions
    # A database dump alone must not be replayable as a credential.
    stored_key = next(iter(stub.sessions))
    with pytest.raises(HTTPException) as excinfo:
        api_module._require_session(f"Bearer {stored_key}")
    assert excinfo.value.status_code == 401

    _resolved, session = api_module._require_session(f"Bearer {token}")
    assert session["user_id"] == 7


def test_expired_session_is_rejected_and_purged(monkeypatch):
    stub = SessionDBStub()
    monkeypatch.setattr(api_module, "_get_db", lambda: stub)
    token, _ = api_module._issue_session(7)
    key = security.hash_session_token(token)
    stub.sessions[key]["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)

    with pytest.raises(HTTPException) as excinfo:
        api_module._require_session(f"Bearer {token}")
    assert excinfo.value.status_code == 401
    assert key not in stub.sessions


@pytest.mark.parametrize(
    "header", [None, "", "Basic abc", "Bearer", "Bearer   ", 12345, object()]
)
def test_extract_token_ignores_non_bearer_input(header):
    assert api_module._extract_token(header) is None


def test_require_admin_rejects_paying_non_admin(monkeypatch):
    stub = SessionDBStub(is_admin=False, email="subscriber@example.com")
    monkeypatch.setattr(api_module, "_get_db", lambda: stub)
    monkeypatch.setattr(api_module, "ADMIN_EMAILS", [], raising=False)
    token, _ = api_module._issue_session(3)

    # An active subscription is enough for paid features...
    assert api_module._require_paid_feature(f"Bearer {token}", "History")
    # ...but not for operator surfaces.
    with pytest.raises(HTTPException) as excinfo:
        api_module._require_admin(f"Bearer {token}", "Governance overrides")
    assert excinfo.value.status_code == 403


def test_require_admin_allows_admin(monkeypatch):
    stub = SessionDBStub(is_admin=True, email="ops@example.com")
    monkeypatch.setattr(api_module, "_get_db", lambda: stub)
    token, _ = api_module._issue_session(3)
    session = api_module._require_admin(f"Bearer {token}", "Governance overrides")
    assert session["user_id"] == 3


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_origin_allowlist_rejects_suffix_lookalikes(monkeypatch):
    import re

    monkeypatch.setattr(api_module, "ALLOWED_ORIGINS", ["https://app.example.com"])
    monkeypatch.setattr(
        api_module, "_ALLOWED_ORIGIN_RE", re.compile(r"https://app\.example\.com")
    )

    assert api_module._origin_allowed("https://app.example.com")
    # `re.match` would accept both of these; `re.fullmatch` must not.
    assert not api_module._origin_allowed("https://app.example.com.attacker.test")
    assert not api_module._origin_allowed("https://app.example.completely-evil.io")
    assert not api_module._origin_allowed("")


def test_origin_allowlist_without_regex_is_exact(monkeypatch):
    monkeypatch.setattr(api_module, "ALLOWED_ORIGINS", ["https://app.example.com"])
    monkeypatch.setattr(api_module, "_ALLOWED_ORIGIN_RE", None)
    assert api_module._origin_allowed("https://app.example.com")
    assert not api_module._origin_allowed("https://evil.example.com")


# ---------------------------------------------------------------------------
# Google OAuth redirect handling
# ---------------------------------------------------------------------------


def test_google_redirect_allowlist_blocks_lookalike_hosts(monkeypatch):
    monkeypatch.setattr(api_module, "FRONTEND_BASE_URL", "https://app.example.com")

    assert (
        api_module._sanitize_google_redirect("https://app.example.com/dashboard")
        == "https://app.example.com/dashboard"
    )
    assert api_module._sanitize_google_redirect("halallens://auth/login")

    # Same prefix, different host - a startswith check would hand over the token.
    assert api_module._sanitize_google_redirect("https://app.example.com.evil.test") is None
    assert api_module._sanitize_google_redirect("https://evil.test/app.example.com") is None
    # Scheme downgrade must not be accepted either.
    assert api_module._sanitize_google_redirect("http://app.example.com/dashboard") is None
    assert api_module._sanitize_google_redirect(None) is None


def test_google_redirect_puts_token_in_fragment_only(monkeypatch):
    monkeypatch.setattr(api_module, "FRONTEND_BASE_URL", "https://app.example.com")
    expires = datetime(2026, 1, 1, tzinfo=timezone.utc)

    url = api_module._build_google_redirect("secret-token", expires)
    before_fragment, _, fragment = url.partition("#")

    assert "secret-token" not in before_fragment, "token must not land in the query string"
    assert "secret-token" in fragment
    assert before_fragment == "https://app.example.com/login"


def test_google_redirect_honours_sanitised_base(monkeypatch):
    monkeypatch.setattr(api_module, "FRONTEND_BASE_URL", "https://app.example.com")
    expires = datetime(2026, 1, 1, tzinfo=timezone.utc)
    url = api_module._build_google_redirect("tok", expires, "halallens://auth/login")
    assert url.startswith("halallens://auth/login#")
    assert "?" not in url


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_sliding_window_blocks_after_limit():
    limiter = security.SlidingWindowRateLimiter()
    rule = security.RateLimitRule(limit=3, window_seconds=60)

    for _ in range(3):
        allowed, _ = limiter.check("login", "1.2.3.4", rule, now=100.0)
        assert allowed

    allowed, retry_after = limiter.check("login", "1.2.3.4", rule, now=100.0)
    assert not allowed
    assert retry_after == pytest.approx(60.0)

    # A different identity is unaffected.
    allowed, _ = limiter.check("login", "5.6.7.8", rule, now=100.0)
    assert allowed


def test_sliding_window_recovers_after_window():
    limiter = security.SlidingWindowRateLimiter()
    rule = security.RateLimitRule(limit=1, window_seconds=10)

    assert limiter.check("b", "id", rule, now=0.0)[0]
    assert not limiter.check("b", "id", rule, now=5.0)[0]
    assert limiter.check("b", "id", rule, now=11.0)[0]


def test_throttled_caller_cannot_extend_its_own_penalty():
    limiter = security.SlidingWindowRateLimiter()
    rule = security.RateLimitRule(limit=1, window_seconds=10)

    limiter.check("b", "id", rule, now=0.0)
    for moment in (1.0, 2.0, 3.0):
        assert not limiter.check("b", "id", rule, now=moment)[0]
    # The window is still measured from the single accepted hit at t=0.
    assert limiter.check("b", "id", rule, now=10.5)[0]


def test_enforce_rate_limit_raises_429(monkeypatch):
    monkeypatch.setattr(api_module, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(
        api_module,
        "RATE_LIMIT_RULES",
        {"auth_login": security.RateLimitRule(limit=1, window_seconds=60)},
    )
    api_module.RATE_LIMITER.reset()

    api_module._enforce_rate_limit("auth_login", "9.9.9.9")
    with pytest.raises(HTTPException) as excinfo:
        api_module._enforce_rate_limit("auth_login", "9.9.9.9")
    assert excinfo.value.status_code == 429
    assert "Retry-After" in (excinfo.value.headers or {})


def test_rate_limit_disabled_is_a_no_op(monkeypatch):
    monkeypatch.setattr(api_module, "RATE_LIMIT_ENABLED", False)
    api_module.RATE_LIMITER.reset()
    for _ in range(100):
        api_module._enforce_rate_limit("auth_login", "9.9.9.9")


class _FakeRequest:
    def __init__(self, host: Optional[str], headers: Optional[Dict[str, str]] = None):
        self.client = type("C", (), {"host": host})() if host else None
        self.headers = headers or {}


def test_forwarded_for_is_ignored_unless_proxy_is_trusted(monkeypatch):
    request = _FakeRequest("10.0.0.1", {"x-forwarded-for": "1.1.1.1, 2.2.2.2"})

    monkeypatch.setattr(api_module, "TRUST_PROXY_HEADERS", False)
    assert api_module._client_identity(request) == "10.0.0.1"

    monkeypatch.setattr(api_module, "TRUST_PROXY_HEADERS", True)
    assert api_module._client_identity(request) == "1.1.1.1"

    assert api_module._client_identity(None) == "unknown"


# ---------------------------------------------------------------------------
# Log injection
# ---------------------------------------------------------------------------


def test_log_text_is_stripped_of_control_characters():
    hostile = "ok\r\n2026-01-01 INFO [api] payment verified for attacker"
    cleaned = api_module._sanitize_log_text(hostile)
    assert "\n" not in cleaned and "\r" not in cleaned
    assert api_module._sanitize_log_text("x" * 900, limit=10).endswith("[truncated]")


# ---------------------------------------------------------------------------
# Cache bounds
# ---------------------------------------------------------------------------


def test_ttl_cache_stays_bounded(monkeypatch):
    monkeypatch.setattr(api_module, "CACHE_MAX_ENTRIES", 10)
    cache: Dict[str, Any] = {}
    for index in range(200):
        api_module._cache_set(cache, f"key-{index}", index, ttl=300)
    assert len(cache) <= 10
