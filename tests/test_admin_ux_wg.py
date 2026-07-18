from unittest.mock import AsyncMock, patch

import pytest

from app.wg import WireGuardError, WireGuardManager


@pytest.mark.asyncio
async def test_runtime_snapshot_parses_dump_and_ignores_interface_private_key():
    dump = "\n".join([
        "private-interface-key\tpublic-interface-key\t51820\toff",
        "peer-public-1\tpsk\t1.2.3.4:51820\t10.10.0.2/32\t123\t456\t789\t25",
        "peer-public-2\tpsk\t(none)\t(none)\tbad\tnot-int\t3\t25",
        "malformed line",
    ])
    manager = WireGuardManager()

    with patch.object(manager, "_run", AsyncMock(return_value=dump)):
        snapshot = await manager.runtime_snapshot()

    assert snapshot["available"] is True
    assert "private-interface-key" not in snapshot["peers"]
    assert snapshot["peers"]["peer-public-1"] == {
        "allowed_ips": "10.10.0.2/32",
        "latest_handshake": 123,
        "rx_bytes": 456,
        "tx_bytes": 789,
    }
    assert snapshot["peers"]["peer-public-2"] == {
        "allowed_ips": "",
        "latest_handshake": 0,
        "rx_bytes": 0,
        "tx_bytes": 3,
    }


@pytest.mark.asyncio
async def test_runtime_snapshot_returns_sanitized_unavailable_on_wg_error():
    manager = WireGuardManager()

    with patch.object(manager, "_run", AsyncMock(side_effect=WireGuardError("secret stderr"))):
        snapshot = await manager.runtime_snapshot()

    assert snapshot == {"available": False, "error": "unavailable", "peers": {}}
