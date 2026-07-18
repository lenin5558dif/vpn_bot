import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.wg import WireGuardError, WireGuardManager


@pytest.mark.asyncio
async def test_generate_keys_unavailable_fails_closed():
    wg = WireGuardManager()
    with patch("asyncio.create_subprocess_exec", side_effect=OSError("no awg")):
        with pytest.raises(WireGuardError):
            await wg.generate_keys()


@pytest.mark.asyncio
async def test_generate_keys_with_wg():
    mock_proc1 = AsyncMock()
    mock_proc1.communicate = AsyncMock(return_value=(b"privkey123\n", b""))
    mock_proc1.returncode = 0
    mock_proc2 = AsyncMock()
    mock_proc2.communicate = AsyncMock(return_value=(b"pubkey456\n", b""))
    mock_proc2.returncode = 0

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
    public_key = "sensitive-public-key-material"
    mock_proc.communicate = AsyncMock(return_value=(b"", f"failed for {public_key}".encode()))
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        wg = WireGuardManager()
        with pytest.raises(WireGuardError) as exc_info:
            await wg.apply_peer(public_key, "10.10.0.2/32")

    assert public_key not in str(exc_info.value)
    assert "<peer-key>" in str(exc_info.value)


@pytest.mark.asyncio
async def test_apply_peer_exception():
    with patch("asyncio.create_subprocess_exec", side_effect=OSError("no wg")):
        wg = WireGuardManager()
        with pytest.raises(WireGuardError):
            await wg.apply_peer("pubkey", "10.10.0.2/32")


@pytest.mark.asyncio
async def test_apply_peer_timeout_kills_process_and_raises():
    mock_proc = MagicMock()

    async def communicate(input=None):
        import asyncio

        await asyncio.sleep(1)
        return b"", b""

    mock_proc.communicate = communicate
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("app.wg.settings.subprocess_timeout_sec", 0.01):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            wg = WireGuardManager()
            with pytest.raises(WireGuardError, match="timed out"):
                await wg.apply_peer("pubkey", "10.10.0.2/32")

    mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_remove_peer_failure():
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        wg = WireGuardManager()
        with pytest.raises(WireGuardError):
            await wg.remove_peer("pubkey")


@pytest.mark.asyncio
async def test_remove_peer_exception():
    with patch("asyncio.create_subprocess_exec", side_effect=OSError("no wg")):
        wg = WireGuardManager()
        with pytest.raises(WireGuardError):
            await wg.remove_peer("pubkey")


@pytest.mark.asyncio
async def test_apply_speed_limit():
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0
    wg = WireGuardManager()
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await wg.apply_speed_limit("10.10.0.2", 20)
