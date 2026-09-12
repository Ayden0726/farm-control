from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User, UserRole
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(creds.credentials)
        user_id = UUID(payload["sub"])
    except (ExpiredSignatureError, InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    if user.role == UserRole.viewer and request.method not in {"GET", "HEAD", "OPTIONS"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewer accounts are read-only")
    return user


WRITE_MAP = {
    "production": {UserRole.admin, UserRole.operator},
    "packing": {UserRole.admin, UserRole.operator, UserRole.packing},
    "inventory": {UserRole.admin, UserRole.operator, UserRole.inventory},
    "admin": {UserRole.admin},
}


def require_perm(scope: str):
    allowed = WRITE_MAP.get(scope, {UserRole.admin})

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role == UserRole.admin:
            return user
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return checker


def require_roles(*roles: UserRole):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role == UserRole.admin:
            return user
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return checker


async def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not creds:
        return None
    try:
        payload = decode_token(creds.credentials)
        return await db.get(User, UUID(payload["sub"]))
    except Exception:
        return None
