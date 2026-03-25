import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Set test env BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.sqlite"
os.environ["JWT_SECRET"] = "test-secret-key-for-jwt-tokens-32b"
os.environ["JWT_ALG"] = "HS256"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpass"
os.environ["ADMIN_PASSWORD_HASH"] = ""
os.environ["ENCRYPTION_KEY"] = "VGVzdEtleUZvclRlc3RpbmcxMjM0NTY3ODkwYWJjZGU="  # will be overridden
os.environ["BOT_API_KEY"] = "test-bot-api-key"
os.environ["BOT_TOKEN"] = "000000000:AAFakeTokenForTesting"
os.environ["ADMIN_IDS"] = "123456789"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["WG_INTERFACE"] = "wg0"
os.environ["WG_ENDPOINT"] = "test.example.com:51820"
os.environ["WG_NETWORK"] = "10.10.0.0/24"
os.environ["SERVER_PUBLIC_KEY"] = "dGVzdHB1YmxpY2tleWZvcnRlc3Rpbmc9"

# Generate a valid Fernet key for tests
from cryptography.fernet import Fernet

TEST_FERNET_KEY = Fernet.generate_key().decode()
os.environ["ENCRYPTION_KEY"] = TEST_FERNET_KEY

# Clear lru_cache so test settings take effect
from app.config import get_settings

get_settings.cache_clear()

from app.database import engine, SessionLocal, init_db
from app.main import app
from app.security import create_access_token


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with SessionLocal() as s:
        yield s


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def admin_token():
    return create_access_token({"sub": "admin"})


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def bot_headers():
    return {"X-Bot-Api-Key": "test-bot-api-key"}
