import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta

from app.tasks import TrafficPoller
from app.models import Peer, PeerStatus, TrafficStat
from app.database import SessionLocal


@pytest.mark.asyncio
async def test_poller_start_stop():
    poller = TrafficPoller(SessionLocal, "wg0")
    poller.start()
    assert poller._task is not None
    await poller.stop()
    assert poller._task is None


@pytest.mark.asyncio
async def test_poller_stop_when_not_started():
    poller = TrafficPoller(SessionLocal, "wg0")
    await poller.stop()  # should not raise


@pytest.mark.asyncio
async def test_collect_no_wg(session):
    """collect should handle wg not available gracefully."""
    poller = TrafficPoller(SessionLocal, "wg0")
    await poller.collect()  # wg not installed, should return silently


@pytest.mark.asyncio
async def test_collect_with_mock_wg_output(session):
    """Mock wg show transfer output and verify stats are recorded."""
    peer = Peer(
        user_id=1, iface="wg0", public_key="testpubkey123",
        private_key_enc="enc", address="10.10.0.2/32",
        allowed_ips="10.10.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"testpubkey123\t1000\t2000\n", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        poller = TrafficPoller(SessionLocal, "wg0")
        await poller.collect()

    # Verify stats were recorded
    from sqlmodel import select
    async with SessionLocal() as s:
        result = await s.exec(select(TrafficStat).where(TrafficStat.peer_id == peer.id))
        stats = result.all()
        assert len(stats) == 1
        assert stats[0].rx_bytes == 1000
        assert stats[0].tx_bytes == 2000


@pytest.mark.asyncio
async def test_cleanup(session):
    """cleanup should delete old records."""
    peer = Peer(
        user_id=1, iface="wg0", public_key="pk",
        private_key_enc="enc", address="10.10.0.2/32",
        allowed_ips="10.10.0.2/32", status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)

    # Add old and new stats
    old_ts = TrafficStat(
        peer_id=peer.id, ts=datetime.utcnow() - timedelta(days=10),
        rx_bytes=100, tx_bytes=200,
    )
    new_ts = TrafficStat(
        peer_id=peer.id, ts=datetime.utcnow(),
        rx_bytes=300, tx_bytes=400,
    )
    session.add(old_ts)
    session.add(new_ts)
    await session.commit()

    poller = TrafficPoller(SessionLocal, "wg0")
    await poller.cleanup()

    from sqlmodel import select
    async with SessionLocal() as s:
        result = await s.exec(select(TrafficStat))
        stats = result.all()
        assert len(stats) == 1
        assert stats[0].rx_bytes == 300
