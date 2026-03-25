import pytest
from unittest.mock import AsyncMock, patch

from app.wg import WireGuardManager


@pytest.mark.asyncio
async def test_generate_keys_fallback():
    wg = WireGuardManager()
    priv, pub = await wg.generate_keys()
    assert len(priv) == 64
    assert len(pub) == 64
    assert priv != pub


@pytest.mark.asyncio
async def test_generate_keys_with_wg():
    mock_proc1 = AsyncMock()
    mock_proc1.communicate = AsyncMock(return_value=(b"privkey123\n", b""))
    mock_proc2 = AsyncMock()
    mock_proc2.communicate = AsyncMock(return_value=(b"pubkey456\n", b""))

    with patch("asyncio.create_subprocess_exec", side_effect=[mock_proc1, mock_proc2]):
        wg = WireGuardManager()
        priv, pub = await wg.generate_keys()
        assert priv == "privkey123"
        assert pub == "pubkey456"


def test_allocate_ip():
    wg = WireGuardManager()
    ip = wg.allocate_ip([])
    assert ip == "10.10.0.2/32"


def test_allocate_ip_with_used():
    wg = WireGuardManager()
    ip = wg.allocate_ip(["10.10.0.2/32", "10.10.0.3/32"])
    assert ip == "10.10.0.4/32"


def test_allocate_ip_invalid_entries():
    wg = WireGuardManager()
    ip = wg.allocate_ip(["invalid", "10.10.0.2/32"])
    assert ip == "10.10.0.3/32"


def test_render_peer_config():
    wg = WireGuardManager()
    config = wg.render_peer_config("myprivkey", "10.10.0.2/32")
    assert "[Interface]" in config
    assert "PrivateKey = myprivkey" in config
    assert "Address = 10.10.0.2/32" in config
    assert "[Peer]" in config
    assert "AllowedIPs = 0.0.0.0/0" in config


@pytest.mark.asyncio
async def test_apply_peer_failure():
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error msg"))
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        wg = WireGuardManager()
        await wg.apply_peer("pubkey", "10.10.0.2/32")


@pytest.mark.asyncio
async def test_apply_peer_exception():
    with patch("asyncio.create_subprocess_exec", side_effect=OSError("no wg")):
        wg = WireGuardManager()
        await wg.apply_peer("pubkey", "10.10.0.2/32")


@pytest.mark.asyncio
async def test_remove_peer_failure():
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        wg = WireGuardManager()
        await wg.remove_peer("pubkey")


@pytest.mark.asyncio
async def test_remove_peer_exception():
    with patch("asyncio.create_subprocess_exec", side_effect=OSError("no wg")):
        wg = WireGuardManager()
        await wg.remove_peer("pubkey")


@pytest.mark.asyncio
async def test_apply_speed_limit():
    wg = WireGuardManager()
    await wg.apply_speed_limit("10.10.0.2", 20)
