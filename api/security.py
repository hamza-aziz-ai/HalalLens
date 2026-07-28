#!/usr/bin/env python3
"""Security primitives for the HalalLens API.

Deliberately dependency-free (stdlib only) so the runtime image stays small and
the CI environment does not need extra wheels:

* password hashing  - versioned PBKDF2-HMAC-SHA256 with transparent upgrade of
  legacy hashes produced by the original 100k-iteration scheme.
* session tokens    - only a SHA-256 digest of the bearer token is persisted, so
  a database leak cannot be replayed against the API.
* rate limiting     - in-process sliding window used to blunt credential
  stuffing and abuse of the metered upstream data providers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple
from collections import defaultdict, deque

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000  # OWASP 2023 guidance for PBKDF2-HMAC-SHA256
PBKDF2_SALT_BYTES = 16
LEGACY_ITERATIONS = 100_000
LEGACY_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Return a versioned hash: ``pbkdf2_sha256$<iterations>$<salt>$<digest>``."""

    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return "$".join(
        (
            PBKDF2_ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
    )


def _verify_legacy(password: str, stored_hash: str) -> bool:
    """Verify the original ``base64(salt || pbkdf2_100k)`` format."""

    try:
        data = base64.b64decode(stored_hash.encode("ascii"))
    except Exception:
        return False
    if len(data) < LEGACY_SALT_BYTES + 16:
        return False
    salt = data[:LEGACY_SALT_BYTES]
    saved = data[LEGACY_SALT_BYTES:]
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, LEGACY_ITERATIONS
    )
    return hmac.compare_digest(saved, derived)


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Verify ``password`` against either the current or legacy hash format."""

    if not stored_hash:
        return False
    if not stored_hash.startswith(f"{PBKDF2_ALGORITHM}$"):
        return _verify_legacy(password, stored_hash)

    try:
        _, iterations_raw, salt_b64, digest_b64 = stored_hash.split("$", 3)
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except (ValueError, TypeError):
        return False
    if iterations <= 0 or not salt or not expected:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(derived, expected)


def needs_rehash(stored_hash: Optional[str]) -> bool:
    """True when ``stored_hash`` uses a weaker scheme than the current default."""

    if not stored_hash:
        return True
    if not stored_hash.startswith(f"{PBKDF2_ALGORITHM}$"):
        return True
    try:
        iterations = int(stored_hash.split("$", 2)[1])
    except (IndexError, ValueError):
        return True
    return iterations < PBKDF2_ITERATIONS


#: Pre-computed hash used to keep failed logins as expensive as successful ones
#: so response timing does not leak whether an email is registered.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def dummy_verify(password: str) -> None:
    """Burn the same CPU as a real verification (user-enumeration defence)."""

    verify_password(password or "", _DUMMY_HASH)


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256


def password_policy_error(password: Optional[str]) -> Optional[str]:
    """Return a human-readable reason the password is unacceptable, else None."""

    value = password or ""
    if len(value) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(value) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters"
    if value.lower() in _COMMON_PASSWORDS:
        return "Password is too common"
    if not any(char.isalpha() for char in value):
        return "Password must contain at least one letter"
    if not any(char.isdigit() for char in value):
        return "Password must contain at least one digit"
    return None


_COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "12345678",
    "123456789",
    "1234567890",
    "qwerty123",
    "iloveyou1",
    "letmein123",
    "admin12345",
    "halallens1",
}


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------

SESSION_TOKEN_BYTES = 32


def generate_session_token() -> str:
    """Return a fresh opaque bearer token (never persisted in this form)."""

    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Return the digest stored in ``user_sessions.token``."""

    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def redact_token(token: Optional[str]) -> str:
    if not token:
        return "<none>"
    if len(token) <= 8:
        return "<redacted>"
    return f"{token[:6]}...{token[-4:]}"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitRule:
    """Allow at most ``limit`` hits per ``window_seconds`` for one identity."""

    limit: int
    window_seconds: float

    def __post_init__(self) -> None:  # pragma: no cover - constructor guard
        if self.limit <= 0 or self.window_seconds <= 0:
            raise ValueError("RateLimitRule requires positive limit and window")


class SlidingWindowRateLimiter:
    """Thread-safe in-process sliding-window limiter.

    NOTE: state is per worker process. Running uvicorn with ``--workers N``
    multiplies the effective limit by ``N``. That is an accepted trade-off for
    the pilot; swap in a Redis-backed implementation of :meth:`check` before
    scaling horizontally.
    """

    def __init__(self, *, max_identities: int = 50_000) -> None:
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_identities = max_identities

    def check(
        self, bucket: str, identity: str, rule: RateLimitRule, *, now: Optional[float] = None
    ) -> Tuple[bool, float]:
        """Record a hit.

        Returns ``(allowed, retry_after_seconds)``. When ``allowed`` is False the
        hit is *not* recorded, so a throttled caller cannot extend its own
        penalty by hammering the endpoint.
        """

        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - rule.window_seconds
        key = (bucket, identity)
        with self._lock:
            if len(self._hits) > self._max_identities:
                self._evict_locked(cutoff)
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= rule.limit:
                retry_after = max(0.0, hits[0] + rule.window_seconds - timestamp)
                return False, retry_after
            hits.append(timestamp)
            return True, 0.0

    def reset(self, bucket: Optional[str] = None) -> None:
        """Clear recorded hits (used by tests and admin tooling)."""

        with self._lock:
            if bucket is None:
                self._hits.clear()
                return
            for key in [key for key in self._hits if key[0] == bucket]:
                self._hits.pop(key, None)

    def _evict_locked(self, cutoff: float) -> None:
        for key in [
            key
            for key, hits in self._hits.items()
            if not hits or hits[-1] <= cutoff
        ]:
            self._hits.pop(key, None)


__all__ = [
    "PBKDF2_ITERATIONS",
    "MIN_PASSWORD_LENGTH",
    "RateLimitRule",
    "SlidingWindowRateLimiter",
    "dummy_verify",
    "generate_session_token",
    "hash_password",
    "hash_session_token",
    "needs_rehash",
    "password_policy_error",
    "redact_token",
    "verify_password",
]
