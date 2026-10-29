"""HTTP-level contracts: every request goes through the ASGI stack.

The handler tests in test_api_endpoints.py call route functions directly, so
routing, header parsing, body validation, middleware, CORS and serialization
are only exercised here. A framework upgrade (FastAPI, Starlette, Pydantic)
that breaks any of them should fail this module.

No database is used: DB_MANAGER is a MagicMock whose get_session() resolves the
four test identities below. Assertions about authorised callers only check that
the guard let them through; what the handler then does with a mock database is
covered elsewhere. Outbound sockets are blocked, so a route that reaches for BSE,
a vendor, Razorpay or Google fails fast instead of hanging on the network.
"""

import importlib
import socket
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from alerts import AlertEngine, WatchEntry
from tests.watchlist_fake import MemoryWatchlistStorage
from api.security import RateLimitRule, hash_session_token

api_module = importlib.import_module("api.app")

FUTURE = datetime.now(timezone.utc) + timedelta(days=30)
PAST = datetime.now(timezone.utc) - timedelta(days=1)

SESSIONS = {
    "free-token": {
        "user_id": 1,
        "email": "free@example.invalid",
        "plan": "free",
        "subscription_status": "inactive",
        "is_admin": False,
        "expires_at": FUTURE,
        "email_verified_at": PAST,
    },
    "paid-token": {
        "user_id": 2,
        "email": "paid@example.invalid",
        "plan": "pro",
        "subscription_status": "active",
        "subscription_renewal": FUTURE,
        "is_admin": False,
        "expires_at": FUTURE,
        "email_verified_at": PAST,
    },
    "paid-token-2": {
        "user_id": 3,
        "email": "paid2@example.invalid",
        "plan": "pro",
        "subscription_status": "active",
        "subscription_renewal": FUTURE,
        "is_admin": False,
        "expires_at": FUTURE,
        "email_verified_at": PAST,
    },
    "admin-token": {
        "user_id": 4,
        "email": "admin@example.invalid",
        "plan": "free",
        "subscription_status": "inactive",
        "is_admin": True,
        "expires_at": FUTURE,
        "email_verified_at": PAST,
    },
    "expired-token": {
        "user_id": 5,
        "email": "expired@example.invalid",
        "plan": "pro",
        "subscription_status": "active",
        "subscription_renewal": FUTURE,
        "is_admin": False,
        "expires_at": PAST,
        "email_verified_at": PAST,
    },
}

SCORE_BODY = {
    "snapshot": {"symbol": "ABC", "filing_date": "2026-01-01T00:00:00"},
    "market_data": {"market_cap": 1000.0},
}

# (method, route path) -> (tier, concrete URL, JSON body). Keep in step with the
# route-tier table in docs/guides/API.md ("API and security model"); test_every_route_has_a_tier
# fails when a route is added without an entry here.
ROUTES = {
    ("GET", "/health"): ("public", "/health", None),
    ("POST", "/halal-score"): ("public", "/halal-score", SCORE_BODY),
    ("POST", "/narrate"): ("paid", "/narrate", SCORE_BODY),
    ("GET", "/auth/google/start"): ("public", "/auth/google/start", None),
    ("GET", "/auth/google/callback"): ("public", "/auth/google/callback?code=c&state=s", None),
    ("POST", "/auth/google/link/start"): ("authenticated", "/auth/google/link/start", {"password": "StrongPass123!"}),
    ("POST", "/auth/google/link/confirm"): ("authenticated", "/auth/google/link/confirm", {"code": "c" * 43}),
    ("POST", "/auth/register"): ("public", "/auth/register", {"email": "new@example.invalid"}),
    ("POST", "/auth/password/forgot"): ("public", "/auth/password/forgot", {"email": "new@example.invalid"}),
    ("POST", "/auth/signup/confirm"): (
        "public",
        "/auth/signup/confirm",
        {"token": "t" * 43, "password": "StrongPass123!"},
    ),
    ("POST", "/auth/password/reset"): (
        "public",
        "/auth/password/reset",
        {"token": "t" * 43, "password": "StrongPass123!"},
    ),
    ("POST", "/auth/login"): (
        "public",
        "/auth/login",
        {"email": "new@example.invalid", "password": "StrongPass123!"},
    ),
    ("POST", "/auth/logout"): ("authenticated", "/auth/logout", None),
    ("GET", "/auth/me"): ("authenticated", "/auth/me", None),
    ("POST", "/client-logs"): ("public", "/client-logs", {"message": "hello"}),
    ("GET", "/billing/plans"): ("public", "/billing/plans", None),
    # Public by design: only a status and an age, for the uptime workflow (D-025).
    ("GET", "/health/billing"): ("public", "/health/billing", None),
    ("POST", "/billing/trial"): ("authenticated", "/billing/trial", {"plan_code": "pro"}),
    ("POST", "/billing/razorpay/order"): ("authenticated", "/billing/razorpay/order", {}),
    ("POST", "/billing/razorpay/verify"): (
        "authenticated",
        "/billing/razorpay/verify",
        {"order_id": "o", "payment_id": "p", "signature": "s"},
    ),
    ("POST", "/billing/cancel"): ("authenticated", "/billing/cancel", None),
    ("GET", "/billing/entitlement"): ("authenticated", "/billing/entitlement", None),
    ("GET", "/billing/razorpay/order/{order_id}"): ("authenticated", "/billing/razorpay/order/o", None),
    # Public by design: authenticity comes from the Razorpay HMAC signature.
    ("POST", "/webhooks/razorpay"): ("public", "/webhooks/razorpay", {}),
    ("POST", "/watchlist"): ("paid", "/watchlist", {"user_id": "someone", "symbol": "ABC"}),
    ("GET", "/watchlist/{user_id}"): ("paid", "/watchlist/someone", None),
    ("POST", "/alerts/check"): ("paid", "/alerts/check", {"symbol": "ABC", "is_compliant": True}),
    # Authenticated, not paid: opting out of alert emails must work after access ends (D-031).
    ("GET", "/account/alert-emails"): ("authenticated", "/account/alert-emails", None),
    ("PUT", "/account/alert-emails"): ("authenticated", "/account/alert-emails", {"enabled": False}),
    ("GET", "/filings/recent"): ("public", "/filings/recent", None),
    # Cached filings are public; refresh=true (an on-demand BSE fetch) is paid.
    ("GET", "/filings/{symbol}"): ("paid", "/filings/ABC?refresh=true", None),
    ("GET", "/filings/{symbol}/history"): ("paid", "/filings/ABC/history", None),
    ("GET", "/market-data/{symbol}"): ("authenticated", "/market-data/ABC", None),
    ("GET", "/ingestion/stats"): ("admin", "/ingestion/stats", None),
    ("GET", "/ops/metrics"): ("admin", "/ops/metrics", None),
    ("POST", "/feedback"): ("public", "/feedback", {"message": "Looks wrong for ABC"}),
    ("GET", "/feedback"): ("admin", "/feedback", None),
    ("PATCH", "/feedback/{feedback_id}"): ("admin", "/feedback/1", {"status": "resolved"}),
    ("GET", "/feedback/{feedback_id}/events"): ("admin", "/feedback/1/events", None),
    ("GET", "/feedback/status/{tracking_token}"): ("public", "/feedback/status/tok", None),
    ("GET", "/governance/review/{symbol}/{filing_date}"): (
        "admin",
        "/governance/review/ABC/2026-01-01",
        None,
    ),
    ("GET", "/governance/overrides"): ("admin", "/governance/overrides", None),
    ("PUT", "/governance/overrides"): (
        "admin",
        "/governance/overrides",
        {"symbol": "ABC", "filing_date": "2026-01-01T00:00:00"},
    ),
    ("DELETE", "/governance/overrides/{symbol}/{filing_date}"): (
        "admin",
        "/governance/overrides/ABC/2026-01-01",
        None,
    ),
}

# A guard rejection is the status AND the guard's own message. Matching on the
# message keeps a handler's legitimate 401 (wrong password on /auth/login) or
# 403 from being mistaken for a tier decision.
GUARD_MESSAGES = {
    401: ("Authorization token required", "Invalid session", "Session expired", "Email not verified"),
    402: ("requires an active subscription",),
    403: ("requires an admin account",),
}


def _guard_rejection(response):
    """Return 401/402/403 when an auth guard rejected the call, else None."""

    messages = GUARD_MESSAGES.get(response.status_code)
    if not messages:
        return None
    try:
        detail = str(response.json().get("detail", ""))
    except ValueError:
        return None
    return response.status_code if any(m in detail for m in messages) else None


# Guard outcome each identity must get, per tier. None means "let through".
EXPECTED = {
    "public": {None: None, "free-token": None, "paid-token": None, "admin-token": None},
    "authenticated": {None: 401, "free-token": None, "paid-token": None, "admin-token": None},
    "paid": {None: 401, "free-token": 402, "paid-token": None, "admin-token": None},
    "admin": {None: 401, "free-token": 403, "paid-token": 403, "admin-token": None},
}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    real_connect = socket.socket.connect

    def loopback_only(self, address):
        # The event loop's self-pipe connects over loopback on Windows.
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost") and not isinstance(address, (str, bytes)):
            raise OSError(f"network disabled in tests: {address!r}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)


@pytest.fixture
def db(monkeypatch):
    sessions = {hash_session_token(token): dict(row) for token, row in SESSIONS.items()}
    fake = MagicMock(name="db")
    fake.get_session.side_effect = lambda token_hash: (
        dict(sessions[token_hash]) if token_hash in sessions else None
    )
    monkeypatch.setattr(api_module, "DB_MANAGER", fake)
    monkeypatch.setattr(api_module, "ADMIN_EMAILS", [])
    # Billing configured with dummy keys, so the session guard (not the
    # "Billing not configured" 503) decides who may call the billing routes.
    monkeypatch.setattr(api_module, "RAZORPAY_KEY_ID", "rzp_test_dummy")
    monkeypatch.setattr(api_module, "RAZORPAY_KEY_SECRET", "dummy-secret")
    return fake


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    storage = MemoryWatchlistStorage()
    # The route and the engine must share one store, as they do in app.py.
    monkeypatch.setattr(api_module, "watch_storage", storage)
    monkeypatch.setattr(api_module, "alert_engine", AlertEngine(storage))
    # Context manager: runs startup/shutdown (lifespan) like a real server.
    with TestClient(api_module.app, raise_server_exceptions=False) as test_client:
        yield test_client


def _call(client, method, url, body=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.request(method, url, json=body, headers=headers)


def test_every_route_has_a_tier():
    actual = {
        (method, route.path)
        for route in api_module.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert actual == set(ROUTES), (
        "Route table drifted. New routes need a deliberate tier "
        f"(docs/guides/API.md 'API and security model'): missing={sorted(actual - set(ROUTES))} "
        f"stale={sorted(set(ROUTES) - actual)}"
    )


@pytest.mark.parametrize("identity", [None, "free-token", "paid-token", "admin-token"])
@pytest.mark.parametrize("route", sorted(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_tier_matrix(client, route, identity):
    tier, url, body = ROUTES[route]
    response = _call(client, route[0], url, body, identity)
    assert _guard_rejection(response) == EXPECTED[tier][identity], response.text


def test_cached_filing_is_public(client, db):
    db.get_latest_filing.return_value = {
        "symbol": "ABC",
        "filing_date": "2026-01-01T00:00:00",
        "total_debt": 10.0,
    }
    db.get_filing_evaluation.return_value = None
    response = _call(client, "GET", "/filings/ABC")
    assert _guard_rejection(response) is None, response.text


@pytest.mark.parametrize(
    "header",
    ["paid-token", "Token paid-token", "Bearer", "Bearer ", "Bearer unknown-token"],
)
def test_malformed_or_unknown_credentials_are_rejected(client, header):
    response = client.get("/auth/me", headers={"Authorization": header})
    assert _guard_rejection(response) == 401


def test_expired_session_is_rejected_and_revoked(client, db):
    response = _call(client, "GET", "/auth/me", token="expired-token")
    assert response.status_code == 401
    assert response.json()["detail"] == "Session expired"
    db.delete_session.assert_called_once_with(hash_session_token("expired-token"))


def test_raw_token_never_reaches_the_database(client, db):
    _call(client, "GET", "/auth/me", token="paid-token")
    passed = [call.args[0] for call in db.get_session.call_args_list]
    assert passed == [hash_session_token("paid-token")]
    assert "paid-token" not in passed


def test_halal_score_serializes_insufficient_data_as_null(client):
    response = _call(client, "POST", "/halal-score", SCORE_BODY)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_compliant"] is None
    assert body["screen_verdict"] == "insufficient-data"


def test_halal_score_serializes_a_conclusive_verdict(client):
    snapshot = {
        "symbol": "ABC",
        "filing_date": "2026-01-01T00:00:00",
        "total_debt": 10.0,
        "cash_equiv": 10.0,
        "revenue": 1000.0,
        "interest_income": 1.0,
        "dividend_income": 1.0,
        "non_permissible_income": 1.0,
        "accounts_receivable": 10.0,
        "liquid_assets": 10.0,
    }
    response = _call(
        client,
        "POST",
        "/halal-score",
        {"snapshot": snapshot, "market_data": {"market_cap": 1000.0}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_compliant"] is True
    assert body["screen_verdict"] == "compliant"


@pytest.mark.parametrize(
    "snapshot_patch",
    [
        {"interest_income": True},  # booleans are not amounts
        {"unexpected_field": 1},  # extra="forbid"
        {"filing_date": "not-a-date"},
    ],
)
def test_halal_score_rejects_invalid_payloads(client, snapshot_patch):
    body = {
        "snapshot": {**SCORE_BODY["snapshot"], **snapshot_patch},
        "market_data": SCORE_BODY["market_data"],
    }
    response = _call(client, "POST", "/halal-score", body)
    assert response.status_code == 422


def test_missing_body_field_is_422(client):
    response = _call(client, "POST", "/auth/login", {"email": "a@example.invalid"})
    assert response.status_code == 422


def test_security_headers_on_every_response(client):
    for url in ("/health", "/does-not-exist"):
        response = client.get(url)
        for header, value in api_module.SECURITY_HEADERS.items():
            assert response.headers.get(header) == value, (url, header)
    # HSTS only when TLS terminates in front of the API.
    assert "strict-transport-security" not in client.get("/health").headers


def test_cors_preflight_allows_only_configured_origins(client):
    allowed = (api_module.ALLOWED_ORIGINS or api_module.DEFAULT_ALLOWED_ORIGINS)[0]
    ok = client.options(
        "/auth/me",
        headers={"Origin": allowed, "Access-Control-Request-Method": "GET"},
    )
    assert ok.status_code == 200
    assert ok.headers.get("access-control-allow-origin") == allowed
    assert ok.headers.get("access-control-allow-credentials") == "true"

    evil = client.options(
        "/auth/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert evil.headers.get("access-control-allow-origin") is None


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(api_module, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setitem(api_module.RATE_LIMIT_RULES, "public_compute", RateLimitRule(2, 60.0))
    statuses = [_call(client, "POST", "/halal-score", SCORE_BODY).status_code for _ in range(3)]
    assert statuses[:2] == [200, 200]
    assert statuses[2] == 429
    limited = _call(client, "POST", "/halal-score", SCORE_BODY)
    assert int(limited.headers["Retry-After"]) >= 1


def test_watchlist_is_scoped_to_the_session_not_the_path(client):
    added = _call(
        client,
        "POST",
        "/watchlist",
        {"user_id": "user:3", "symbol": "abc"},
        token="paid-token",
    )
    assert added.status_code == 200, added.text
    # The body's user_id is ignored: the entry belongs to the caller.
    assert added.json()["user_id"] == "user:2"

    own = _call(client, "GET", "/watchlist/anything", token="paid-token").json()
    assert [(e["user_id"], e["symbol"]) for e in own] == [("user:2", "ABC")]

    # Another subscriber asking for user 2's list by path still gets only their own.
    other = _call(client, "GET", "/watchlist/user:2", token="paid-token-2").json()
    assert other == []


# --- /alerts/check: verdict from the stored evaluation, caller-scoped ---------

FILING_DATE = datetime(2026, 1, 1)


def _stored(verdict, is_compliant, day=1, open_issues=False):
    return {
        "filing_date": FILING_DATE,
        "evaluated_at": datetime(2026, 2, day),
        "verdict": verdict,
        "is_compliant": is_compliant,
        "open_issues": open_issues,
    }


@pytest.fixture
def alerts(client, db, monkeypatch):
    """Watch entries for the paid caller (user 2) and another subscriber (user 3)."""

    storage = api_module.watch_storage
    storage.add(WatchEntry(user_id=2, symbol="ABC"))
    storage.add(WatchEntry(user_id=3, symbol="ABC", last_is_compliant=True))

    def explode(*args, **kwargs):
        raise AssertionError("/alerts/check must not fetch, re-evaluate or send mail")

    for name in ("_market_data_for_filing", "_fetch_latest_filing_from_bse", "_ensure_filing_evaluation"):
        monkeypatch.setattr(api_module, name, explode)
    monkeypatch.setattr(api_module, "send_email", explode)
    assert not hasattr(api_module, "email_notifier")  # the operator-mail path is gone (D-031)

    def check(body=None, token="paid-token"):
        return _call(client, "POST", "/alerts/check", body or {"symbol": "ABC"}, token)

    def row(user_id):
        return storage.rows[(user_id, "ABC", "compliance_flip")]

    return check, storage, row


def test_alert_flip_uses_the_stored_verdict_and_only_the_caller(alerts):
    check, storage, row = alerts
    storage.filings["ABC"] = _stored("compliant", True)
    assert check().json() == []  # seeds the caller's baseline, silently
    assert row(2)["last_is_compliant"] is True and row(2)["notified_is_compliant"] is True

    storage.filings["ABC"] = _stored("non-compliant", False, day=2)
    events = check().json()
    assert [(e["user_id"], e["symbol"]) for e in events] == [("user:2", "ABC")]
    # Observation only: the flip is now a pending alert email for the scheduler.
    assert row(2)["last_is_compliant"] is False and row(2)["notified_is_compliant"] is True
    # The other subscriber's row is never read or moved by this caller.
    assert row(3)["last_is_compliant"] is True

    assert check().json() == []  # unchanged verdict: no second event


def test_alert_ignores_a_caller_supplied_verdict(alerts):
    check, storage, row = alerts
    storage.filings["ABC"] = _stored("compliant", True)
    check()
    response = check({"symbol": "ABC", "is_compliant": False})
    assert response.status_code == 200 and response.json() == []
    assert row(2)["last_is_compliant"] is True


@pytest.mark.parametrize(
    "record",
    [
        None,  # unknown symbol
        _stored(None, None),  # newest filing not evaluated
        _stored("needs-review", None),
        _stored("insufficient-data", None),
        _stored("compliant", False),  # inconsistent pair
        _stored("non-compliant", True),
        _stored("compliant", None),
        _stored("non-compliant", False, open_issues=True),  # open quality issue
    ],
)
def test_alert_without_a_conclusive_stored_verdict_changes_nothing(alerts, record):
    check, storage, row = alerts
    storage.filings["ABC"] = record
    response = check()
    assert response.status_code == 200 and response.json() == []
    assert row(2)["last_is_compliant"] is None and row(3)["last_is_compliant"] is True


def test_alert_lookup_failure_is_503_and_changes_nothing(alerts):
    check, storage, row = alerts
    storage.filings["ABC"] = RuntimeError("db down")
    assert check().status_code == 503
    assert row(2)["last_is_compliant"] is None and row(3)["last_is_compliant"] is True


def test_alert_normalises_the_symbol(alerts):
    check, storage, row = alerts
    storage.filings["ABC"] = _stored("compliant", True)
    check({"symbol": "  abc "})
    assert row(2)["last_is_compliant"] is True


def test_alert_blank_symbol_is_422(alerts):
    check, _, _ = alerts
    assert check({"symbol": "   "}).status_code == 422


def test_alert_check_is_rate_limited_per_user(alerts, monkeypatch):
    check, _, _ = alerts
    monkeypatch.setattr(api_module, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setitem(api_module.RATE_LIMIT_RULES, "metered", RateLimitRule(2, 60.0))
    assert [check().status_code for _ in range(3)] == [200, 200, 429]


def test_alert_email_setting_is_the_callers_own(client):
    storage = api_module.watch_storage
    assert _call(client, "GET", "/account/alert-emails", token="free-token").json() == {"enabled": True}
    response = _call(client, "PUT", "/account/alert-emails", {"enabled": False}, "free-token")
    assert response.json() == {"enabled": False}
    assert storage.users[1]["alert_emails"] is False and 2 not in storage.users  # the session's user only
    assert _call(client, "GET", "/account/alert-emails", token="paid-token").json() == {"enabled": True}
    # No other account can be named: the body takes only the flag.
    assert _call(client, "PUT", "/account/alert-emails", {"enabled": True, "user_id": 2}, "free-token").status_code == 422


def test_watchlist_storage_failure_is_503_not_an_empty_list(client, monkeypatch):
    class Broken:
        def add(self, entry):
            raise RuntimeError("database down")

        def list(self, user_id):
            raise RuntimeError("database down")

    monkeypatch.setattr(api_module, "watch_storage", Broken())
    body = {"user_id": "x", "symbol": "abc", "trigger": "compliance_flip"}
    assert _call(client, "POST", "/watchlist", body, "paid-token").status_code == 503
    assert _call(client, "GET", "/watchlist/x", token="paid-token").status_code == 503
