import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from bot.backend import BackendClient
from app.schemas import RequestStatus
from app.security import create_access_token


@pytest.fixture
def bc():
    client = BackendClient()
    return client


def _mock_client():
    """Create a mock httpx.AsyncClient."""
    m = AsyncMock()
    m.is_closed = False
    return m


@pytest.mark.asyncio
async def test_get_client_creates_client(bc):
    bc.base_url = "http://localhost:8000"
    client = await bc._get_client()
    assert client is not None
    await bc.close()


@pytest.mark.asyncio
async def test_close_idempotent(bc):
    await bc.close()  # no client, should not raise


@pytest.mark.asyncio
async def test_bot_key_headers(bc):
    headers = bc._bot_key_headers()
    assert "X-Bot-Api-Key" in headers


@pytest.mark.asyncio
async def test_bot_key_headers_empty():
    bc = BackendClient()
    bc.settings.bot_api_key = ""
    assert bc._bot_key_headers() == {}


def test_is_token_valid_good(bc):
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))
    assert bc._is_token_valid(token) is True


def test_is_token_valid_expired(bc):
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(seconds=-10))
    assert bc._is_token_valid(token) is False


def test_is_token_valid_invalid(bc):
    assert bc._is_token_valid("garbage.token.here") is False


@pytest.mark.asyncio
async def test_get_token(bc):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "tok123"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.post = AsyncMock(return_value=mock_resp)
    bc._client = mc

    token = await bc._get_token()
    assert token == "tok123"


@pytest.mark.asyncio
async def test_get_token_cached(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))
    mc = _mock_client()
    bc._client = mc
    token = await bc._get_token()
    assert token == bc.token


@pytest.mark.asyncio
async def test_headers(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))
    mc = _mock_client()
    bc._client = mc
    headers = await bc._headers()
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_create_user(bc):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 1, "name": "Test"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.post = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.create_user({"name": "Test"})
    assert result["id"] == 1


@pytest.mark.asyncio
async def test_create_request(bc):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 1, "status": "new"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.post = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.create_request({"user_id": 1})
    assert result["status"] == "new"


@pytest.mark.asyncio
async def test_update_request(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "status": "approved"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.update_request(1, RequestStatus.approved)
    assert result["status"] == "approved"
    call_kwargs = mc.request.call_args
    assert call_kwargs.kwargs["json"]["status"] == "approved"


@pytest.mark.asyncio
async def test_create_peer(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "status": "active"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.create_peer(1)
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_get_user(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "name": "Test"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.get_user(1)
    assert result["name"] == "Test"


@pytest.mark.asyncio
async def test_get_config(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "[Interface]\nPrivateKey = x"
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.get_config(1)
    assert "[Interface]" in result


@pytest.mark.asyncio
async def test_list_users(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 1}]
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.list_users()
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_requests_with_status(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.list_requests(status="new")
    assert result == []


@pytest.mark.asyncio
async def test_list_requests_no_status(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 1}]
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.list_requests()
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_peers(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 1}]
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.list_peers()
    assert len(result) == 1


@pytest.mark.asyncio
async def test_update_peer_status(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": 1, "status": "disabled"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.update_peer_status(1, "disabled")
    assert result["status"] == "disabled"


@pytest.mark.asyncio
async def test_health(bc):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "ok"}
    mock_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.get = AsyncMock(return_value=mock_resp)
    bc._client = mc

    result = await bc.health()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_request_with_auth_retry_on_401(bc):
    bc.token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))

    resp_401 = MagicMock()
    resp_401.status_code = 401

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = {"ok": True}
    resp_ok.raise_for_status = MagicMock()

    login_resp = MagicMock()
    login_resp.json.return_value = {"access_token": "new_token"}
    login_resp.raise_for_status = MagicMock()

    mc = _mock_client()
    mc.request = AsyncMock(side_effect=[resp_401, resp_ok])
    mc.post = AsyncMock(return_value=login_resp)
    bc._client = mc

    result = await bc._request_with_auth("GET", "/test")
    assert result.json() == {"ok": True}
    assert mc.request.call_count == 2
