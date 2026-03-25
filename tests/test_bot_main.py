import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.main import (
    translit_slug,
    _format_requests,
    _format_peers,
    _format_users,
    _ensure_admin,
    ADMIN_IDS,
)


def test_translit_slug_cyrillic():
    assert translit_slug("Иван Петров") == "ivan_petrov"


def test_translit_slug_latin():
    assert translit_slug("John Doe") == "john_doe"


def test_translit_slug_mixed():
    assert translit_slug("Тест-test_123") == "test_test_123"


def test_translit_slug_empty():
    assert translit_slug("") == ""


def test_translit_slug_max_length():
    long_name = "А" * 100
    result = translit_slug(long_name)
    assert len(result) <= 50


def test_translit_slug_special_chars():
    assert translit_slug("Щёлково") == "schelkovo"


def test_format_requests_empty():
    assert _format_requests([]) == "Пусто"


def test_format_requests_with_data():
    reqs = [{"id": 1, "user_id": 2, "status": "new", "created_at": "2024-01-01"}]
    result = _format_requests(reqs)
    assert "#1" in result
    assert "user=2" in result


def test_format_requests_max_15():
    reqs = [{"id": i, "user_id": 1, "status": "new", "created_at": "x"} for i in range(20)]
    result = _format_requests(reqs)
    lines = result.strip().split("\n")
    assert len(lines) == 15


def test_format_peers_empty():
    assert _format_peers([]) == "Пусто"


def test_format_peers_with_data():
    peers = [{"id": 1, "user_id": 2, "address": "10.0.0.2", "status": "active", "speed_limit_mbps": 20}]
    result = _format_peers(peers)
    assert "#1" in result
    assert "20mbit" in result


def test_format_users_empty():
    assert _format_users([]) == "Пусто"


def test_format_users_with_data():
    users = [{"id": 1, "name": "Test", "contact": "test@mail.com"}]
    result = _format_users(users)
    assert "#1" in result
    assert "Test" in result


@pytest.mark.asyncio
async def test_ensure_admin_authorized():
    callback = MagicMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789  # in ADMIN_IDS
    result = await _ensure_admin(callback)
    assert result is True


@pytest.mark.asyncio
async def test_ensure_admin_unauthorized():
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 999999
    callback.answer = AsyncMock()
    result = await _ensure_admin(callback)
    assert result is False
    callback.answer.assert_called_once_with("Нет прав", show_alert=True)


@pytest.mark.asyncio
async def test_cmd_start():
    from bot.main import cmd_start
    message = AsyncMock()
    state = AsyncMock()
    await cmd_start(message, state)
    state.clear.assert_called_once()
    message.answer.assert_called_once()
    state.set_state.assert_called_once()


@pytest.mark.asyncio
async def test_handle_name():
    from bot.main import handle_name
    message = AsyncMock()
    message.text = "Иван Петров"
    state = AsyncMock()
    await handle_name(message, state)
    state.update_data.assert_called_once_with(name="Иван Петров")
    state.set_state.assert_called_once()


@pytest.mark.asyncio
async def test_handle_name_no_text():
    from bot.main import handle_name
    message = AsyncMock()
    message.text = None
    state = AsyncMock()
    await handle_name(message, state)
    message.answer.assert_called_once_with("Пожалуйста, отправь текстовое сообщение.")
    state.update_data.assert_not_called()


@pytest.mark.asyncio
async def test_handle_contact():
    from bot.main import handle_contact
    message = AsyncMock()
    message.text = "test@mail.com"
    state = AsyncMock()
    await handle_contact(message, state)
    state.update_data.assert_called_once_with(contact="test@mail.com")


@pytest.mark.asyncio
async def test_handle_contact_no_text():
    from bot.main import handle_contact
    message = AsyncMock()
    message.text = None
    state = AsyncMock()
    await handle_contact(message, state)
    message.answer.assert_called_once_with("Пожалуйста, отправь текстовое сообщение.")


@pytest.mark.asyncio
async def test_handle_comment_no_text():
    from bot.main import handle_comment
    message = AsyncMock()
    message.text = None
    state = AsyncMock()
    await handle_comment(message, state)
    message.answer.assert_called_once_with("Пожалуйста, отправь текстовое сообщение.")


@pytest.mark.asyncio
async def test_handle_comment_with_no_comment():
    from bot.main import handle_comment
    message = AsyncMock()
    message.text = "нет"
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

    state.clear.assert_called_once()
    mock_be.create_user.assert_called_once()
    mock_be.create_request.assert_called_once()


@pytest.mark.asyncio
async def test_admin_menu_authorized():
    from bot.main import admin_menu
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    await admin_menu(message)
    message.answer.assert_called_once()
    call_args = message.answer.call_args
    assert "Админ-меню" in call_args.args[0]


@pytest.mark.asyncio
async def test_admin_menu_unauthorized():
    from bot.main import admin_menu
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 999999
    await admin_menu(message)
    message.answer.assert_called_once_with("Нет доступа")


@pytest.mark.asyncio
async def test_approve_request():
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
        mock_be.get_user = AsyncMock(return_value={"name": "Тест"})
        with patch("bot.main.bot") as mock_bot:
            mock_bot.send_message = AsyncMock()
            mock_bot.send_document = AsyncMock()
            await approve_request(callback)

    mock_be.update_request.assert_called_once()
    mock_be.create_peer.assert_called_once()
    callback.answer.assert_called_with("Одобрено")


@pytest.mark.asyncio
async def test_reject_request():
    from bot.main import reject_request
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "reject:1:2:333"
    callback.answer = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.update_request = AsyncMock()
        with patch("bot.main.bot") as mock_bot:
            mock_bot.send_message = AsyncMock()
            await reject_request(callback)

    mock_be.update_request.assert_called_once()
    callback.answer.assert_called_with("Отказано")


@pytest.mark.asyncio
async def test_approve_request_not_admin():
    from bot.main import approve_request
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 999999
    callback.data = "approve:1:2:333"
    callback.answer = AsyncMock()
    await approve_request(callback)
    callback.answer.assert_called_with("Нет прав", show_alert=True)


@pytest.mark.asyncio
async def test_admin_peer_update():
    from bot.main import admin_peer_update
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:peer:5:disabled"
    callback.answer = AsyncMock()
    callback.message = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.update_peer_status = AsyncMock()
        await admin_peer_update(callback)

    mock_be.update_peer_status.assert_called_once_with(5, "disabled")
    callback.answer.assert_called()


@pytest.mark.asyncio
async def test_admin_peer_update_error():
    from bot.main import admin_peer_update
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:peer:5:disabled"
    callback.answer = AsyncMock()
    callback.message = AsyncMock()

    with patch("bot.main.backend") as mock_be:
        mock_be.update_peer_status = AsyncMock(side_effect=Exception("fail"))
        await admin_peer_update(callback)

    callback.message.answer.assert_called()


@pytest.mark.asyncio
async def test_admin_peer_update_bad_data():
    from bot.main import admin_peer_update
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = 123456789
    callback.data = "admin:peer:bad"
    callback.answer = AsyncMock()
    await admin_peer_update(callback)
    callback.answer.assert_called_with("Некорректный запрос", show_alert=True)
