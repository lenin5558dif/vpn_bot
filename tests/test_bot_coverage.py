"""Additional bot/main.py tests for uncovered admin actions."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_admin_actions_new_requests():
    from bot.main import admin_actions
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:req:new"
    callback.message = AsyncMock()
    callback.answer = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.list_requests = AsyncMock(return_value=[{"id": 1, "user_id": 1, "status": "new", "created_at": "x"}])
        await admin_actions(callback)

    callback.message.answer.assert_called()
    callback.answer.assert_called()


@pytest.mark.asyncio
async def test_admin_actions_all_requests():
    from bot.main import admin_actions
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:req:all"
    callback.message = AsyncMock()
    callback.answer = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.list_requests = AsyncMock(return_value=[])
        await admin_actions(callback)

    callback.message.answer.assert_called()


@pytest.mark.asyncio
async def test_admin_actions_peers():
    from bot.main import admin_actions
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:peers"
    callback.message = AsyncMock()
    callback.answer = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.list_peers = AsyncMock(return_value=[
            {"id": 1, "user_id": 1, "address": "10.0.0.2", "status": "active", "speed_limit_mbps": 20}
        ])
        await admin_actions(callback)

    assert callback.message.answer.call_count >= 1


@pytest.mark.asyncio
async def test_admin_actions_users():
    from bot.main import admin_actions
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:users"
    callback.message = AsyncMock()
    callback.answer = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.list_users = AsyncMock(return_value=[{"id": 1, "name": "U", "contact": "c"}])
        await admin_actions(callback)

    callback.message.answer.assert_called()


@pytest.mark.asyncio
async def test_admin_actions_health():
    from bot.main import admin_actions
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:health"
    callback.message = AsyncMock()
    callback.answer = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.health = AsyncMock(return_value={"status": "ok"})
        await admin_actions(callback)

    callback.message.answer.assert_called()


@pytest.mark.asyncio
async def test_admin_actions_unauthorized():
    from bot.main import admin_actions
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 999999
    callback.data = "admin:req:new"
    callback.answer = AsyncMock()

    await admin_actions(callback)
    callback.answer.assert_called_with("Нет доступа", show_alert=True)


@pytest.mark.asyncio
async def test_reject_unauthorized():
    from bot.main import reject_request
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 999999
    callback.data = "reject:1:2:333"
    callback.answer = AsyncMock()

    await reject_request(callback)
    callback.answer.assert_called_with("Нет прав", show_alert=True)


@pytest.mark.asyncio
async def test_handle_comment_with_comment():
    from bot.main import handle_comment
    message = AsyncMock()
    message.text = "some comment"
    message.from_user = MagicMock()
    message.from_user.id = 111
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"name": "Test", "contact": "t@m.com"})

    with patch("bot.main.backend") as mock_be:
        mock_be.create_user = AsyncMock(return_value={"id": 1})
        mock_be.create_request = AsyncMock(return_value={"id": 1})
        with patch("bot.main.bot") as mock_bot:
            mock_bot.send_message = AsyncMock()
            await handle_comment(message, state)

    # Verify comment was passed
    call_args = mock_be.create_request.call_args
    assert call_args.args[0]["comment"] == "some comment"


@pytest.mark.asyncio
async def test_approve_fetch_user_error():
    """Cover the except branch when fetching user for filename fails."""
    from bot.main import approve_request
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "approve:1:2:333"
    callback.answer = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.update_request = AsyncMock()
        mock_be.create_peer = AsyncMock(return_value={"id": 10})
        mock_be.get_config = AsyncMock(return_value="[Interface]\nPrivateKey=x")
        mock_be.get_user = AsyncMock(side_effect=Exception("network error"))
        with patch("bot.main.bot") as mock_bot:
            mock_bot.send_message = AsyncMock()
            mock_bot.send_document = AsyncMock()
            await approve_request(callback)

    callback.answer.assert_called_with("Одобрено")
