import pytest
from unittest.mock import AsyncMock, patch, call

from app.wg import WireGuardManager


@pytest.mark.asyncio
async def test_apply_speed_limit_creates_tc_rules():
    """apply_speed_limit should call tc commands."""
    calls = []

    async def mock_subprocess(*args, **kwargs):
        calls.append(args)
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        wg = WireGuardManager()
        await wg.apply_speed_limit("10.10.0.2", 20)

    # Should have made tc calls
    assert len(calls) >= 1
    # First call should be tc
    assert calls[0][0] == "tc"


@pytest.mark.asyncio
async def test_apply_speed_limit_zero_removes_limit():
    """Speed limit 0 should remove tc rules."""
    calls = []

    async def mock_subprocess(*args, **kwargs):
        calls.append(args)
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.returncode = 0
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        wg = WireGuardManager()
        await wg.remove_speed_limit("10.10.0.2")

    assert len(calls) >= 1


@pytest.mark.asyncio
async def test_apply_speed_limit_handles_failure():
    """Should not raise on tc failure."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"", b"RTNETLINK error"))
    proc.returncode = 2

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        wg = WireGuardManager()
        await wg.apply_speed_limit("10.10.0.2", 50)  # should not raise
