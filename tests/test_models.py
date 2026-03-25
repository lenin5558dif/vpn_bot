import pytest
from datetime import datetime

from app.models import (
    User, Request, Peer, Config, TrafficStat, AuditLog,
    Role, RequestStatus, PeerStatus,
)


@pytest.mark.asyncio
async def test_create_user(session):
    user = User(name="Test", contact="test@mail.com", role=Role.user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    assert user.id is not None
    assert user.role == Role.user
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_create_request(session):
    user = User(name="U")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    req = Request(user_id=user.id, status=RequestStatus.new, comment="hi")
    session.add(req)
    await session.commit()
    await session.refresh(req)
    assert req.id is not None
    assert req.status == RequestStatus.new


@pytest.mark.asyncio
async def test_create_peer(session):
    user = User(name="U")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    peer = Peer(
        user_id=user.id, iface="wg0", public_key="pk",
        private_key_enc="enc", address="10.10.0.2/32",
        allowed_ips="10.10.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    assert peer.id is not None
    assert peer.speed_limit_mbps == 20


@pytest.mark.asyncio
async def test_create_config(session):
    user = User(name="U")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    peer = Peer(
        user_id=user.id, iface="wg0", public_key="pk",
        private_key_enc="enc", address="10.0.0.2/32",
        allowed_ips="10.0.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    cfg = Config(peer_id=peer.id, download_token="tok123")
    session.add(cfg)
    await session.commit()
    await session.refresh(cfg)
    assert cfg.id is not None


@pytest.mark.asyncio
async def test_create_traffic_stat(session):
    user = User(name="U")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    peer = Peer(
        user_id=user.id, iface="wg0", public_key="pk",
        private_key_enc="enc", address="10.0.0.2/32",
        allowed_ips="10.0.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    ts = TrafficStat(peer_id=peer.id, rx_bytes=100, tx_bytes=200)
    session.add(ts)
    await session.commit()
    await session.refresh(ts)
    assert ts.delta_rx == 0


@pytest.mark.asyncio
async def test_create_audit_log(session):
    log = AuditLog(action="login", ip="1.2.3.4", meta={"browser": "chrome"})
    session.add(log)
    await session.commit()
    await session.refresh(log)
    assert log.id is not None
    assert log.meta["browser"] == "chrome"


def test_enum_values():
    assert Role.user.value == "user"
    assert Role.admin.value == "admin"
    assert RequestStatus.new.value == "new"
    assert RequestStatus.approved.value == "approved"
    assert RequestStatus.rejected.value == "rejected"
    assert PeerStatus.pending.value == "pending"
    assert PeerStatus.active.value == "active"
    assert PeerStatus.disabled.value == "disabled"
    assert PeerStatus.banned.value == "banned"
