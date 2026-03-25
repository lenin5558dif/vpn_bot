import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_wg():
    with patch("app.api.peers.wg") as m:
        m.generate_keys = AsyncMock(return_value=("privkey123", "pubkey456"))
        m.apply_peer = AsyncMock()
        m.apply_speed_limit = AsyncMock()
        m.remove_peer = AsyncMock()
        m.allocate_ip = lambda used: "10.10.0.2/32"
        m.interface = "wg0"
        m.render_peer_config = lambda private_key, address: (
            f"[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n\n"
            f"[Peer]\nPublicKey = serverpubkey\nAllowedIPs = 0.0.0.0/0\n"
        )
        yield m


@pytest.mark.asyncio
async def test_create_peer(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "PeerUser"}, headers=bot_headers)
    uid = user.json()["id"]
    resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["address"] == "10.10.0.2/32"
    assert data["speed_limit_mbps"] == 20
    mock_wg.apply_peer.assert_called_once()


@pytest.mark.asyncio
async def test_create_peer_speed_limit_zero(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    resp = await client.post("/peers", json={"user_id": uid, "speed_limit_mbps": 0}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["speed_limit_mbps"] == 0


@pytest.mark.asyncio
async def test_create_peer_custom_speed(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    resp = await client.post("/peers", json={"user_id": uid, "speed_limit_mbps": 50}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["speed_limit_mbps"] == 50


@pytest.mark.asyncio
async def test_list_peers(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    resp = await client.get("/peers", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_list_peers_pagination(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    # allocate different IPs
    ips = iter(["10.10.0.2/32", "10.10.0.3/32", "10.10.0.4/32"])
    mock_wg.allocate_ip = lambda used: next(ips)
    for _ in range(3):
        await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    resp = await client.get("/peers?limit=2", headers=admin_headers)
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_update_peer_disable(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    resp = await client.patch(f"/peers/{pid}", json={"status": "disabled"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"


@pytest.mark.asyncio
async def test_update_peer_speed_zero(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    resp = await client.patch(f"/peers/{pid}", json={"status": "active", "speed_limit_mbps": 0}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["speed_limit_mbps"] == 0


@pytest.mark.asyncio
async def test_update_peer_ban(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    resp = await client.patch(f"/peers/{pid}", json={"status": "banned"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "banned"
    mock_wg.remove_peer.assert_called_once()
    # Peer should be deleted
    get_resp = await client.get(f"/peers/{pid}/config", headers=admin_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_update_peer_not_found(client, admin_headers):
    resp = await client.patch("/peers/999", json={"status": "active"}, headers=admin_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_config(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    resp = await client.get(f"/peers/{pid}/config", headers=admin_headers)
    assert resp.status_code == 200
    assert "download_token" in resp.json()


@pytest.mark.asyncio
async def test_get_config_not_found(client, admin_headers):
    resp = await client.get("/peers/999/config", headers=admin_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_config_file(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    with patch("app.api.peers.decrypt_private_key", return_value="decrypted_privkey"):
        resp = await client.get(f"/peers/{pid}/config/file", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.text
    assert "[Interface]" in body
    assert "PrivateKey = decrypted_privkey" in body
    assert "[Peer]" in body


@pytest.mark.asyncio
async def test_download_config_not_found(client, admin_headers):
    resp = await client.get("/peers/999/config/file", headers=admin_headers)
    assert resp.status_code == 404
