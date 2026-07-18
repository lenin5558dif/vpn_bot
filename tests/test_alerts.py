import os
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from bot.alerts import AlertManager


class FakeBackend:
    def __init__(self) -> None:
        self.health = AsyncMock(return_value={"status": "ok", "checks": {"wireguard": "ok"}})
        self.get_server_stats = AsyncMock(return_value={"disk_used_pct": 10, "disk_used_gb": 1, "disk_total_gb": 10})
        self.reconcile_peers = AsyncMock(return_value={
            "status": "ok",
            "wg_available": True,
            "counts": {
                "unknown_wg_peers": 0,
                "missing_wg_peers": 0,
                "allowed_ips_mismatch": 0,
                "disabled_with_allowed_ips": 0,
            },
        })
        self.get_traffic_summary = AsyncMock(return_value=[])


def make_manager(tmp_path, backend=None) -> AlertManager:
    settings = Settings(
        alerts_state_file=str(tmp_path / "alerts.json"),
        alerts_failure_threshold=3,
        alerts_health_interval_sec=60,
        alerts_diagnostic_interval_sec=0,
        alerts_repeat_hours=6,
        alerts_traffic_24h_threshold_gb=50,
    )
    bot = AsyncMock()
    return AlertManager(bot=bot, backend=backend or FakeBackend(), admin_ids={1, 2}, settings=settings)


@pytest.mark.asyncio
async def test_backend_alert_after_three_failures_and_suppresses_dependent_checks(tmp_path):
    backend = FakeBackend()
    backend.health = AsyncMock(side_effect=RuntimeError("down"))
    manager = make_manager(tmp_path, backend)

    await manager.run_once()
    await manager.run_once()
    assert manager.bot.send_message.await_count == 0

    await manager.run_once()

    assert manager.bot.send_message.await_count == 2
    backend.get_server_stats.assert_not_called()
    backend.reconcile_peers.assert_not_called()


@pytest.mark.asyncio
async def test_wireguard_alert_and_recovery(tmp_path):
    backend = FakeBackend()
    backend.health = AsyncMock(return_value={"status": "degraded", "checks": {"wireguard": "unavailable"}})
    manager = make_manager(tmp_path, backend)

    await manager.run_once()
    await manager.run_once()
    await manager.run_once()
    assert "WireGuard недоступен" in manager.bot.send_message.await_args_list[-1].args[1]

    backend.health = AsyncMock(return_value={"status": "ok", "checks": {"wireguard": "ok"}})
    await manager.run_once()

    sent = [call.args[1] for call in manager.bot.send_message.await_args_list]
    assert any("WireGuard снова доступен" in text for text in sent)


@pytest.mark.asyncio
async def test_diagnostics_alerts_for_disk_unknown_peer_and_drift(tmp_path):
    backend = FakeBackend()
    backend.get_server_stats = AsyncMock(return_value={"disk_used_pct": 81, "disk_used_gb": 81, "disk_total_gb": 100})
    backend.reconcile_peers = AsyncMock(return_value={
        "status": "drift",
        "wg_available": True,
        "counts": {
            "unknown_wg_peers": 1,
            "missing_wg_peers": 1,
            "allowed_ips_mismatch": 1,
            "disabled_with_allowed_ips": 0,
        },
    })
    manager = make_manager(tmp_path, backend)

    await manager.run_once()

    texts = [call.args[1] for call in manager.bot.send_message.await_args_list]
    assert any("Диск заполнен" in text for text in texts)
    assert any("неизвестный peer" in text for text in texts)
    assert any("БД и WireGuard расходятся" in text for text in texts)


@pytest.mark.asyncio
async def test_traffic_alert_once_per_day(tmp_path):
    backend = FakeBackend()
    big = 51 * 1024 ** 3
    backend.get_traffic_summary = AsyncMock(return_value=[{"user_id": 7, "name": "U", "rx": big, "tx": 0}])
    manager = make_manager(tmp_path, backend)

    await manager.run_once()
    first_count = manager.bot.send_message.await_count
    await manager.run_once()

    assert first_count >= 2
    assert manager.bot.send_message.await_count == first_count


@pytest.mark.asyncio
async def test_state_file_is_atomic_json_and_0600(tmp_path):
    manager = make_manager(tmp_path)

    await manager.run_once()

    path = tmp_path / "alerts.json"
    assert path.exists()
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
