"""Additional API tests for uncovered paths."""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

from app.models import Peer, PeerStatus, Config, TrafficStat, User, Role


@pytest.fixture
def mock_wg():
    with patch("app.api.peers.wg") as m:
        m.generate_keys = AsyncMock(return_value=("privkey", "pubkey"))
        m.apply_peer = AsyncMock()
        m.apply_speed_limit = AsyncMock()
        m.remove_peer = AsyncMock()
        m.allocate_ip = lambda used: "10.10.0.2/32"
        m.interface = "wg0"
        m.render_peer_config = lambda private_key, address: (
            f"[Interface]\nPrivateKey = {private_key}\nAddress = {address}\n\n"
            f"[Peer]\nPublicKey = srv\nAllowedIPs = 0.0.0.0/0\n"
        )
        yield m


# --- peers.py coverage: create_peer, ban, activate, disable, config ---

@pytest.mark.asyncio
async def test_create_peer_full_flow(client, admin_headers, bot_headers, mock_wg, session):
    """Cover create_peer including encrypt_private_key."""
    resp = await client.post("/users", json={"name": "U1"}, headers=bot_headers)
    uid = resp.json()["id"]

    with patch("app.api.peers.encrypt_private_key", return_value="encrypted_key"):
        resp = await client.post("/peers", json={"user_id": uid, "speed_limit_mbps": 10}, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["speed_limit_mbps"] == 10
    assert data["status"] == "active"
    mock_wg.apply_peer.assert_called()
    mock_wg.apply_speed_limit.assert_called()


@pytest.mark.asyncio
async def test_peer_ban_full_flow(client, admin_headers, bot_headers, mock_wg, session):
    """Cover ban path including TrafficStat cleanup."""
    resp = await client.post("/users", json={"name": "U2"}, headers=bot_headers)
    uid = resp.json()["id"]

    with patch("app.api.peers.encrypt_private_key", return_value="enc"):
        resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = resp.json()["id"]

    # Add TrafficStat for the peer (to test FK cleanup)
    peer = await session.get(Peer, pid)
    ts = TrafficStat(peer_id=pid, rx_bytes=100, tx_bytes=200)
    session.add(ts)
    await session.commit()

    resp = await client.patch(f"/peers/{pid}", json={"status": "banned"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "banned"
    mock_wg.remove_peer.assert_called()


@pytest.mark.asyncio
async def test_peer_activate_from_disabled(client, admin_headers, bot_headers, mock_wg):
    """Cover activate path."""
    resp = await client.post("/users", json={"name": "U3"}, headers=bot_headers)
    uid = resp.json()["id"]

    with patch("app.api.peers.encrypt_private_key", return_value="enc"):
        resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = resp.json()["id"]

    await client.patch(f"/peers/{pid}", json={"status": "disabled"}, headers=admin_headers)
    resp = await client.patch(f"/peers/{pid}", json={"status": "active"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_download_config_with_decrypt(client, admin_headers, bot_headers, mock_wg):
    """Cover download_config path."""
    resp = await client.post("/users", json={"name": "U4"}, headers=bot_headers)
    uid = resp.json()["id"]

    with patch("app.api.peers.encrypt_private_key", return_value="enc"):
        resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = resp.json()["id"]

    with patch("app.api.peers.decrypt_private_key", return_value="decrypted_key"):
        resp = await client.get(f"/peers/{pid}/config/file", headers=admin_headers)
    assert resp.status_code == 200
    assert "decrypted_key" in resp.text


# --- traffic.py coverage: list with hours filter ---

@pytest.mark.asyncio
async def test_list_traffic_with_hours_filter(client, admin_headers, session):
    peer = Peer(
        user_id=1, iface="wg0", public_key="pk", private_key_enc="enc",
        address="10.10.0.2/32", allowed_ips="10.10.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    ts = TrafficStat(peer_id=peer.id, ts=datetime.utcnow(), rx_bytes=500, tx_bytes=600)
    session.add(ts)
    await session.commit()
    resp = await client.get("/traffic?hours=1&limit=10", headers=admin_headers)
    assert resp.status_code == 200


# --- requests.py coverage: create with bot key and update ---

@pytest.mark.asyncio
async def test_create_and_update_request_flow(client, admin_headers, bot_headers, session):
    user = await client.post("/users", json={"name": "ReqU"}, headers=bot_headers)
    uid = user.json()["id"]
    req = await client.post("/requests", json={"user_id": uid, "comment": "test"}, headers=bot_headers)
    rid = req.json()["id"]

    resp = await client.patch(
        f"/requests/{rid}",
        json={"status": "rejected", "resolved_by": uid},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["resolved_by"] == uid


# --- users.py: create with minimal fields ---

@pytest.mark.asyncio
async def test_create_user_minimal(client, bot_headers):
    resp = await client.post("/users", json={"name": "MinUser"}, headers=bot_headers)
    assert resp.status_code == 200
    assert resp.json()["tg_id"] is None
    assert resp.json()["contact"] is None


# --- health.py: check with wg mock ---

@pytest.mark.asyncio
async def test_health_with_wg_mock(client):
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["checks"]["wireguard"] == "ok"


@pytest.mark.asyncio
async def test_health_wg_error(client):
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"err"))
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        resp = await client.get("/health")
    data = resp.json()
    assert data["checks"]["wireguard"] == "error"
    assert data["status"] == "degraded"
