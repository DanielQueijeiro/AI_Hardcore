"""Identity: who is calling. The request body never establishes identity; only a verified JWT does."""

from __future__ import annotations

import hashlib
import hmac
import secrets
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
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.resolved_jwt_secret(), algorithm=ALGORITHM), expires_in


def token_claims(settings: Settings, token: str) -> dict[str, object]:
    """Verified claims (signature, expiry, required fields). Raises AuthError otherwise."""
    try:
        return jwt.decode(
            token,
            settings.resolved_jwt_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "role", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc


def verify_token(settings: Settings, token: str) -> Principal:
    try:
        payload = jwt.decode(
            token,
            settings.resolved_jwt_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "role"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    role = payload["role"]
    if role not in ("merchant", "operator"):
        raise AuthError("unknown role")
    return Principal(user_id=str(payload["sub"]), role=role)


class SlidingWindowRateLimiter:
    """Per-process login throttle. A shared store (Redis) is required before running several replicas."""

    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.attempts:
            return False
        hits.append(now)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
