from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from app.settings import get_settings


class TokenRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)


def issue_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def user_from_authorization(authorization: str | None = Header(None)) -> str:
    settings = get_settings()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Authorization: Bearer <jwt>")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired. Sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Token missing sub")
    return str(user_id)
