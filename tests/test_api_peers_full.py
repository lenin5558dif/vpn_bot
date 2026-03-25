"""Full coverage tests for peers.py - test through real encrypt/decrypt."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_wg_real():
    """Mock only WG commands, let crypto work for real."""
    with patch("app.api.peers.wg") as m:
        m.generate_keys = AsyncMock(return_value=("real_privkey_test", "real_pubkey_test"))
        m.apply_peer = AsyncMock()
        m.apply_speed_limit = AsyncMock()
        m.remove_peer = AsyncMock()
        m.allocate_ip = lambda used: "10.10.0.5/32"
        m.interface = "wg0"
        m.render_peer_config = lambda private_key, address: (
            f"[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n\n"
            f"[Peer]\nPublicKey = srv\nAllowedIPs = 0.0.0.0/0\n"
        )
        yield m


@pytest.mark.asyncio
async def test_full_peer_lifecycle(client, admin_headers, bot_headers, mock_wg_real):
    """Create user -> create peer -> get config -> download config -> disable -> activate -> ban."""
    # Create user
    resp = await client.post("/users", json={"name": "Lifecycle"}, headers=bot_headers)
    assert resp.status_code == 200
    uid = resp.json()["id"]

    # Create peer
    resp = await client.post("/peers", json={"user_id": uid, "speed_limit_mbps": 30}, headers=admin_headers)
    assert resp.status_code == 200
    peer = resp.json()
    pid = peer["id"]
    assert peer["speed_limit_mbps"] == 30
    assert peer["status"] == "active"
    assert peer["address"] == "10.10.0.5/32"

    # Get config metadata
    resp = await client.get(f"/peers/{pid}/config", headers=admin_headers)
    assert resp.status_code == 200
    assert "download_token" in resp.json()

    # Download config file (decrypt works for real)
    resp = await client.get(f"/peers/{pid}/config/file", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.text
    assert "[Interface]" in body
    assert "real_privkey_test" in body

    # Disable peer
    resp = await client.patch(f"/peers/{pid}", json={"status": "disabled"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"

    # Activate peer
    resp = await client.patch(f"/peers/{pid}", json={"status": "active", "speed_limit_mbps": 0}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    assert resp.json()["speed_limit_mbps"] == 0

    # Ban peer (deletes from DB)
    resp = await client.patch(f"/peers/{pid}", json={"status": "banned"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "banned"
    mock_wg_real.remove_peer.assert_called()

    # Verify deleted
    resp = await client.get(f"/peers/{pid}/config", headers=admin_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_peer_with_custom_allowed_ips(client, admin_headers, bot_headers, mock_wg_real):
    resp = await client.post("/users", json={"name": "Custom"}, headers=bot_headers)
    uid = resp.json()["id"]
    resp = await client.post(
        "/peers",
        json={"user_id": uid, "allowed_ips": "10.10.0.5/32"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["allowed_ips"] == "10.10.0.5/32"


@pytest.mark.asyncio
async def test_peers_no_auth(client):
    resp = await client.get("/peers")
    assert resp.status_code == 401
    resp = await client.post("/peers", json={"user_id": 1})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_config_for_nonexistent_peer_config(client, admin_headers, bot_headers, mock_wg_real):
    """Create peer then delete config manually to hit config not found."""
    resp = await client.post("/users", json={"name": "NoConfig"}, headers=bot_headers)
    uid = resp.json()["id"]
    resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = resp.json()["id"]

    # Delete config via session
    from app.database import SessionLocal
    from app.models import Config
    from sqlmodel import select
    async with SessionLocal() as session:
        cfgs = await session.exec(select(Config).where(Config.peer_id == pid))
        for c in cfgs.all():
            await session.delete(c)
        await session.commit()

    resp = await client.get(f"/peers/{pid}/config", headers=admin_headers)
    assert resp.status_code == 404
