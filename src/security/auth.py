"""Identity: who is calling. The request body never establishes identity; only a verified JWT does."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from src.config import Settings

ALGORITHM = "HS256"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. `user_id` is None for anonymous visitors (public knowledge only)."""

    user_id: str | None
    role: str = "anonymous"  # anonymous | merchant | operator

    @property
    def is_merchant(self) -> bool:
        return self.role == "merchant" and self.user_id is not None

    @property
    def is_operator(self) -> bool:
        return self.role == "operator" and self.user_id is not None

    def as_dict(self) -> dict[str, str | None]:
        return {"user_id": self.user_id, "role": self.role}

    @classmethod
    def from_dict(cls, data: dict[str, str | None] | None) -> Principal:
        data = data or {}
        return cls(user_id=data.get("user_id"), role=data.get("role") or "anonymous")


ANONYMOUS = Principal(user_id=None, role="anonymous")


class AuthError(Exception):
    pass


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(candidate.hex(), digest_hex)


def issue_token(settings: Settings, user_id: str, role: str) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_in = settings.jwt_expires_minutes * 60
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.resolved_jwt_secret(), algorithm=ALGORITHM), expires_in


def token_claims(settings: Settings, token: str) -> dict[str, object]:
    """Verified claims: signature, expiry, issuer, audience and required fields. Raises AuthError otherwise.

    This is the only token check in the service; revocation (`jti`) is checked by the caller against the store.
    Issuer and audience stop a token minted for another service that happens to share the secret from being
    accepted here.
    """
    try:
        return jwt.decode(
            token,
            settings.resolved_jwt_secret(),
            algorithms=[ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["iss", "aud", "sub", "exp", "role", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc


def client_ip(peer: str | None, forwarded_for: str | None, trusted_proxies: frozenset[str]) -> str:
    """The caller's address for rate limiting.

    `X-Forwarded-For` is honoured only when the direct peer is a configured proxy, and then read from the right,
    skipping trusted hops: the left-most entries are whatever the client chose to send.
    """
    address = peer or "unknown"
    if address not in trusted_proxies or not forwarded_for:
        return address
    for hop in reversed([h.strip() for h in forwarded_for.split(",") if h.strip()]):
        if hop not in trusted_proxies:
            return hop
    return address


class SlidingWindowRateLimiter:
    """Per-process throttle. A shared store (Redis) is required before running several replicas."""

    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()  # requests run on a thread pool

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.attempts:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory: forget keys whose window has fully passed
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window_seconds]:
                    del self._hits[stale]
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
