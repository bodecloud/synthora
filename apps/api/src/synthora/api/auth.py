"""Optional authentication (KTD 5): AUTH_MODE=none|session.

``none``  — every request maps to the default workspace, no credentials.
``session`` — register/login issue JWTs; API requests carry Bearer tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request
from synthora.api.settings import settings
from synthora.core.models import User


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 200_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def issue_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "username": user.username,
        "exp": int(time.time()) + settings.token_ttl_seconds,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def identity_from_token(token: Optional[str]) -> dict:
    """Resolve identity from a raw JWT (WebSocket query param or Bearer)."""
    if settings.auth_mode != "session":
        return {"user_id": None, "username": "anonymous", "workspace_id": "default"}
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        payload = decode_token(token.strip())
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc
    return {
        "user_id": payload["sub"],
        "username": payload["username"],
        "workspace_id": payload["sub"],  # one workspace per user
    }


async def current_identity(request: Request) -> dict:
    """Resolve the caller. In ``none`` mode everyone shares the default
    workspace; in ``session`` mode a valid Bearer token is required."""
    header = request.headers.get("Authorization", "")
    token = (
        header.removeprefix("Bearer ").strip()
        if header.startswith("Bearer ")
        else None
    )
    return identity_from_token(token)


Identity = Depends(current_identity)
