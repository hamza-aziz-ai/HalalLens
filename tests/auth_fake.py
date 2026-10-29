"""In-memory stand-in for the auth surface of BSEDatabaseManager.

Mirrors the semantics of the real methods (google_sign_in, login_with_password,
issue_auth_token, complete_signup, complete_password_reset): matching by Google
subject only, single-use expiring proofs, verification and admin granted only
on proof, sessions revoked on reset. Locking is not modelled; the SQL holds the
user row FOR UPDATE.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now():
    return datetime.now(timezone.utc)


class AuthDB:
    def __init__(self):
        self.users: Dict[int, Dict[str, Any]] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.tokens: List[Dict[str, Any]] = []
        self.flows: List[Dict[str, Any]] = []
        self.next_id = 1

    # -- helpers for tests -------------------------------------------------
    def add_user(self, email, *, password_hash=None, provider="password", verified=False,
                 is_admin=False, google_sub=None, plan="free", subscription_status="inactive"):
        user = {
            "id": self.next_id,
            "email": email,
            "password_hash": password_hash,
            "provider": provider,
            "google_sub": google_sub,
            "full_name": None,
            "avatar_url": None,
            "is_admin": is_admin,
            "plan": plan,
            "subscription_status": subscription_status,
            "subscription_renewal": None,
            "trial_used": False,
            "email_verified_at": _now() if verified else None,
        }
        self.users[user["id"]] = user
        self.next_id += 1
        return user

    def by_email(self, email):
        return next((u for u in self.users.values() if u["email"] == email), None)

    # -- reads ---------------------------------------------------------------
    def get_user_by_email(self, email):
        user = self.by_email(email)
        return dict(user) if user else None

    def get_user_by_id(self, user_id):
        user = self.users.get(user_id)
        return dict(user) if user else None

    def get_session(self, digest):
        session = self.sessions.get(digest)
        if not session:
            return None
        user = self.users[session["user_id"]]
        return {**session, **{k: user[k] for k in (
            "email", "plan", "subscription_status", "subscription_renewal", "trial_used",
            "full_name", "avatar_url", "is_admin", "email_verified_at")}}

    # -- sessions ------------------------------------------------------------
    def create_user_session(self, digest, user_id, expires_at):
        self.sessions[digest] = {"token": digest, "user_id": user_id, "expires_at": expires_at}

    def delete_session(self, digest):
        self.sessions.pop(digest, None)

    def touch_user_login(self, user_id):
        self.users[user_id]["last_login"] = _now()

    # -- the real methods' semantics ------------------------------------------
    def google_sign_in(self, *, email, google_sub, full_name, avatar_url, admin_emails):
        user = next((u for u in self.users.values() if u["google_sub"] == google_sub), None)
        if user:
            if user["email"] == email:
                user["email_verified_at"] = user["email_verified_at"] or _now()
                user["is_admin"] = user["is_admin"] or email in admin_emails
            return "ok", dict(user)
        if self.by_email(email):
            return "email_in_use", None
        user = self.add_user(email, provider="google", verified=True, google_sub=google_sub,
                             is_admin=email in admin_emails, subscription_status="active")
        return "ok", dict(user)

    def login_with_password(self, *, email, check_password, rehash, session_digest, expires_at):
        user = self.by_email(email)
        if not check_password(user["password_hash"] if user else None):
            return "bad_credentials", None
        if not user["email_verified_at"]:
            return "unverified", dict(user)
        upgraded = rehash(user["password_hash"])
        if upgraded:
            user["password_hash"] = upgraded
        self.create_user_session(session_digest, user["id"], expires_at)
        return "ok", dict(user)

    def issue_auth_token(self, *, purpose, email, user_id, token_digest, expires_at):
        for token in self.tokens:
            if token["email"] == email and token["purpose"] == purpose and not token["consumed_at"]:
                token["consumed_at"] = _now()
        self.tokens.append({"purpose": purpose, "email": email, "user_id": user_id,
                            "digest": token_digest, "expires_at": expires_at, "consumed_at": None})

    def _consume(self, digest, purpose):
        for token in self.tokens:
            if (token["digest"] == digest and token["purpose"] == purpose
                    and not token["consumed_at"] and token["expires_at"] > _now()):
                token["consumed_at"] = _now()
                return token
        return None

    def complete_signup(self, *, token_digest, password_hash, admin_emails):
        token = self._consume(token_digest, "signup")
        if not token:
            return "invalid_token", None
        if self.by_email(token["email"]):
            return "email_in_use", None
        user = self.add_user(token["email"], password_hash=password_hash, verified=True,
                             is_admin=token["email"] in admin_emails)
        return "ok", dict(user)

    def complete_password_reset(self, *, token_digest, password_hash, admin_emails):
        token = self._consume(token_digest, "reset_password")
        if not token or not token["user_id"]:
            return "invalid_token", None
        user = self.users.get(token["user_id"])
        if not user or user["email"] != token["email"]:
            return "invalid_token", None
        user["password_hash"] = password_hash
        user["email_verified_at"] = user["email_verified_at"] or _now()
        user["is_admin"] = user["is_admin"] or user["email"] in admin_emails
        for digest in [d for d, s in self.sessions.items() if s["user_id"] == user["id"]]:
            del self.sessions[digest]
        for other in self.tokens:
            if other["user_id"] == user["id"] and not other["consumed_at"]:
                other["consumed_at"] = _now()
        return "ok", dict(user)

    # -- OAuth flows (D-021) -------------------------------------------------
    def _flows(self):
        return self.flows

    def create_oauth_flow(self, *, purpose, state_digest, browser_digest, expires_at,
                          redirect=None, user_id=None, session_digest=None):
        self._flows().append({
            "id": len(self._flows()) + 1, "purpose": purpose, "state": state_digest,
            "browser": browser_digest, "redirect": redirect, "user_id": user_id,
            "session": session_digest, "expires_at": expires_at, "callback_at": None,
            "completed_at": None, "google_sub": None, "code": None,
        })

    def consume_oauth_flow(self, *, state_digest, browser_digest):
        for flow in self._flows():
            if (flow["state"] == state_digest and flow["browser"] == browser_digest
                    and not flow["callback_at"] and flow["expires_at"] > _now()):
                flow["callback_at"] = _now()
                return {k: flow[k] for k in ("id", "purpose", "redirect", "user_id")}
        return None

    def record_link_identity(self, *, flow_id, google_sub, google_email, link_code_digest):
        flow = self._flows()[flow_id - 1]
        flow.update(google_sub=google_sub, google_email=google_email, code=link_code_digest)

    def complete_google_link(self, *, link_code_digest, user_id, session_digest):
        flow = next((f for f in self._flows() if f["code"] == link_code_digest and f["purpose"] == "link"
                     and f["callback_at"] and not f["completed_at"] and f["expires_at"] > _now()), None)
        if (not flow or flow["user_id"] != user_id or flow["session"] != session_digest
                or session_digest not in self.sessions):
            return "invalid", None
        owner = next((u for u in self.users.values() if u["google_sub"] == flow["google_sub"]), None)
        if owner and owner["id"] != user_id:
            return "conflict", None
        user = self.users[user_id]
        if user["google_sub"] and user["google_sub"] != flow["google_sub"]:
            return "already_linked", None
        user["google_sub"] = flow["google_sub"]
        flow["completed_at"] = _now()
        return "ok", dict(user)
