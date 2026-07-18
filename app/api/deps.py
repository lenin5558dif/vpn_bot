import hmac
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.security import AdminUser, JWT_AUDIENCE, JWT_ISSUER, get_current_admin

DBSession = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[AdminUser, Depends(get_current_admin)]

settings = get_settings()


async def verify_bot_api_key(x_bot_api_key: str = Header(...)) -> None:
    if not settings.bot_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot API key not configured",
        )
    if not hmac.compare_digest(x_bot_api_key, settings.bot_api_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid bot API key")


BotKeyDep = Annotated[None, Depends(verify_bot_api_key)]


async def get_admin_or_bot(
    authorization: str | None = Header(default=None),
    x_bot_api_key: str | None = Header(default=None),
) -> AdminUser:
    if settings.bot_api_key and x_bot_api_key and hmac.compare_digest(x_bot_api_key, settings.bot_api_key):
        return AdminUser(username="bot")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_alg],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    username: str | None = payload.get("sub")
    if username != settings.admin_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AdminUser(username=username)


AdminOrBotDep = Annotated[AdminUser, Depends(get_admin_or_bot)]
