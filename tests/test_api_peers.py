import pytest
from unittest.mock import AsyncMock, patch

from app.wg import WireGuardError


@pytest.fixture
def mock_wg():
    with patch("app.api.peers.wg") as m:
        key_counter = 455

        async def generate_keys():
            nonlocal key_counter
            key_counter += 1
            return f"privkey{key_counter}", f"pubkey{key_counter}"

        m.generate_keys = AsyncMock(side_effect=generate_keys)
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
    assert data["speed_limit_mbps"] == 50
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
async def test_list_peers_filter_user_id_with_bot_key(client, bot_headers, mock_wg):
    user1 = await client.post("/users", json={"name": "U1"}, headers=bot_headers)
    user2 = await client.post("/users", json={"name": "U2"}, headers=bot_headers)
    uid1 = user1.json()["id"]
    uid2 = user2.json()["id"]
    ips = iter(["10.10.0.2/32", "10.10.0.3/32"])
    mock_wg.allocate_ip = lambda used: next(ips)
    await client.post("/peers", json={"user_id": uid1}, headers=bot_headers)
    await client.post("/peers", json={"user_id": uid2}, headers=bot_headers)

    resp = await client.get(f"/peers?user_id={uid2}", headers=bot_headers)

    assert resp.status_code == 200
    assert resp.json()[0]["user_id"] == uid2


@pytest.mark.asyncio
async def test_create_peer_wg_failure_does_not_persist(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    mock_wg.apply_peer = AsyncMock(side_effect=WireGuardError("awg failed"))

    resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    peers = await client.get("/peers", headers=admin_headers)

    assert resp.status_code == 503
    assert peers.json() == []


@pytest.mark.asyncio
async def test_create_peer_missing_user_returns_404_without_wg(client, admin_headers, mock_wg):
    resp = await client.post("/peers", json={"user_id": 999}, headers=admin_headers)

    assert resp.status_code == 404
    mock_wg.generate_keys.assert_not_called()


@pytest.mark.asyncio
async def test_create_peer_invalid_allowed_ips_returns_422(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]

    resp = await client.post(
        "/peers",
        json={"user_id": uid, "allowed_ips": "not-a-network"},
        headers=admin_headers,
    )

    assert resp.status_code == 422
    mock_wg.generate_keys.assert_not_called()


@pytest.mark.asyncio
async def test_create_peer_speed_limit_failure_removes_wg_peer(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    mock_wg.apply_speed_limit = AsyncMock(side_effect=WireGuardError("tc failed"))

    resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)

    assert resp.status_code == 503
    mock_wg.remove_peer.assert_called_once_with("pubkey456")


@pytest.mark.asyncio
async def test_create_peer_duplicate_address_returns_409_and_removes_wg_peer(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    mock_wg.allocate_ip = lambda used: "10.10.0.2/32"
    first = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)

    resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)

    assert first.status_code == 200
    assert resp.status_code == 409
    mock_wg.remove_peer.assert_called_with("pubkey457")


@pytest.mark.asyncio
async def test_ban_peer_wg_failure_keeps_db_record(client, admin_headers, bot_headers, mock_wg):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    mock_wg.remove_peer = AsyncMock(side_effect=WireGuardError("remove failed"))

    resp = await client.patch(f"/peers/{pid}", json={"status": "banned"}, headers=admin_headers)
    peers = await client.get("/peers", headers=admin_headers)

    assert resp.status_code == 503
    assert len(peers.json()) == 1


@pytest.mark.asyncio
async def test_disable_db_failure_restores_previous_wg_state(
    client, admin_headers, bot_headers, mock_wg
):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    mock_wg.apply_peer.reset_mock()

    with patch("app.api.peers.record_audit", AsyncMock(side_effect=RuntimeError("db failed"))):
        with pytest.raises(RuntimeError, match="db failed"):
            await client.patch(f"/peers/{pid}", json={"status": "disabled"}, headers=admin_headers)

    assert mock_wg.apply_peer.await_args_list[0].kwargs["allowed_ips"] == ""
    assert mock_wg.apply_peer.await_args_list[-1].args[1] == "10.10.0.2/32"


@pytest.mark.asyncio
async def test_create_db_and_cleanup_failure_requires_reconciliation(
    client, admin_headers, bot_headers, mock_wg
):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    mock_wg.remove_peer = AsyncMock(side_effect=WireGuardError("remove failed"))

    with patch("app.api.peers.record_audit", AsyncMock(side_effect=RuntimeError("db failed"))):
        resp = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)

    assert resp.status_code == 503
    assert "manual reconciliation required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_wg_failure_and_restore_failure_requires_manual_reconciliation(
    client, admin_headers, bot_headers, mock_wg
):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    mock_wg.apply_peer = AsyncMock(
        side_effect=[
            WireGuardError("disable failed"),
            WireGuardError("restore failed"),
        ]
    )

    resp = await client.patch(f"/peers/{pid}", json={"status": "disabled"}, headers=admin_headers)

    assert resp.status_code == 503
    assert resp.json()["detail"] == "WireGuard operation failed; manual reconciliation required"


@pytest.mark.asyncio
async def test_ban_commit_failure_and_restore_failure_requires_manual_reconciliation(
    client, admin_headers, bot_headers, mock_wg
):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    mock_wg.apply_speed_limit = AsyncMock(side_effect=WireGuardError("restore failed"))

    with patch(
        "sqlmodel.ext.asyncio.session.AsyncSession.commit",
        new=AsyncMock(side_effect=RuntimeError("db failed")),
    ):
        resp = await client.patch(f"/peers/{pid}", json={"status": "banned"}, headers=admin_headers)

    assert resp.status_code == 503
    assert resp.json()["detail"] == "State update failed; manual reconciliation required"


@pytest.mark.asyncio
async def test_ban_audit_failure_rolls_back_and_restores_wg_state(
    client, admin_headers, bot_headers, mock_wg
):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    peer = await client.post("/peers", json={"user_id": uid}, headers=admin_headers)
    pid = peer.json()["id"]
    mock_wg.apply_peer.reset_mock()
    mock_wg.apply_speed_limit.reset_mock()

    with patch("app.api.peers.record_audit", AsyncMock(side_effect=RuntimeError("audit failed"))):
        with pytest.raises(RuntimeError, match="audit failed"):
            await client.patch(f"/peers/{pid}", json={"status": "banned"}, headers=admin_headers)

    mock_wg.apply_peer.assert_awaited_once_with("pubkey456", "10.10.0.2/32")
    mock_wg.apply_speed_limit.assert_awaited_once_with("10.10.0.2", 50)
    peers = await client.get("/peers", headers=admin_headers)
    assert [item["id"] for item in peers.json()] == [pid]


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
