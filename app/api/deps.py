import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.security import get_current_admin, AdminUser

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
