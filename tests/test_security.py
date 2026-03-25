import pytest
from datetime import timedelta
from jose import jwt

from app.config import get_settings
from app.security import (
    AdminUser,
    authenticate_admin,
    create_access_token,
    get_current_admin,
    get_password_hash,
    verify_password,
)


settings = get_settings()


def test_password_hash_and_verify():
    hashed = get_password_hash("mypassword")
    assert hashed != "mypassword"
    assert verify_password("mypassword", hashed)
    assert not verify_password("wrong", hashed)


def test_authenticate_admin_success():
    result = authenticate_admin("admin", "testpass")
    assert result is not None
    assert isinstance(result, AdminUser)
    assert result.username == "admin"
    assert result.role == "admin"


def test_authenticate_admin_wrong_username():
    result = authenticate_admin("notadmin", "testpass")
    assert result is None


def test_authenticate_admin_wrong_password():
    result = authenticate_admin("admin", "wrongpass")
    assert result is None


def test_create_access_token():
    token = create_access_token({"sub": "admin"})
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    assert payload["sub"] == "admin"
    assert "exp" in payload


def test_create_access_token_custom_expiry():
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(minutes=5))
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    assert payload["sub"] == "admin"


@pytest.mark.asyncio
async def test_get_current_admin_valid():
    token = create_access_token({"sub": "admin"})
    user = get_current_admin(token)
    assert user.username == "admin"


@pytest.mark.asyncio
async def test_get_current_admin_invalid_token():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        get_current_admin("invalid.token.here")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_admin_wrong_user():
    from fastapi import HTTPException
    token = create_access_token({"sub": "notadmin"})
    with pytest.raises(HTTPException):
        get_current_admin(token)


@pytest.mark.asyncio
async def test_get_current_admin_no_sub():
    from fastapi import HTTPException
    token = create_access_token({"data": "nosub"})
    with pytest.raises(HTTPException):
        get_current_admin(token)
