"""Auth hardening (D-020): email-first sign-up, password reset, no admin rights
or Google linking from an unproven email. Handlers are called directly against
an in-memory DB (tests/auth_fake.py); outgoing mail is captured."""

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.security import hash_session_token
from tests.auth_fake import AuthDB

# `api.app` the attribute is the FastAPI instance (api/__init__.py); load the module.
api_module = importlib.import_module("api.app")

ADMIN = "owner@example.com"
PASSWORD = "StrongPass123!"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(monkeypatch):
    fake = AuthDB()
    monkeypatch.setattr(api_module, "_get_db", lambda: fake)
    monkeypatch.setattr(api_module, "ADMIN_EMAILS", [ADMIN])
    monkeypatch.setattr(api_module, "FRONTEND_BASE_URL", "https://app.example.test")
    return fake


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(api_module, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def _link_token(body, param):
    """Token from the emailed link: it must sit in the URL fragment."""

    url = next(word for word in body.split() if word.startswith("https://app.example.test/"))
    parts = urlsplit(url)
    assert not parts.query, "proofs must never travel in the query string"
    return parse_qs(parts.fragment)[param][0]


def _register(email):
    return _run(api_module.auth_register(api_module.RegisterRequest(email=email)))


def _confirm(token, password=PASSWORD):
    return _run(api_module.auth_signup_confirm(api_module.TokenPasswordRequest(token=token, password=password)))


def _reset(token, password=PASSWORD):
    return _run(api_module.auth_password_reset(api_module.TokenPasswordRequest(token=token, password=password)))


def _login(email, password=PASSWORD):
    return _run(api_module.auth_login(api_module.LoginRequest(email=email, password=password)))


def _me(token):
    return _run(api_module.auth_me(authorization=f"Bearer {token}"))


# ---------------------------------------------------------------------------
# Email-first sign-up
# ---------------------------------------------------------------------------


def test_signup_creates_a_verified_account_only_from_the_emailed_link(db, outbox):
    assert _register("New@Example.com") == api_module.ACCOUNT_EMAIL_ACCEPTED
    assert db.get_user_by_email("new@example.com") is None  # nothing until the link
    (to, _subject, body), = outbox
    assert to == "new@example.com" and "/verify/#signup=" in body
    token = _link_token(body, "signup")
    assert db.tokens[0]["digest"] == hash_session_token(token)  # digest only
    assert token not in str(db.tokens)

    response = _confirm(token)
    assert response.user.email == "new@example.com" and response.user.email_verified
    assert _me(response.token).email_verified

    with pytest.raises(HTTPException) as reuse:  # single use
        _confirm(token)
    assert reuse.value.status_code == 400


def test_register_no_longer_accepts_a_password():
    # Pre-registration with a password the attacker knows is no longer possible.
    with pytest.raises(ValidationError):
        api_module.RegisterRequest(email="victim@example.com", password=PASSWORD)


def test_admin_address_becomes_admin_only_after_proving_the_mailbox(db, outbox):
    _register(ADMIN)
    assert db.get_user_by_email(ADMIN) is None
    response = _confirm(_link_token(outbox[0][2], "signup"))
    assert response.user.is_admin is True


def test_expired_signup_link_is_rejected(db, outbox):
    _register("late@example.com")
    token = _link_token(outbox[0][2], "signup")
    db.tokens[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(HTTPException) as excinfo:
        _confirm(token)
    assert excinfo.value.status_code == 400


def test_only_the_latest_link_works(db, outbox, monkeypatch):
    monkeypatch.setattr(api_module, "RATE_LIMIT_ENABLED", False)
    _register("twice@example.com")
    _register("twice@example.com")
    first, second = (_link_token(body, "signup") for _, _, body in outbox)
    with pytest.raises(HTTPException):
        _confirm(first)
    assert _confirm(second).user.email == "twice@example.com"


def test_signup_link_cannot_be_used_as_a_reset_link(db, outbox):
    user = db.add_user("someone@example.com", password_hash=api_module._hash_password("Old-pass-123!"), verified=True)
    _register("fresh@example.com")
    token = _link_token(outbox[0][2], "signup")
    with pytest.raises(HTTPException):
        _reset(token)
    assert db.users[user["id"]]["password_hash"]  # untouched


def test_weak_password_is_refused_before_the_link_is_spent(db, outbox):
    _register("weak@example.com")
    token = _link_token(outbox[0][2], "signup")
    with pytest.raises(HTTPException) as excinfo:
        _confirm(token, password="short")
    assert excinfo.value.status_code == 400
    assert _confirm(token).user.email == "weak@example.com"


def test_answer_and_mail_failure_do_not_reveal_anything(db, monkeypatch):
    def broken(to, subject, body):
        raise OSError("smtp down")

    monkeypatch.setattr(api_module, "send_email", broken)
    db.add_user("exists@example.com", password_hash="x", verified=True)
    monkeypatch.setattr(api_module, "RATE_LIMIT_ENABLED", False)
    assert _register("exists@example.com") == _register("missing@example.com")


def test_one_address_cannot_be_flooded(db, outbox):
    _register("flood@example.com")
    with pytest.raises(HTTPException) as excinfo:  # 60 s cooldown per address
        _register("flood@example.com")
    assert excinfo.value.status_code == 429
    assert len(outbox) == 1


# ---------------------------------------------------------------------------
# Existing accounts: reset / recovery
# ---------------------------------------------------------------------------


def test_registering_an_existing_address_sends_a_reset_link_instead(db, outbox):
    db.add_user("taken@example.com", password_hash=api_module._hash_password("Attacker-pass-1!"))
    _register("taken@example.com")
    body = outbox[0][2]
    assert "/reset/#reset=" in body and "/verify/" not in body


def test_reset_replaces_a_pre_registered_password_and_revokes_its_sessions(db, outbox):
    # A legacy account someone else pre-registered with this address.
    victim = db.add_user("victim@example.com", password_hash=api_module._hash_password("Attacker-pass-1!"))
    db.create_user_session("attacker-session", victim["id"], datetime.now(timezone.utc) + timedelta(days=1))

    _run(api_module.auth_password_forgot(api_module.RegisterRequest(email="victim@example.com")))
    assert _reset(_link_token(outbox[0][2], "reset")) == {"status": "password_reset"}

    assert db.sessions == {}  # every session revoked, no new one issued
    assert db.users[victim["id"]]["email_verified_at"]
    with pytest.raises(HTTPException) as old:
        _login("victim@example.com", "Attacker-pass-1!")
    assert old.value.status_code == 401
    assert _login("victim@example.com").user.email_verified


def test_reset_grants_admin_to_a_proven_admin_address(db, outbox):
    owner = db.add_user(ADMIN, password_hash=api_module._hash_password("Old-pass-123!"))
    _run(api_module.auth_password_forgot(api_module.RegisterRequest(email=ADMIN)))
    _reset(_link_token(outbox[0][2], "reset"))
    assert db.users[owner["id"]]["is_admin"] is True


def test_google_only_account_never_gains_a_password_by_email(db, outbox):
    db.add_user("g@example.com", provider="google", verified=True, google_sub="sub-g")
    _run(api_module.auth_password_forgot(api_module.RegisterRequest(email="g@example.com")))
    (_to, subject, body), = outbox
    assert "Google" in subject and "#reset=" not in body
    assert db.tokens == []


# ---------------------------------------------------------------------------
# Login and sessions
# ---------------------------------------------------------------------------


def test_unverified_account_cannot_sign_in(db):
    db.add_user("legacy@example.com", password_hash=api_module._hash_password(PASSWORD))
    with pytest.raises(HTTPException) as excinfo:
        _login("legacy@example.com")
    assert excinfo.value.status_code == 403
    assert "Forgot password" in excinfo.value.detail
    with pytest.raises(HTTPException) as wrong:  # wrong password says nothing more
        _login("legacy@example.com", "Wrong-pass-123!")
    assert wrong.value.status_code == 401
    assert db.sessions == {}


def test_unknown_address_and_google_only_account_get_the_same_answer(db):
    db.add_user("g@example.com", provider="google", verified=True, google_sub="s")
    for email in ("nobody@example.com", "g@example.com"):
        with pytest.raises(HTTPException) as excinfo:
            _login(email)
        assert excinfo.value.status_code == 401


def test_session_of_an_unverified_account_fails_closed(db):
    user = db.add_user("old@example.com", password_hash="x", is_admin=True)
    token, _ = api_module._issue_session(user["id"])
    for call in (lambda: _me(token), lambda: api_module._require_admin(f"Bearer {token}", "Governance")):
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "Email not verified"


def test_admin_address_is_not_promoted_by_login_me_or_admin_checks(db):
    user = db.add_user(ADMIN, password_hash=api_module._hash_password(PASSWORD), verified=True)
    token = _login(ADMIN).token
    assert _me(token).is_admin is False
    with pytest.raises(HTTPException) as excinfo:
        api_module._require_admin(f"Bearer {token}", "Governance")
    assert excinfo.value.status_code == 403
    assert api_module._subscription_active(db.get_session(hash_session_token(token))) is False
    assert db.users[user["id"]]["is_admin"] is False


# ---------------------------------------------------------------------------
# Google sign-in
# ---------------------------------------------------------------------------


@pytest.fixture
def google(db, monkeypatch):
    """Drive Google sign-in and linking through HTTP, cookies included."""

    from fastapi.testclient import TestClient

    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(api_module, "GOOGLE_REDIRECT_URI", "https://app.example.test/auth/google/callback")
    monkeypatch.setattr(api_module, "_exchange_google_code", lambda code: {"access_token": "t"})
    profile = {}
    monkeypatch.setattr(api_module, "_fetch_google_profile", lambda token: dict(profile))

    class Google:
        def __init__(self):
            self.browser = TestClient(api_module.app, base_url="https://app.example.test")

        def new_browser(self):
            return TestClient(api_module.app, base_url="https://app.example.test")

        @staticmethod
        def state_of(url):
            return parse_qs(urlsplit(url).query)["state"][0]

        def start(self, browser=None):
            response = (browser or self.browser).get("/auth/google/start", follow_redirects=False)
            assert response.status_code == 307
            cookie = response.headers["set-cookie"].lower()
            assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie
            return self.state_of(response.headers["location"])

        def callback(self, state, browser=None, **claims):
            profile.clear()
            profile.update({"email_verified": True, "name": "N"}, **claims)
            return (browser or self.browser).get(
                f"/auth/google/callback?code=c&state={state}", follow_redirects=False
            )

        def sign_in(self, **claims):
            response = self.callback(self.start(), **claims)
            if response.status_code != 302:
                return response
            return parse_qs(urlsplit(response.headers["location"]).fragment)

    return Google()


@pytest.mark.parametrize("claim", [None, False, "true"])
def test_google_requires_an_explicitly_verified_email(google, claim):
    response = google.sign_in(email="g@example.com", sub="s1", email_verified=claim)
    assert response.status_code == 403


def test_google_creates_a_verified_account_and_proves_an_admin_address(db, google):
    fragment = google.sign_in(email=ADMIN, sub="s1")
    assert "token" in fragment
    user = db.get_user_by_email(ADMIN)
    assert user["email_verified_at"] and user["is_admin"] and user["password_hash"] is None


def test_google_never_attaches_to_an_existing_account_by_email(db, google):
    squatter = db.add_user("victim@example.com", password_hash=api_module._hash_password("Attacker-pass-1!"))
    fragment = google.sign_in(email="victim@example.com", sub="victim-sub")
    assert fragment == {"error": ["account_exists"]}
    assert db.users[squatter["id"]]["google_sub"] is None
    assert db.sessions == {}


def test_google_sign_in_verifies_an_already_linked_account(db, google):
    # The maintainer's case: password account linked to Google before this fix.
    owner = db.add_user(ADMIN, password_hash="x", google_sub="owner-sub")
    assert "token" in google.sign_in(email=ADMIN, sub="owner-sub")
    assert db.users[owner["id"]]["email_verified_at"] and db.users[owner["id"]]["is_admin"]


def test_linked_account_with_another_primary_email_is_not_verified_by_google(db, google):
    db.add_user("primary@example.com", password_hash="x", google_sub="sub-x")
    assert google.sign_in(email="other@gmail.com", sub="sub-x") == {"error": ["verify_email"]}
    assert db.sessions == {}


# ---------------------------------------------------------------------------
# Browser-bound, single-use OAuth flows (D-021)
# ---------------------------------------------------------------------------


def test_callback_in_another_browser_is_refused(db, google):
    # Login CSRF: an attacker's own state completed in the victim's browser.
    state = google.start()
    response = google.callback(state, browser=google.new_browser(), email="a@example.com", sub="s")
    assert response.status_code == 400
    assert db.sessions == {} and db.get_user_by_email("a@example.com") is None


def test_state_works_once(db, google):
    state = google.start()
    assert google.callback(state, email="a@example.com", sub="s").status_code == 302
    assert google.callback(state, email="a@example.com", sub="s").status_code == 400


def test_expired_flow_is_refused(db, google):
    state = google.start()
    db.flows[0]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert google.callback(state, email="a@example.com", sub="s").status_code == 400


# ---------------------------------------------------------------------------
# Explicit "Link Google account"
# ---------------------------------------------------------------------------


def _signed_in(db, email="me@example.com"):
    db.add_user(email, password_hash=api_module._hash_password(PASSWORD), verified=True)
    return _login(email).token


def _start_link(google, token, password=PASSWORD, browser=None):
    return (browser or google.browser).post(
        "/auth/google/link/start", json={"password": password},
        headers={"Authorization": f"Bearer {token}"},
    )


def _confirm_link(google, token, code):
    return google.browser.post(
        "/auth/google/link/confirm", json={"code": code},
        headers={"Authorization": f"Bearer {token}"},
    )


def _link_code(google, token, **claims):
    started = _start_link(google, token)
    assert started.status_code == 200
    response = google.callback(google.state_of(started.json()["url"]), **claims)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://app.example.test/account/#link=")
    return parse_qs(urlsplit(location).fragment)["link"][0]


def test_linking_needs_the_password_again_and_the_same_session(db, google):
    token = _signed_in(db)
    assert _start_link(google, token, password="Wrong-pass-123!").status_code == 401
    code = _link_code(google, token, email="me.other@gmail.com", sub="google-me")
    assert db.by_email("me@example.com")["google_sub"] is None  # callback links nothing
    other_session = _login("me@example.com").token
    assert _confirm_link(google, other_session, code).status_code == 400
    linked = _confirm_link(google, token, code)
    assert linked.status_code == 200 and linked.json()["google_linked"] is True
    user = db.by_email("me@example.com")
    assert user["google_sub"] == "google-me" and user["email"] == "me@example.com"
    assert _confirm_link(google, token, code).status_code == 400  # single use


def test_victim_cannot_be_linked_to_an_attackers_account(db, google):
    # The attacker starts a link from their account and sends the Google URL
    # to the victim, whose browser lacks the attacker's flow cookie.
    attacker = _signed_in(db, "attacker@example.com")
    started = _start_link(google, attacker)
    response = google.callback(google.state_of(started.json()["url"]), browser=google.new_browser(),
                               email="victim@gmail.com", sub="victim-sub")
    assert response.status_code == 400
    assert db.by_email("attacker@example.com")["google_sub"] is None


def test_a_google_account_links_to_one_hallens_account_only(db, google):
    db.add_user("first@example.com", password_hash="x", verified=True, google_sub="shared-sub")
    token = _signed_in(db)
    code = _link_code(google, token, email="shared@gmail.com", sub="shared-sub")
    assert _confirm_link(google, token, code).status_code == 409


def test_account_without_a_password_cannot_start_a_link(db, google):
    user = db.add_user("g@example.com", provider="google", verified=True, google_sub="g1")
    token, _ = api_module._issue_session(user["id"])
    assert _start_link(google, token).status_code == 400
