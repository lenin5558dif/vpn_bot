from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.backend import BackendClient


@pytest.fixture
def bc():
    client = BackendClient()
    client.settings.bot_api_key = "test-bot-api-key"
    return client


def _mock_client():
    client = AsyncMock()
    client.is_closed = False
    return client


@pytest.mark.asyncio
async def test_admin_user_list_passes_search_pagination_params(bc):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"items": [], "total": 0, "limit": 5, "offset": 10}
    response.raise_for_status = MagicMock()
    client = _mock_client()
    client.request = AsyncMock(return_value=response)
    bc._client = client

    result = await bc.admin_user_list(query="alice", limit=5, offset=10)

    assert result["offset"] == 10
    assert client.request.call_args.args[:2] == ("GET", "/users/admin/list")
    assert client.request.call_args.kwargs["params"] == {"limit": 5, "offset": 10, "query": "alice"}


@pytest.mark.asyncio
async def test_admin_user_card_uses_user_card_endpoint(bc):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"user": {"id": 7}, "peers": []}
    response.raise_for_status = MagicMock()
    client = _mock_client()
    client.request = AsyncMock(return_value=response)
    bc._client = client

    result = await bc.admin_user_card(7)

    assert result["user"]["id"] == 7
    assert client.request.call_args.args[:2] == ("GET", "/users/7/admin-card")


@pytest.mark.asyncio
async def test_bulk_update_user_peers_sends_status_and_speed_limit(bc):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"user_id": 7, "status": "active", "updated": 2}
    response.raise_for_status = MagicMock()
    client = _mock_client()
    client.request = AsyncMock(return_value=response)
    bc._client = client

    result = await bc.bulk_update_user_peers(7, "active", speed_limit_mbps=50)

    assert result["updated"] == 2
    assert client.request.call_args.args[:2] == ("PATCH", "/peers/user/7/status")
    assert client.request.call_args.kwargs["json"] == {"status": "active", "speed_limit_mbps": 50}


@pytest.mark.asyncio
async def test_reconcile_peers_uses_reconcile_endpoint(bc):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok"}
    response.raise_for_status = MagicMock()
    client = _mock_client()
    client.request = AsyncMock(return_value=response)
    bc._client = client

    result = await bc.reconcile_peers()

    assert result == {"status": "ok"}
    assert client.request.call_args.args[:2] == ("GET", "/peers/reconcile")
