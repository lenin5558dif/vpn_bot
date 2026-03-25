import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.deps import verify_bot_api_key


@pytest.mark.asyncio
async def test_verify_bot_api_key_valid():
    original = deps.settings.bot_api_key
    deps.settings.bot_api_key = "test-bot-api-key"
    try:
        await verify_bot_api_key("test-bot-api-key")
    finally:
        deps.settings.bot_api_key = original


@pytest.mark.asyncio
async def test_verify_bot_api_key_invalid():
    original = deps.settings.bot_api_key
    deps.settings.bot_api_key = "test-bot-api-key"
    try:
        with pytest.raises(HTTPException) as exc_info:
            await verify_bot_api_key("wrong-key")
        assert exc_info.value.status_code == 403
    finally:
        deps.settings.bot_api_key = original


@pytest.mark.asyncio
async def test_verify_bot_api_key_empty_config():
    original = deps.settings.bot_api_key
    deps.settings.bot_api_key = ""
    try:
        with pytest.raises(HTTPException) as exc_info:
            await verify_bot_api_key("anykey")
        assert exc_info.value.status_code == 503
    finally:
        deps.settings.bot_api_key = original
