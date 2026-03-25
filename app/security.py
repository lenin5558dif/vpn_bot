from datetime import datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

from app.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

JWT_ISSUER = "vpn-admin-api"
JWT_AUDIENCE = "vpn-admin"


class AdminUser:
    def __init__(self, username: str):
        self.username = username
        self.role = "admin"


settings = get_settings()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def authenticate_admin(username: str, password: str) -> AdminUser | None:
    if username != settings.admin_username:
        return None
    if not settings.admin_password_hash:
        raise RuntimeError(
            "ADMIN_PASSWORD_HASH must be set. Generate with: "
            "python3 -c \"from passlib.context import CryptContext; "
            "print(CryptContext(schemes=['bcrypt']).hash('your_password'))\""
        )
    if not pwd_context.verify(password, settings.admin_password_hash):
        return None
    return AdminUser(username=username)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=1))
    to_encode.update({"exp": expire, "iss": JWT_ISSUER, "aud": JWT_AUDIENCE})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_alg)


def get_current_admin(token: Annotated[str, Depends(oauth2_scheme)]) -> AdminUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_alg],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.InvalidTokenError:
        raise credentials_exception

    if username != settings.admin_username:
        raise credentials_exception
    return AdminUser(username=username)
