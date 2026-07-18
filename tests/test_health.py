import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "checks" in data
    assert data["checks"]["db"] == "ok"


@pytest.mark.asyncio
async def test_root_endpoint(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json()["message"] == "VPN Admin API"


@pytest.mark.asyncio
async def test_server_stats_accepts_bot_service_key(client, bot_headers):
    resp = await client.get("/stats/server", headers=bot_headers)

    assert resp.status_code == 200
    assert "cpu_pct" in resp.json()
