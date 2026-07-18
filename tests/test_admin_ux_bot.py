from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _callback(data: str, admin_id: int = 123456789):
    callback = AsyncMock()
    callback.data = data
    callback.from_user = MagicMock()
    callback.from_user.id = admin_id
    callback.message = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def test_format_user_card_shows_user_devices_wg_and_traffic():
    from bot.main import _format_user_card

    text = _format_user_card({
        "user": {"id": 7, "name": "Alice", "tg_id": 777, "contact": "@alice"},
        "latest_request": {"id": 3, "status": "approved"},
        "wg": {"available": False},
        "traffic_24h_bytes": 2 * 1024 ** 3,
        "peers": [{
            "id": 10,
            "address": "10.10.0.10/32",
            "status": "active",
            "speed_limit_mbps": 20,
            "online": True,
            "wg_present": True,
            "last_handshake_at": "2026-07-18T10:00:00",
            "traffic_24h": {"rx": 1024 ** 3, "tx": 2 * 1024 ** 3},
        }],
    })

    assert "👤 Alice · #7" in text
    assert "WG: ⚠️ недоступен" in text
    assert "🟢 #10" in text
    assert "онлайн, WG есть" in text
    assert "24ч ↓1.0 / ↑2.0 ГБ" in text


def test_user_card_keyboard_routes_peer_and_bulk_actions_to_user_context():
    from bot.main import _user_card_keyboard

    keyboard = _user_card_keyboard({
        "user": {"id": 7},
        "peers": [{"id": 10, "address": "10.10.0.10/32", "status": "active"}],
    })
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

    assert "adm:pc:10:7" in callbacks
    assert "adm:add:7" in callbacks
    assert "adm:ub:7:disabled" in callbacks
    assert "adm:ub:7:active" in callbacks


def test_peer_card_keyboard_exposes_speed_presets_and_unlimited():
    from bot.main import _peer_card_keyboard

    keyboard = _peer_card_keyboard({"id": 10, "status": "active"}, user_id=7)
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    labels = {button.text for button in buttons}
    callbacks = {button.callback_data for button in buttons}

    assert "50 Мбит" in labels
    assert "Без лимита" in labels
    assert "adm:ps:10:7:50" in callbacks
    assert "adm:ps:10:7:0" in callbacks


def test_format_user_list_shows_search_aggregates_and_empty_state():
    from bot.main import _format_user_list

    empty = _format_user_list({"items": [], "total": 0}, query="none")
    filled = _format_user_list({
        "total": 1,
        "items": [{
            "id": 1,
            "name": "Bob",
            "contact": "@bob",
            "tg_id": 222,
            "peer_counts": {"active": 1, "disabled": 2, "banned": 0},
            "latest_request": {"status": "new"},
            "traffic_24h_bytes": 1024 ** 3,
        }],
    })

    assert "Ничего не найдено" in empty
    assert "🔑 Пиры: 🟢1 🔴2 ⛔0" in filled
    assert "24ч 1.0 ГБ" in filled


@pytest.mark.asyncio
async def test_admin_card_actions_rejects_malformed_callback():
    from bot.main import admin_card_actions

    callback = _callback("adm")
    state = AsyncMock()

    await admin_card_actions(callback, state)

    callback.answer.assert_called_once_with("Некорректный запрос", show_alert=True)


@pytest.mark.asyncio
async def test_admin_card_actions_search_sets_state_and_prompts_admin():
    from bot.main import AdminSearch, admin_card_actions

    callback = _callback("adm:srch")
    state = AsyncMock()

    await admin_card_actions(callback, state)

    state.set_state.assert_called_once_with(AdminSearch.waiting_query)
    callback.message.answer.assert_called_once()
    callback.answer.assert_called_once()


@pytest.mark.asyncio
async def test_admin_card_actions_updates_peer_and_refreshes_returned_user_card():
    from bot.main import admin_card_actions

    callback = _callback("adm:pa:10:disabled")
    state = AsyncMock()
    card = {
        "user": {"id": 7, "name": "Alice"},
        "latest_request": {},
        "wg": {"available": True},
        "traffic_24h_bytes": 0,
        "peers": [{"id": 10, "user_id": 7, "address": "10.10.0.10/32", "status": "disabled"}],
    }
    with patch("bot.main.backend") as backend:
        backend.update_peer_status = AsyncMock(return_value={"id": 10, "user_id": 7})
        backend.admin_user_card = AsyncMock(return_value=card)
        await admin_card_actions(callback, state)

    backend.update_peer_status.assert_awaited_once_with(10, "disabled")
    backend.admin_user_card.assert_awaited_once_with(7)
    callback.message.edit_text.assert_called_once()


@pytest.mark.asyncio
async def test_speed_change_preserves_disabled_peer_status():
    from bot.main import admin_card_actions

    callback = _callback("adm:ps:10:7:50")
    state = AsyncMock()
    card = {
        "user": {"id": 7, "name": "Alice"},
        "latest_request": {},
        "wg": {"available": True},
        "traffic_24h_bytes": 0,
        "peers": [{
            "id": 10,
            "user_id": 7,
            "address": "10.10.0.10/32",
            "status": "disabled",
            "speed_limit_mbps": 50,
        }],
    }
    with patch("bot.main.backend") as backend:
        backend.admin_user_card = AsyncMock(return_value=card)
        backend.update_peer_status = AsyncMock(return_value=card["peers"][0])
        await admin_card_actions(callback, state)

    backend.update_peer_status.assert_awaited_once_with(
        10,
        "disabled",
        speed_limit_mbps=50,
    )


@pytest.mark.asyncio
async def test_admin_card_actions_rejects_bad_bulk_status_data():
    from bot.main import admin_card_actions

    callback = _callback("adm:ub:not-int:active")
    state = AsyncMock()

    await admin_card_actions(callback, state)

    callback.answer.assert_called_once_with("Некорректные данные", show_alert=True)


@pytest.mark.asyncio
async def test_admin_search_query_clears_state_and_uses_admin_list_search():
    from bot.main import admin_search_query

    message = AsyncMock()
    message.text = "alice"
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    state = AsyncMock()
    with patch("bot.main.backend") as backend:
        backend.admin_user_list = AsyncMock(return_value={"items": [], "total": 0, "limit": 8, "offset": 0})
        await admin_search_query(message, state)

    state.set_state.assert_awaited_once_with(None)
    state.update_data.assert_awaited_once_with(admin_query="alice", admin_offset=0)
    backend.admin_user_list.assert_awaited_once_with(query="alice", limit=8, offset=0)
    message.answer.assert_called_once()


@pytest.mark.asyncio
async def test_admin_search_query_denies_non_admin_and_clears_state():
    from bot.main import admin_search_query

    message = AsyncMock()
    message.text = "alice"
    message.from_user = MagicMock()
    message.from_user.id = 1
    state = AsyncMock()

    await admin_search_query(message, state)

    message.answer.assert_called_once_with("Нет доступа")
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_config_rejects_peer_owned_by_another_user():
    from bot.main import _send_config_to_user

    with patch("bot.main.backend") as backend:
        backend.admin_user_card = AsyncMock(return_value={
            "user": {"id": 7, "tg_id": 777, "name": "Alice"},
            "peers": [{"id": 10, "user_id": 7}],
        })
        backend.get_config = AsyncMock()

        with pytest.raises(RuntimeError, match="does not belong"):
            await _send_config_to_user(11, 7)

    backend.get_config.assert_not_called()
