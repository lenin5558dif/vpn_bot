from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Peer, PeerStatus, Request, RequestStatus, TrafficStat, User
from app.wg import WireGuardError


@pytest.fixture
def admin_ux_wg():
    with patch("app.api.peers.wg") as peers_wg, patch("app.api.users.wg") as users_wg:
        key_counter = 1000
        ip_counter = 1

        async def generate_keys():
            nonlocal key_counter
            key_counter += 1
            return f"privkey{key_counter}", f"pubkey{key_counter}"

        def allocate_ip(_used):
            nonlocal ip_counter
            ip_counter += 1
            return f"10.10.0.{ip_counter}/32"

        peers_wg.generate_keys = AsyncMock(side_effect=generate_keys)
        peers_wg.apply_peer = AsyncMock()
        peers_wg.apply_speed_limit = AsyncMock()
        peers_wg.remove_peer = AsyncMock()
        peers_wg.allocate_ip = allocate_ip
        peers_wg.interface = "wg0"
        peers_wg.render_peer_config = lambda private_key, address: f"{private_key}:{address}"
        peers_wg.runtime_snapshot = AsyncMock(return_value={"available": True, "peers": {}, "error": None})

        users_wg.runtime_snapshot = AsyncMock(return_value={"available": True, "peers": {}, "error": None})
        yield peers_wg, users_wg


@pytest.mark.asyncio
async def test_admin_user_list_filters_pages_and_returns_aggregates(
    client, admin_headers, bot_headers, session, admin_ux_wg
):
    await client.post("/users", json={"name": "Alice VPN", "contact": "@alice", "tg_id": 101}, headers=bot_headers)
    bob = await client.post("/users", json={"name": "Bob", "contact": "@bob", "tg_id": 202}, headers=bot_headers)
    await client.post("/users", json={"name": "Carol", "contact": "@carol", "tg_id": 303}, headers=bot_headers)
    bob_id = bob.json()["id"]
    peer = await client.post("/peers", json={"user_id": bob_id}, headers=admin_headers)
    peer_id = peer.json()["id"]
    session.add(TrafficStat(peer_id=peer_id, delta_rx=1024, delta_tx=2048))
    session.add(Request(user_id=bob_id, status=RequestStatus.approved, comment="ok"))
    await session.commit()

    resp = await client.get("/users/admin/list?query=202&limit=1&offset=0", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == bob_id
    assert data["items"][0]["peer_counts"] == {"total": 1, "active": 1, "disabled": 0, "banned": 0}
    assert data["items"][0]["latest_request"]["status"] == "approved"
    assert data["items"][0]["traffic_24h_bytes"] == 3072


@pytest.mark.asyncio
async def test_admin_user_list_paginates_without_search(client, admin_headers, bot_headers):
    for index in range(3):
        await client.post("/users", json={"name": f"User {index}"}, headers=bot_headers)

    resp = await client.get("/users/admin/list?limit=2&offset=2", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 1
    assert data["offset"] == 2


@pytest.mark.asyncio
async def test_admin_user_card_returns_wg_unavailable_and_db_traffic_fallback(
    client, admin_headers, bot_headers, session, admin_ux_wg
):
    _, users_wg = admin_ux_wg
    created = await client.post("/users", json={"name": "Card User", "tg_id": 777}, headers=bot_headers)
    user_id = created.json()["id"]
    peer = await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    peer_id = peer.json()["id"]
    db_peer = await session.get(Peer, peer_id)
    db_peer.last_handshake_at = datetime.utcnow() - timedelta(minutes=20)
    session.add(db_peer)
    session.add(TrafficStat(peer_id=peer_id, delta_rx=10, delta_tx=90))
    await session.commit()
    users_wg.runtime_snapshot = AsyncMock(return_value={"available": False, "error": "unavailable", "peers": {}})

    resp = await client.get(f"/users/{user_id}/admin-card", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["wg"] == {"available": False, "error": "unavailable"}
    assert data["traffic_24h_bytes"] == 100
    assert data["peers"][0]["wg_present"] is False
    assert data["peers"][0]["traffic_24h"] == {"rx": 10, "tx": 90}
    assert data["peers"][0]["last_handshake_at"] is not None


@pytest.mark.asyncio
async def test_admin_user_card_prefers_live_handshake_and_never_exposes_private_key(
    client, admin_headers, bot_headers, admin_ux_wg
):
    _, users_wg = admin_ux_wg
    created = await client.post("/users", json={"name": "Online User"}, headers=bot_headers)
    user_id = created.json()["id"]
    peer = await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    public_key = peer.json()["public_key"]
    live_ts = int(datetime.utcnow().timestamp())
    users_wg.runtime_snapshot = AsyncMock(return_value={
        "available": True,
        "error": None,
        "peers": {
            public_key: {
                "allowed_ips": "10.10.0.2/32",
                "latest_handshake": live_ts,
                "rx_bytes": 1,
                "tx_bytes": 2,
            }
        },
    })

    resp = await client.get(f"/users/{user_id}/admin-card", headers=admin_headers)

    peer_data = resp.json()["peers"][0]
    assert peer_data["online"] is True
    assert peer_data["wg_present"] is True
    assert "private_key_enc" not in peer_data


@pytest.mark.asyncio
async def test_bulk_update_user_peers_updates_current_non_banned_peers(
    client, admin_headers, bot_headers, session, admin_ux_wg
):
    created = await client.post("/users", json={"name": "Bulk User"}, headers=bot_headers)
    user_id = created.json()["id"]
    p1 = await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    p2 = await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    db_peer = await session.get(Peer, p2.json()["id"])
    db_peer.status = PeerStatus.banned
    session.add(db_peer)
    await session.commit()

    resp = await client.patch(f"/peers/user/{user_id}/status", json={"status": "disabled"}, headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json() == {"user_id": user_id, "status": "disabled", "updated": 1}
    updated = await session.get(Peer, p1.json()["id"])
    banned = await session.get(Peer, p2.json()["id"])
    assert updated.status == PeerStatus.disabled
    assert banned.status == PeerStatus.banned


@pytest.mark.asyncio
async def test_bulk_update_mid_operation_failure_restores_changed_and_current_peer(
    client, admin_headers, bot_headers, admin_ux_wg
):
    peers_wg, _ = admin_ux_wg
    created = await client.post("/users", json={"name": "Partial User"}, headers=bot_headers)
    user_id = created.json()["id"]
    await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    peers_wg.apply_peer.reset_mock()
    peers_wg.apply_speed_limit.reset_mock()
    peers_wg.apply_peer = AsyncMock(side_effect=[
        None,
        WireGuardError("second failed"),
        None,
        None,
    ])

    resp = await client.patch(f"/peers/user/{user_id}/status", json={"status": "disabled"}, headers=admin_headers)

    assert resp.status_code == 503
    assert resp.json()["detail"] == "WireGuard bulk operation failed"
    assert peers_wg.apply_peer.await_count == 4
    restored_allowed_ips = [
        call.kwargs.get("allowed_ips") if "allowed_ips" in call.kwargs else call.args[1]
        for call in peers_wg.apply_peer.await_args_list[-2:]
    ]
    assert restored_allowed_ips == ["10.10.0.3/32", "10.10.0.2/32"]


@pytest.mark.asyncio
async def test_bulk_update_db_failure_restores_all_runtime_changes(
    client, admin_headers, bot_headers, admin_ux_wg
):
    peers_wg, _ = admin_ux_wg
    created = await client.post("/users", json={"name": "DB Fail User"}, headers=bot_headers)
    user_id = created.json()["id"]
    await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    await client.post("/peers", json={"user_id": user_id}, headers=admin_headers)
    peers_wg.apply_peer.reset_mock()

    with patch("app.api.peers.record_audit", AsyncMock(side_effect=RuntimeError("db failed"))):
        with pytest.raises(RuntimeError, match="db failed"):
            await client.patch(f"/peers/user/{user_id}/status", json={"status": "disabled"}, headers=admin_headers)

    assert peers_wg.apply_peer.await_count == 4
    assert [
        call.kwargs.get("allowed_ips") if "allowed_ips" in call.kwargs else call.args[1]
        for call in peers_wg.apply_peer.await_args_list[-2:]
    ] == [
        "10.10.0.3/32",
        "10.10.0.2/32",
    ]


@pytest.mark.asyncio
async def test_reconcile_reports_unknown_missing_mismatch_and_disabled_allowed_ips(
    client, admin_headers, session
):
    user = User(name="Recon User")
    session.add(user)
    await session.flush()
    active = Peer(
        user_id=user.id,
        public_key="db-active-key",
        private_key_enc="enc",
        address="10.10.0.2/32",
        allowed_ips="10.10.0.2/32",
        status=PeerStatus.active,
    )
    missing = Peer(
        user_id=user.id,
        public_key="db-missing-key",
        private_key_enc="enc",
        address="10.10.0.3/32",
        allowed_ips="10.10.0.3/32",
        status=PeerStatus.active,
    )
    disabled = Peer(
        user_id=user.id,
        public_key="db-disabled-key",
        private_key_enc="enc",
        address="10.10.0.4/32",
        allowed_ips="10.10.0.4/32",
        status=PeerStatus.disabled,
    )
    session.add(active)
    session.add(missing)
    session.add(disabled)
    await session.commit()
    with patch("app.api.peers.wg") as peers_wg:
        peers_wg.runtime_snapshot = AsyncMock(return_value={
            "available": True,
            "error": None,
            "peers": {
                "db-active-key": {"allowed_ips": "10.99.0.2/32", "latest_handshake": 10},
                "db-disabled-key": {"allowed_ips": "10.10.0.4/32", "latest_handshake": 0},
                "runtime-only-secret-public-key": {"allowed_ips": "10.10.0.99/32", "latest_handshake": 1},
            },
        })

        resp = await client.get("/peers/reconcile", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "drift"
    assert data["counts"] == {
        "unknown_wg_peers": 1,
        "missing_wg_peers": 1,
        "allowed_ips_mismatch": 1,
        "disabled_with_allowed_ips": 1,
    }
    assert data["unknown_wg_peers"][0]["public_key_fingerprint"] == "runtime-on…ic-key"


@pytest.mark.asyncio
async def test_reconcile_returns_unavailable_without_drift_when_wg_snapshot_fails(client, admin_headers):
    with patch("app.api.peers.wg") as peers_wg:
        peers_wg.runtime_snapshot = AsyncMock(return_value={"available": False, "error": "unavailable", "peers": {}})

        resp = await client.get("/peers/reconcile", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "wireguard_unavailable"
