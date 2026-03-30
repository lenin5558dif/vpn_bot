import pytest
from datetime import datetime

from app.models import Peer, PeerStatus, TrafficStat


@pytest.mark.asyncio
async def test_list_traffic_empty(client, admin_headers):
    resp = await client.get("/traffic", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_traffic_with_data(client, admin_headers, session):
    peer = Peer(
        user_id=1, iface="wg0", public_key="pk", private_key_enc="enc",
        address="10.10.0.2/32", allowed_ips="10.10.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    ts = TrafficStat(peer_id=peer.id, rx_bytes=100, tx_bytes=200, delta_rx=100, delta_tx=200)
    session.add(ts)
    await session.commit()
    resp = await client.get("/traffic", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rx_bytes"] == 100


@pytest.mark.asyncio
async def test_list_traffic_pagination(client, admin_headers, session):
    peer = Peer(
        user_id=1, iface="wg0", public_key="pk", private_key_enc="enc",
        address="10.10.0.2/32", allowed_ips="10.10.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    for i in range(5):
        session.add(TrafficStat(peer_id=peer.id, rx_bytes=i, tx_bytes=i))
    await session.commit()
    resp = await client.get("/traffic?limit=2", headers=admin_headers)
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_traffic_summary(client, admin_headers, session):
    from app.models import User, Role
    user = User(name="Test User", role=Role.user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    peer = Peer(
        user_id=user.id, iface="wg0", public_key="pk", private_key_enc="enc",
        address="10.10.0.2/32", allowed_ips="10.10.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    ts = TrafficStat(peer_id=peer.id, ts=datetime.utcnow(), rx_bytes=100, tx_bytes=200, delta_rx=50, delta_tx=100)
    session.add(ts)
    await session.commit()
    resp = await client.get("/traffic/summary?hours=24", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rx"] == 50
    assert data[0]["name"] == "Test User"


@pytest.mark.asyncio
async def test_list_traffic_no_auth(client):
    resp = await client.get("/traffic")
    assert resp.status_code == 401
